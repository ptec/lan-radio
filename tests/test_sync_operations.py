import unittest
import tempfile
from radio.store import Store
from radio.catalog import normalize_catalog
from copy import deepcopy
from unittest.mock import Mock, patch
from radio.sync import SheetSync
from radio.sync import SyncError


def run_operation(api, action, **body):
    sync = SheetSync(Mock(snapshot=lambda: {'stations': [], 'songs': []}), Mock(), 'unused')
    with patch('radio.gas.gas_get_stations', side_effect=lambda url: api(action='getStations')['content']), \
         patch('radio.gas.gas_get_station', side_effect=lambda name, url: api(action='getStation', stationId=name)['content']), \
         patch('radio.gas.gas_create_station', side_effect=lambda name, url: api(action='createStation', stationId=name)['content']), \
         patch('radio.gas.gas_update_station', side_effect=lambda name, state, url: api(action='updateStation', stationId=name, state=state)['content']):
        if action == 'catalog':
            return sync.load_catalog()
        if action == 'submit':
            return sync.submit_requests(**body)
        return sync.save_edits(**body)


class StationApiTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(title='Song', artist='Artist', youtubeId='', status='pending', notes='')
        self.original = dict(title='Song', artist='Artist', youtube_id='', status='pending', notes='')
        self.edit = dict(id='local', station='Rock', station_status='approved',
                         original=self.original, changes=dict(self.original, notes='Checked', status='rejected'))

    def test_all_sheet_names_are_literal_station_names(self):
        api = Mock(side_effect=[dict(content=['Rock','pending:Jazz','metadata:Notes']),
                              dict(content=[dict(self.row, status='not-approved')]), dict(content=[]), dict(content=[])])
        result = run_operation(api, action='catalog')
        self.assertEqual([s['name'] for s in result['stations']], ['Rock','pending:Jazz','metadata:Notes'])
        self.assertEqual(result['stations'][0]['songs'][0]['status'], 'rejected')
        self.assertTrue(all(s['status'] == 'approved' for s in result['stations']))

    def test_new_station_uses_the_requested_name(self):
        api = Mock(side_effect=[dict(content=[]), dict(content=['Jazz'])])
        result = run_operation(api, action='submit', requests=[dict(id='one', type='station', name='Jazz')])
        self.assertEqual(result['acknowledged'], ['one'])
        self.assertEqual(api.call_args.kwargs, dict(action='createStation', stationId='Jazz'))

    def test_edits_grouped_and_values_verified(self):
        api = Mock(side_effect=[dict(content=['Rock']),dict(content=[self.row]),
                              dict(content=[dict(self.row, notes='Checked',status='not-approved')])])
        result = run_operation(api, action='edit_batch', edits=[self.edit])
        self.assertTrue(result['results'][0]['saved'])
        self.assertEqual(api.call_args.kwargs['state']['Song:Artist']['status'], 'not-approved')
        self.assertEqual(api.call_args.kwargs['action'], 'updateStation')

    def test_stale_rows_are_not_recreated(self):
        api = Mock(side_effect=[dict(content=['Rock']),dict(content=[])])
        self.assertFalse(run_operation(api, action='edit_batch', edits=[self.edit])['results'][0]['saved'])
        self.assertEqual(api.call_count,2)

    def test_incorrect_returned_notes_are_not_acknowledged(self):
        api = Mock(side_effect=[dict(content=['Rock']),dict(content=[self.row]),dict(content=[self.row])])
        self.assertFalse(run_operation(api, action='edit_batch', edits=[self.edit])['results'][0]['saved'])

    def test_ambiguous_keys_are_not_edited(self):
        api = Mock(side_effect=[dict(content=['Rock']),dict(content=[self.row,self.row])])
        self.assertFalse(run_operation(api, action='edit_batch', edits=[self.edit])['results'][0]['saved'])
        self.assertEqual(api.call_count,2)

    def test_requests_are_pending_and_grouped(self):
        a=dict(id='a',type='song',station='Rock',title='One',artist='Artist')
        b=dict(a,id='b',title='Two')
        api=Mock(side_effect=[dict(content=['Rock']),dict(content=[]),dict(content=[dict(self.row,title='One'),dict(self.row,title='Two')])])
        result=run_operation(api,action='submit',requests=[a,b])
        self.assertEqual(result['acknowledged'],['a','b'])
        self.assertEqual(len(api.call_args.kwargs['state']),2)
        self.assertTrue(all(r['status']=='pending' for r in api.call_args.kwargs['state'].values()))

    def test_partial_station_failure_preserves_successes(self):
        second=deepcopy(self.edit);second.update(id='other',station='Jazz')
        api=Mock(side_effect=[dict(content=['Rock','Jazz']),dict(content=[self.row]),
                             dict(content=[dict(self.row,notes='Checked',status='not-approved')]),
                             dict(content=[self.row]),SyncError('HTTP 404')])
        result=run_operation(api,action='edit_batch',edits=[self.edit,second])
        self.assertEqual([r['saved'] for r in result['results']],[True,False])


class WriteResponseTests(unittest.TestCase):
    def test_station_response_preserves_others_and_replaces_changed_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            song = dict(title='Old', artist='Artist', status='approved', youtube_id='', notes='')
            store.replace(normalize_catalog(dict(schema_version=2, stations=[
                dict(name='Rock', status='approved', songs=[song]),
                dict(name='Jazz', status='approved', songs=[song]),
            ])))
            before = store.snapshot()
            broadcasts = Mock()
            sync = SheetSync(store, broadcasts, 'unused')
            sync.apply_catalog_response(station_name='Rock', songs=[dict(song,title='New',notes='Saved')])
            after = store.snapshot()
            self.assertEqual([s['title'] for s in after['songs']], ['New','Old'])
            self.assertNotEqual(before['songs'][0]['id'], after['songs'][0]['id'])
            self.assertEqual(before['songs'][1], after['songs'][1])
            broadcasts.refresh.assert_called_once()
            sync.apply_catalog_response(station_names=['Rock','Country'])
            after = store.snapshot()
            self.assertEqual([s['name'] for s in after['stations']], ['Rock','Country'])
            self.assertEqual([s['title'] for s in after['songs']], ['New'])
            with self.assertRaises(ValueError):
                sync.apply_catalog_response(station_name='Rock',songs=[{}])
            self.assertEqual(after, store.snapshot())

    def test_save_commits_returned_station_without_another_get(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            sync = SheetSync(store, Mock(), 'unused')
            original = dict(title='Song',artist='Artist',youtube_id='',status='pending',notes='')
            returned = dict(title='Song',artist='Artist',youtubeId='',status='approved',notes='Reviewed')
            with patch('radio.gas.gas_get_stations',return_value=['Rock']), \
                 patch('radio.gas.gas_get_station',return_value=[dict(returned,status='pending',notes='')]) as read, \
                 patch('radio.gas.gas_update_station',return_value=[returned]):
                result = sync.save_edits([dict(id='song',station='Rock',station_status='approved',
                    original=original,changes=dict(original,status='approved',notes='Reviewed'))])
            self.assertTrue(result['results'][0]['saved'])
            read.assert_called_once()
            self.assertEqual(store.snapshot()['songs'][0]['notes'], 'Reviewed')
            self.assertEqual(store.snapshot()['songs'][0]['status'], 'approved')
