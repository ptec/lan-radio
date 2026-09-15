import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from radio.store import Store
from radio.sync import SheetSync
from radio.web import create_app


class SyncFeatures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.broadcasts = SimpleNamespace(refresh=lambda: None, get=lambda _: None)
        self.sync = SheetSync(self.store, self.broadcasts, 'url', 'token')
        self.clock = patch('radio.sync.time.time', return_value=1000)
        self.time = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.catalog = {'schema_version': 2, 'stations': []}
        self.app = create_app(self.store, self.broadcasts, self.sync, threading.Event())
        self.client = self.app.test_client()

    def add_request(self):
        return self.store.enqueue(dict(type='station', name='Jazz'))

    def answer(self, **body):
        if body['action'] == 'submit':
            return {'acknowledged': [r['id'] for r in body['requests']]}
        return self.catalog

    def test_idle_never_calls_sheets_including_startup(self):
        with patch.object(self.sync, 'call') as call:
            for now in (1000, 2000, 1000000):
                self.time.return_value = now
                self.sync.tick()
            call.assert_not_called()
        self.assertIsNone(self.sync.status()['next_sync_at'])

    def test_first_request_sets_five_minute_deadline_without_debounce(self):
        self.add_request()
        self.assertEqual(self.sync.status()['next_sync_at'], 1300)
        self.time.return_value = 1200
        self.add_request()
        with patch.object(self.sync, 'call', side_effect=self.answer) as call:
            self.sync.tick()
            call.assert_not_called()
            self.time.return_value = 1300
            self.sync.tick()
            self.assertEqual([c.kwargs['action'] for c in call.call_args_list], ['submit', 'catalog'])
            self.assertEqual(self.store.pending(), [])
            call.reset_mock()
            self.time.return_value = 100000
            self.sync.tick()
            call.assert_not_called()

    def test_restart_keeps_original_deadline(self):
        self.add_request()
        self.time.return_value = 1200
        restarted = SheetSync(Store(self.temp.name), self.broadcasts, 'url', 'token')
        self.assertEqual(restarted.status()['next_sync_at'], 1300)

    def test_manual_sync_works_without_outbound_requests_and_coalesces(self):
        self.assertEqual(self.client.post('/api/sync', json={}).status_code, 202)
        self.assertEqual(self.client.post('/api/sync', json={}).status_code, 202)
        with patch.object(self.sync, 'call', side_effect=self.answer) as call:
            self.sync.tick()
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.kwargs['action'], 'catalog')
        self.assertEqual(self.client.post('/api/sync', json={}).status_code, 429)
        self.time.return_value = 1031
        self.assertEqual(self.client.post('/api/sync', json={}).status_code, 202)

    def test_manual_sync_pushes_all_batches_then_pulls(self):
        for _ in range(105):
            self.add_request()
        self.sync.request_manual()
        with patch.object(self.sync, 'call', side_effect=self.answer) as call:
            self.sync.tick()
            self.assertEqual([c.kwargs['action'] for c in call.call_args_list], ['submit', 'submit', 'catalog'])
        self.assertEqual(self.store.pending(), [])

    def test_upload_failure_retries_after_delay_and_still_pulls(self):
        self.add_request()
        self.sync.request_manual()
        def fail_upload(**body):
            if body['action'] == 'submit':
                raise TimeoutError()
            return self.catalog
        with patch.object(self.sync, 'call', side_effect=fail_upload) as call:
            self.sync.tick()
            self.assertEqual(call.call_count, 2)
            self.assertEqual(len(self.store.pending()), 1)
            call.reset_mock()
            self.time.return_value = 1299
            self.sync.tick()
            call.assert_not_called()
            self.time.return_value = 1300
            self.sync.tick()
            self.assertEqual(call.call_count, 2)

    def test_failed_pull_with_empty_queue_requires_manual_retry(self):
        self.sync.request_manual()
        with patch.object(self.sync, 'call', side_effect=TimeoutError()) as call:
            self.sync.tick()
            self.assertIn('Catalog sync failed', self.sync.error)
            self.time.return_value = 100000
            self.sync.tick()
            self.assertEqual(call.call_count, 1)

    def test_sync_rejects_cross_origin_and_unconfigured_requests(self):
        self.assertEqual(self.client.post('/api/sync').status_code, 415)
        self.assertEqual(self.client.post('/api/sync', json={}, headers={'Origin': 'https://other.test'}).status_code, 403)
        self.sync.url = ''
        self.assertEqual(self.client.post('/api/sync', json={}).status_code, 503)

    def test_song_collection_includes_all_statuses_and_local_pending(self):
        self.store.replace(dict(stations=[dict(id='rock', name='Rock', status='approved'), dict(id='jazz', name='Jazz', status='pending')], songs=[
            dict(id='a', station_id='rock', title='Approved', artist='Artist', status='approved'),
            dict(id='b', station_id='rock', title='Pending', artist='Artist', status='pending'),
            dict(id='c', station_id='rock', title='Rejected', artist='Artist', status='rejected')]))
        self.store.enqueue(dict(type='song', station='Rock', title='New request', artist='Artist'))
        self.store.enqueue(dict(type='song', station='Rock', title='Pending', artist='Artist'))
        body = self.client.get('/api/stations/rock/songs').get_json()
        self.assertEqual([s['title'] for s in body['songs']], ['Approved', 'Pending', 'Rejected', 'New request'])
        self.assertTrue(body['songs'][3]['queued'])
        self.assertFalse(body['songs'][1]['queued'])
        self.assertEqual(self.client.get('/api/stations/jazz/songs').status_code, 200)
        self.assertEqual(self.client.get('/api/stations/missing/songs').status_code, 404)
        self.assertEqual(len(self.client.get('/api/stations').get_json()['stations']), 2)
        self.store.replace(dict(stations=[], songs=[]))
        self.assertEqual(self.client.get('/api/stations/rock/songs').status_code, 404)

    def test_collection_includes_local_requests_beyond_first_batch(self):
        self.store.replace(dict(stations=[dict(id='rock', name='Rock', status='approved')], songs=[]))
        for _ in range(101):
            self.add_request()
        self.store.enqueue(dict(type='song', station='Rock', title='Last', artist='Artist'))
        self.assertEqual(self.client.get('/api/stations/rock/songs').get_json()['songs'][0]['title'], 'Last')


if __name__ == '__main__':
    unittest.main()
