import tempfile
import threading
import unittest
from unittest.mock import Mock
from radio.store import Store
from radio.review import MetadataReview, review_key


class MetadataReviewTests(unittest.TestCase):
    def test_exact_matching_errors_persistence_and_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            song = dict(id='song',station_id='station',title='Hello',artist='Adele',status='approved')
            catalog = dict(stations=[dict(id='station',name='Pop',status='approved')],songs=[song])
            store.replace(catalog)
            search = Mock()
            review = MetadataReview(store, search, threading.Event())
            search.search.return_value = [dict(title='hello',artist='Adele')]
            self.assertEqual(review.check(song),'review')
            search.search.return_value = []
            self.assertEqual(review.check(song),'review')
            search.search.side_effect = RuntimeError('offline')
            self.assertEqual(review.check(song),'error')
            search.search.side_effect = None
            search.search.return_value = [dict(title='Hello',artist='Adele')]
            self.assertEqual(review.check(song),'matched')
            search.search.assert_called_with('Hello','Adele',limit=20)
            reopened = MetadataReview(Store(directory),search,threading.Event())
            self.assertEqual(reopened.results()[review_key(song)]['state'],'matched')
            self.assertNotIn(review_key(dict(song,title='HELLO')),reopened.results())
            self.assertEqual(store.snapshot(),catalog)

    def test_explicit_versions_unknown_errors_and_saved_results(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            song = dict(id='one', station_id='station', title='Song', artist='Artist', status='pending')
            search = Mock()
            review = MetadataReview(store, search, threading.Event())
            for ratings, expected in [(['explicit'], 'explicit'), (['cleaned'], 'cleaned'),
                                      (['notExplicit'], 'notExplicit'), (['explicit','cleaned'], 'ambiguous'),
                                      ([], 'unknown'), ([None], 'unknown')]:
                search.search.return_value = [dict(title='Song',artist='Artist',explicitness=r) for r in ratings]
                review.check(song)
                self.assertEqual(review.results()[review_key(song)]['explicit_state'], expected)
            search.search.side_effect = RuntimeError('offline')
            review.check(song)
            self.assertEqual(review.results()[review_key(song)]['explicit_state'], 'error')
            reopened = MetadataReview(Store(directory), search, threading.Event())
            self.assertEqual(reopened.results(), review.results())

    def test_scan_scopes_reuse_results_and_deduplicate_stations(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            song = dict(id='one', station_id='station', title='Song', artist='Artist', status='pending')
            other = dict(song,id='two',title='Other',status='approved')
            duplicate = dict(song,id='three')
            store.replace(dict(stations=[dict(id='station',name='Rock',status='approved')],songs=[song,other,duplicate]))
            search = Mock(); search.search.return_value = [dict(title='Song',artist='Artist',explicitness='explicit')]
            review = MetadataReview(store,search,threading.Event()); review.check(song)
            with patch('radio.review.threading.Thread') as worker:
                self.assertTrue(review.start(scope='pending'))
                self.assertEqual(worker.call_args.kwargs['args'][0], [])
                self.assertFalse(review.start(scope='all'))
                review.progress['running'] = False
                review.start(scope='unchecked',tool='explicit')
                self.assertEqual(worker.call_args.kwargs['args'][0],[other])
                review.progress['running'] = False
                review.start(scope='all')
                self.assertEqual(len(worker.call_args.kwargs['args'][0]),2)
                review.progress['running'] = False
                review.start(scope='song',song_id='one')
                self.assertEqual(worker.call_args.kwargs['args'][0],[song])
                review.progress['running'] = False
                with self.assertRaises(ValueError): review.start(scope='song',song_id='missing')
                with self.assertRaises(ValueError): review.start(scope='invalid')
