import threading
import unittest
from unittest.mock import Mock, patch

import requests

from radio.search import SongSearch
from radio.web import create_app


class SongSearchTests(unittest.TestCase):
    @patch('radio.search.requests.get')
    def test_metadata_deduplication_ranking_and_cache(self, get):
        get.return_value.json.return_value = {'results': [
            {'trackName': 'Other', 'artistName': 'Other'},
            {'trackName': 'Hello', 'artistName': 'Adele'},
            {'trackName': 'Hello', 'artistName': 'Adele'},
            {'trackName': 'No artist'}, None,
        ]}
        search = SongSearch()
        result = search.search('Hello', 'Adele')
        self.assertEqual(result[0], {'title': 'Hello', 'artist': 'Adele'})
        self.assertEqual(len(result), 2)
        self.assertEqual(search.search('HELLO', 'adele'), result)
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs['params']['term'], 'Hello Adele')
        self.assertEqual(get.call_args.kwargs['timeout'], 5)

    @patch('radio.search.requests.get')
    def test_shared_rate_limit_keeps_cached_results_available(self, get):
        get.return_value.json.return_value = {'results': []}
        search = SongSearch()
        for index in range(20):
            search.search(str(index), '')
        self.assertEqual(search.search('0', ''), [])
        with self.assertRaises(ValueError):
            search.search('new', '')
        self.assertEqual(get.call_count, 20)

    @patch('radio.search.requests.get')
    def test_route_validation_and_provider_failure(self, get):
        client = create_app(Mock(), Mock(), Mock(), threading.Event()).test_client()
        self.assertEqual(client.get('/api/song-suggestions?title=x').json['songs'], [])
        self.assertEqual(client.get('/api/song-suggestions', query_string={'title': 'x'*201}).status_code, 400)
        get.assert_not_called()
        get.side_effect = requests.exceptions.SSLError('private diagnostic')
        response = client.get('/api/song-suggestions?artist=Adele')
        self.assertEqual(response.status_code, 503)
        self.assertIn('manually', response.json['error'])
        self.assertNotIn('private diagnostic', response.json['error'])
        get.side_effect = None
        get.return_value.json.return_value = {'results': [{'trackName': 'Hello', 'artistName': 'Adele'}]}
        response = client.get('/api/song-suggestions?artist=Adele')
        self.assertEqual(response.json['songs'][0]['title'], 'Hello')
