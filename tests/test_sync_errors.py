import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from radio.store import Store
from radio.sync import SheetSync


class SyncErrorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.sync = SheetSync(self.store, SimpleNamespace(refresh=lambda: None),
                              'https://example.test/exec', 'secret-token')

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
