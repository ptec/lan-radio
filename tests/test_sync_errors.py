import tempfile
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import requests
from radio.store import Store
from radio.sync import SheetSync, SyncError


class SyncErrorTests(unittest.TestCase):
    def test_form_encoded_payload(self):
        response = Mock(ok=True)
        response.json.return_value = {'ok':True}
        with patch('radio.sync.requests.post', return_value=response) as post:
            self.sync.call(action='submit', requests=[{'title':'A&B + 100% café'}])
        self.assertNotIn('json', post.call_args.kwargs)
        payload = json.loads(post.call_args.kwargs['data']['payload'])
        self.assertEqual(payload['requests'][0]['title'], 'A&B + 100% café')
        self.assertEqual(payload['token'], 'secret-token')
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.sync = SheetSync(self.store, SimpleNamespace(refresh=lambda: None),
                              'https://script.google.com/private-deployment/exec', 'secret-token')

    def test_apps_script_error_preserved_and_secrets_redacted(self):
        response = Mock(ok=True)
        response.json.return_value = {'ok': False, 'error': 'Unauthorized secret-token https://example.test/private'}
        with patch('radio.sync.requests.post', return_value=response):
            with self.assertRaises(SyncError) as caught:
                self.sync.call(action='catalog')
        message = str(caught.exception)
        self.assertIn('Unauthorized', message)
        self.assertIn('Script Properties', message)
        self.assertNotIn('secret-token', message)
        self.assertNotIn('example.test', message)

    def test_non_json_and_http_errors_explain_deployment_problem(self):
        response = Mock(ok=True)
        response.json.side_effect = ValueError('HTML including secret-token')
        with patch('radio.sync.requests.post', return_value=response):
            with self.assertRaisesRegex(SyncError, 'non-JSON'):
                self.sync.call(action='catalog')
        response = Mock(ok=False, status_code=403)
        with patch('radio.sync.requests.post', return_value=response):
            with self.assertRaisesRegex(SyncError, 'HTTP 403'):
                self.sync.call(action='catalog')

    def test_network_error_categories_are_actionable_without_raw_urls(self):
        for error, expected in [(requests.exceptions.Timeout('secret-token'), '45 seconds'),
                                (requests.exceptions.SSLError('secret-token'), 'certificate'),
                                (requests.exceptions.ConnectionError('secret-token'), 'DNS')]:
            with self.subTest(error=type(error).__name__), patch('radio.sync.requests.post', side_effect=error):
                with self.assertRaises(SyncError) as caught:
                    self.sync.call(action='catalog')
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn('secret-token', str(caught.exception))

    def test_failure_history_survives_restart_and_next_success(self):
        self.sync.request_manual()
        with patch.object(self.sync, 'pull', side_effect=ValueError('Deploy schema version 2 secret-token')):
            self.sync.tick()
        self.assertIn('schema version 2', self.sync.error)
        self.assertNotIn('secret-token', self.sync.error)
        reopened = Store(self.directory.name)
        self.assertEqual(reopened.diagnostics()['recent_sync_failures'][0]['error'], self.sync.error)
        self.sync.manual_requested = True
        with patch.object(self.sync, 'pull'):
            self.sync.tick()
        self.assertIsNone(self.sync.error)
        self.assertEqual(len(reopened.diagnostics()['recent_sync_failures']), 1)
        for _ in range(15):
            reopened.record_sync_failure('error')
        self.assertEqual(len(reopened.diagnostics()['recent_sync_failures']), 10)

    def test_redirect_tls_diagnostics_do_not_leak_urls_or_payloads(self):
        import ssl
        from urllib3.exceptions import MaxRetryError, SSLError
        target = requests.Request('GET','https://script.googleusercontent.com/macros/echo?private=secret-token').prepare()
        original = ssl.SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] private-data')
        wrapped = requests.exceptions.SSLError(MaxRetryError(None, '/private-url', SSLError(original)),request=target)
        def fail(url, **kwargs):
            kwargs['hooks']['response'](SimpleNamespace(url=url,status_code=302))
            raise wrapped
        with patch('radio.sync.requests.post',side_effect=fail), self.assertLogs('radio.sync',level='WARNING') as logs:
            with self.assertRaises(SyncError) as caught: self.sync.call(action='edit_batch')
        text = str(caught.exception)
        self.assertIn('save edits',text)
        self.assertIn('response redirect',text)
        self.assertIn('script.googleusercontent.com',text)
        self.assertIn('CERTIFICATE_VERIFY_FAILED',text)
        for secret in ('secret-token','private-data','private-url','macros/echo'):
            self.assertNotIn(secret,text+' '.join(logs.output))

    def test_generic_tls_is_not_reported_as_certificate_failure(self):
        with patch('radio.sync.requests.post',side_effect=requests.exceptions.SSLError('[SSL: UNEXPECTED_EOF_WHILE_READING] secret-token')):
            with self.assertRaises(SyncError) as caught: self.sync.call(action='catalog')
        self.assertIn('TLS connection failed',str(caught.exception))
        self.assertIn('UNEXPECTED_EOF_WHILE_READING',str(caught.exception))
        self.assertIn('deployment request',str(caught.exception))
        self.assertNotIn('secret-token',str(caught.exception))

    def test_redirect_http_status_is_distinguished(self):
        def reply(url, **kwargs):
            hook=kwargs['hooks']['response']
            hook(SimpleNamespace(url=url,status_code=302))
            response=SimpleNamespace(ok=False,status_code=404,url='https://script.googleusercontent.com/private',request=None)
            hook(response)
            return response
        with patch('radio.sync.requests.post',side_effect=reply) as post, patch('radio.sync.time.sleep'):
            with self.assertRaises(SyncError) as caught: self.sync.call(action='catalog')
        self.assertEqual(post.call_count,3)
        self.assertIn('response redirect',str(caught.exception))
        self.assertIn('script.googleusercontent.com HTTP 404',str(caught.exception))


    def test_catalog_redirect_retry_recovers_without_retrying_writes(self):
        calls = []
        def reply(url, **kwargs):
            calls.append(json.loads(kwargs['data']['payload'])['action'])
            kwargs['hooks']['response'](SimpleNamespace(url=url,status_code=302))
            response = Mock(ok=len(calls) > 1, status_code=404 if len(calls) == 1 else 200,
                            url='https://script.googleusercontent.com/private', request=None)
            response.json.return_value = {'ok':True}
            kwargs['hooks']['response'](response)
            return response
        with patch('radio.sync.requests.post',side_effect=reply), patch('radio.sync.time.sleep') as sleep:
            self.assertEqual(self.sync.call(action='catalog'), {'ok':True})
            self.assertEqual(calls,['catalog','catalog'])
            sleep.assert_called_once_with(1)
            calls.clear()
            with self.assertRaises(SyncError): self.sync.call(action='edit_batch')
            self.assertEqual(calls,['edit_batch'])
