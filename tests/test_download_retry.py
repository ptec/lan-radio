import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from radio.download import _download_one, pending_downloads
from radio.store import Store, media_key
from radio.web import create_app


class DownloadRetryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name)
        self.song = dict(id='song', station_id='station', title='Hello', artist='Adele', status='approved')
        self.catalog = dict(stations=[dict(id='station', name='Pop', status='approved')], songs=[self.song])
        self.store.replace(self.catalog)
        self.client = create_app(self.store, Mock(), Mock(), threading.Event()).test_client()
        self.url = '/api/stations/station/songs/song/retry'

    def test_failure_retry_and_success_lifecycle(self):
        with patch('radio.download.download', side_effect=RuntimeError('Download unavailable')):
            _download_one(self.song, self.store, 'ffmpeg', threading.Event())
        row = self.client.get('/api/stations/station/songs').json['songs'][0]
        self.assertEqual(row['download_status'], 'failed')
        self.assertTrue(row['can_retry'])
        self.assertEqual(pending_downloads(self.store), [])
        self.assertEqual(self.client.post(self.url, json={}).status_code, 202)
        self.assertEqual(self.client.post(self.url, json={}).status_code, 409)
        self.assertEqual(pending_downloads(self.store), [self.song])
        row = self.client.get('/api/stations/station/songs').json['songs'][0]
        self.assertEqual(row['download_status'], 'queued')
        self.assertFalse(row['can_retry'])
        def succeed(*args):
            self.assertEqual(self.store.media_states()[media_key(self.song)], 'downloading')
            self.store.path(self.song).write_bytes(b'cached')
        with patch('radio.download.download', side_effect=succeed):
            _download_one(self.song, self.store, 'ffmpeg', threading.Event())
        row = self.client.get('/api/stations/station/songs').json['songs'][0]
        self.assertEqual(row['download_status'], 'ready')
        self.assertFalse(row['can_retry'])
        self.assertEqual(pending_downloads(self.store), [])

    def test_retry_requires_current_approval_and_same_origin(self):
        self.store.media_state(media_key(self.song), 'failed', 'failure', time.time()+3600)
        self.assertEqual(self.client.post(self.url).status_code, 415)
        self.assertEqual(self.client.post(self.url, json={}, headers={'Origin':'https://elsewhere.example'}).status_code, 403)
        for status in ('pending', 'rejected'):
            self.song['status'] = status
            self.store.replace(self.catalog)
            self.assertEqual(self.client.post(self.url, json={}).status_code, 404)
        self.song['status'] = 'approved'
        self.catalog['stations'][0]['status'] = 'pending'
        self.store.replace(self.catalog)
        self.assertEqual(self.client.post(self.url, json={}).status_code, 404)
        self.assertFalse(self.client.get('/api/stations/station/songs').json['songs'][0]['can_retry'])
        self.catalog['songs'] = []
        self.store.replace(self.catalog)
        self.assertEqual(self.client.post(self.url, json={}).status_code, 404)
