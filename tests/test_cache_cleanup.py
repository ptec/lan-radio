import tempfile
import unittest
from radio.store import Store, media_key


class CacheCleanupTests(unittest.TestCase):
    def test_cleanup_preserves_catalog_and_fences_old_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            song = dict(id='s',station_id='x',title='Keep',artist='Artist',status='pending')
            catalog = dict(stations=[dict(id='x',name='X',status='approved')],songs=[song])
            store.replace(catalog)
            store.path(song).write_bytes(b'keep')
            old = dict(song,title='Unused')
            store.path(old).write_bytes(b'old')
            other = store.cache/'notes.txt'; other.write_text('keep')
            self.assertEqual(store.clean_cache('unused',True)['files'],1)
            self.assertEqual(store.clean_cache('unused')['deleted'],1)
            self.assertTrue(store.path(song).exists())
            generation = store.cache_generation()
            store.media_state(media_key(song),'failed',retry=99999999999)
            self.assertEqual(store.clean_cache('all')['deleted'],1)
            self.assertTrue(store.retry_due(media_key(song)))
            output = store.cache/'temporary.mp3'; output.write_bytes(b'old download')
            self.assertFalse(store.publish_audio(song,output,generation))
            store.media_state(media_key(song),'failed',generation=generation)
            self.assertNotIn(media_key(song),store.media_states())
            self.assertTrue(other.exists())
            self.assertEqual(store.snapshot(),catalog)
