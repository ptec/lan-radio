import tempfile
import unittest
from unittest.mock import patch
from radio.store import Store


class PlaybackIndexTests(unittest.TestCase):
    def test_hot_path_no_database_reads_and_immediate_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            catalog = {'stations':[dict(id='s',name='Station',status='approved')],
                       'songs':[dict(id='one',station_id='s',title='Song',artist='Artist',status='approved')]}
            store.replace(catalog)
            with patch.object(store, 'connect', side_effect=AssertionError('Playback accessed SQLite')):
                for _ in range(100):
                    self.assertTrue(store.playback_approved('s','one'))
                rows = store.playback_songs('s')
                rows[0]['title'] = 'Caller mutation'
                self.assertEqual(store.playback_songs('s')[0]['title'],'Song')
            catalog['songs'][0]['status'] = 'rejected'
            store.replace(catalog)
            self.assertFalse(store.playback_approved('s','one'))
            self.assertEqual(store.playback_songs('s'),[])
            catalog['songs'][0]['status'] = 'approved'
            catalog['stations'][0]['status'] = 'pending'
            store.replace(catalog)
            self.assertFalse(store.playback_approved('s','one'))

    def test_restart_loads_once_and_other_process_reads_current_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = Store(directory)
            reader = Store(directory)
            catalog = {'stations':[dict(id='s',name='Station',status='approved')],
                       'songs':[dict(id='one',station_id='s',title='Song',artist='Artist',status='approved')]}
            writer.replace(catalog)
            restarted = Store(directory)
            with patch.object(restarted,'snapshot',wraps=restarted.snapshot) as snapshot:
                self.assertTrue(restarted.playback_approved('s','one'))
                restarted.playback_songs('s')
                snapshot.assert_called_once()
            self.assertEqual(len(reader.approved()),1)
            catalog['songs'] = []
            writer.replace(catalog)
            self.assertEqual(reader.approved(),[])
