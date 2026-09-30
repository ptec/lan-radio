import json
import unittest
from unittest.mock import Mock, patch
import requests
from radio import gas


class GasTests(unittest.TestCase):
    def test_get_and_post_use_requests_with_query_and_no_body(self):
        response = Mock(ok=True)
        response.json.return_value = dict(ok=True, content=[])
        with patch('radio.gas.requests.get', return_value=response) as get:
            gas.gas_get_station('Rock & Roll', 'https://example.test/exec')
            self.assertEqual(json.loads(get.call_args.kwargs['params']['q']),
                             dict(action='getStation', stationId='Rock & Roll'))
        with patch('radio.gas.requests.post', return_value=response) as post:
            gas.gas_update_station('Rock', {'Song:Artist': {'notes': ''}}, 'https://example.test/exec')
            self.assertNotIn('data', post.call_args.kwargs)
            self.assertNotIn('json', post.call_args.kwargs)
            self.assertEqual(post.call_args.kwargs['timeout'], (10, 45))

    def test_transport_errors_are_bounded_and_do_not_expose_query(self):
        for error in (requests.exceptions.SSLError('secret query'),
                      requests.exceptions.Timeout('secret query'),
                      requests.exceptions.ConnectionError('secret query')):
            with patch('radio.gas.requests.post', side_effect=error) as post:
                with self.assertRaises(gas.GasError) as caught:
                    gas.gas_create_station('Rock', 'https://example.test/secret')
                self.assertNotIn('secret', str(caught.exception))
                post.assert_called_once()

    def test_response_validation(self):
        for value in ([], dict(ok=False,error='secret'), dict(ok=True), dict(ok=True,content={})):
            response = Mock(ok=True)
            response.json.return_value = value
            with patch('radio.gas.requests.get', return_value=response):
                with self.assertRaises(gas.GasError):
                    gas.gas_get_stations('https://example.test/exec')
        response = Mock(ok=False, status_code=404)
        with patch('radio.gas.requests.get', return_value=response):
            with self.assertRaisesRegex(gas.GasError, 'HTTP 404'):
                gas.gas_get_stations('https://example.test/exec')

    def test_diff_preserves_explicit_clears(self):
        self.assertEqual(gas.diff({'notes':'old','title':'Same'}, {'notes':'','title':'Same'}), {'notes':''})
