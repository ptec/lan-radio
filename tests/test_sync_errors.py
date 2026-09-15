import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import requests
from radio.store import Store
from radio.sync import SheetSync, SyncError


class SyncErrorTests(unittest.TestCase):
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
