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
