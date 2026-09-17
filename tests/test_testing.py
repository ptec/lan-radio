import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from radio.store import Store
from radio.web import create_app


class TestingPageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(temp.name)
        self.song = dict(id='song', station_id='station', title='Song', artist='Artist', status='approved', youtube_id='')
        self.store.replace(dict(stations=[dict(id='station', name='Rock', status='approved')], songs=[self.song]))
        self.sync = Mock(lock=threading.Lock(), running=False, url='configured', token='secret', last_success=None, error=None)
        with patch.dict('os.environ', {'TESTING_PASSWORD':'test-password'}):
            self.client = create_app(self.store, Mock(), self.sync, threading.Event()).test_client()
        self.auth = {}

    def edit(self, **extra):
        return self.client.post('/api/debug/edit', headers=self.auth, json=dict(id='song',
            original={k:self.song[k] for k in ('title','artist','status','youtube_id')},
            changes=dict(title='Corrected', artist='Artist', youtube_id='abcdefghijk'), **extra))

    def test_auth_and_preview_range(self):
        self.assertEqual(self.client.get('/debug').status_code, 302)
        self.assertEqual(self.client.get('/testing').status_code, 404)
        self.assertNotIn('WWW-Authenticate', self.client.get('/api/debug').headers)
        self.assertEqual(self.client.post('/debug/login', data={'password':'wrong'}).status_code, 401)
        self.assertEqual(self.client.get('/api/debug').status_code, 401)
        self.assertEqual(self.client.get('/api/debug/audio/song').status_code, 401)
        self.assertEqual(self.client.post('/debug/login', data={'password':'test-password'}).status_code, 302)
        self.assertEqual(self.client.get('/debug', headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get('/api/debug/audio/song', headers=self.auth).status_code, 404)
        self.store.path(self.song).write_bytes(b'0123456789')
        response = self.client.get('/api/debug/audio/song', headers={**self.auth,'Range':'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data,b'2345')
        response.close()
        self.assertEqual(self.client.get('/api/debug',headers=self.auth).json['cache_files'], 1)

    def test_save_conflicts_and_validation(self):
        self.client.post('/debug/login', data={'password':'test-password'})
        self.sync.call.return_value = {'ok':True}
        self.assertEqual(self.edit().status_code,200)
        self.sync.pull.assert_called_once()
        self.assertEqual(self.sync.call.call_args.kwargs['original']['status'],'approved')
        self.sync.call.return_value = {'ok':True,'conflict':True,'error':'Changed'}
        self.assertEqual(self.edit().status_code,409)
        self.sync.running=True
        self.assertEqual(self.edit().status_code,409)
        self.sync.running=False
        self.assertEqual(self.client.post('/api/debug/edit',headers=self.auth,json={'changes':{}}).status_code,400)
        self.assertEqual(self.client.post('/api/debug/edit',headers={**self.auth,'Origin':'https://elsewhere'},json={}).status_code,403)

    def test_deferred_edits_refresh_once(self):
        self.client.post('/debug/login', data={'password':'test-password'})
        self.sync.call.return_value = {'ok': True}
        self.assertEqual(self.edit(defer_refresh=True).status_code, 200)
        self.sync.pull.assert_not_called()
        self.assertEqual(self.client.post('/api/debug/refresh', json={}).status_code, 200)
        self.sync.pull.assert_called_once()

    def test_batch_edits_use_one_remote_call_and_report_partial_failure(self):
        self.client.post('/debug/login', data={'password':'test-password'})
        original = {k:self.song[k] for k in ('title','artist','status','youtube_id')}
        edit = dict(id='song',original=original,changes=dict(title='New',artist='Artist',youtube_id=''))
        self.sync.call.return_value = {'results':[{'id':'song','saved':True}]}
        response = self.client.post('/api/debug/edits',json={'edits':[edit,dict(edit,id='removed')]})
        self.assertEqual(response.status_code,200)
        self.assertEqual({r['id']:r['saved'] for r in response.json['results']},{'song':True,'removed':False})
        self.sync.call.assert_called_once()
        self.assertEqual(self.sync.call.call_args.kwargs['action'],'edit_batch')
        self.sync.pull.assert_not_called()
