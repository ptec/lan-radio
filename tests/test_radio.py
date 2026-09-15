import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from radio.store import Store, media_key
from radio.audio import Station, Broadcasts, frames, FRAME_SECONDS
from radio.sync import SheetSync
from radio.web import create_app
from radio.catalog import normalize_catalog


class RadioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.song = dict(id='song1', station_id='station1', title='Test', artist='Synth', status='approved', youtube_id='')
        self.catalog = dict(stations=[dict(id='station1',name='Test Station',status='approved')], songs=[self.song])
        self.store.replace(self.catalog)
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)

    def tone(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('ffmpeg required')
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=2',
                        '-ac','2','-ar','44100','-c:a','libmp3lame','-b:a','128k','-reservoir','0',
                        '-write_xing','0','-id3v2_version','0',str(self.store.path(self.song))], check=True)

    def test_approval_and_snapshot_atomicity(self):
        self.assertEqual(len(self.store.approved()), 1)
        with self.assertRaises(ValueError):
            self.store.replace({'stations': [], 'songs': [{}]})
        self.assertEqual(len(self.store.approved()), 1)
        self.catalog['songs'][0]['status'] = 'pending'
        self.store.replace(self.catalog)
        self.assertEqual(self.store.approved(), [])
        self.catalog['songs'][0]['status'] = 'approved'
        self.catalog['stations'][0]['status'] = 'rejected'
        self.store.replace(self.catalog)
        self.assertEqual(self.store.approved(), [])

    def test_outbox_survives_restart_and_failed_sync(self):
        item = self.store.enqueue(dict(type='station', name='Jazz'))
        reopened = Store(self.temp.name)
        sync = SheetSync(reopened, None, 'https://example.test', 'secret')
        with patch.object(sync,'call',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                sync.push()
        self.assertEqual(reopened.pending()[0]['id'],item['id'])
        with patch.object(sync,'call',return_value={'acknowledged':[item['id'],'unknown']}):
            sync.push()
        self.assertEqual(reopened.pending(), [])

    def test_cache_shared_across_stations(self):
        other = dict(self.song, id='other', station_id='other')
        self.assertEqual(media_key(self.song), media_key(other))
        self.assertNotEqual(media_key(self.song), media_key(dict(other,youtube_id='abcdefghijk')))

    def test_frames_and_late_join_receive_same_live_chunks(self):
        self.tone()
        count = sum(1 for _ in frames(self.store.path(self.song)))
        self.assertAlmostEqual(count * FRAME_SECONDS, 2, delta=.08)
        station = Station(self.store,'station1',self.stop)
        # Clock starts with no clients; both clients join an already-running track.
        station.thread.start()
        try:
            time.sleep(.35)
            self.assertIsNotNone(station.current)
            with station.lock:
                a,b = queue.Queue(8),queue.Queue(8)
                station.listeners.update([a,b])
            started = time.monotonic()
            for _ in range(3):
                self.assertEqual(a.get(timeout=2), b.get(timeout=2))
            self.assertGreater(time.monotonic()-started,.4)
            self.catalog['songs'][0]['status']='rejected'
            self.store.replace(self.catalog)
            time.sleep(.4)
            self.assertIsNone(station.current)
        finally:
            self.stop.set()
            station.thread.join(3)

    def test_slow_client_is_disconnected(self):
        station = Station(self.store,'station1',self.stop)
        listener = station.subscribe()
        for _ in range(9):
            station.publish(b'audio')
        self.assertIsNone(listener.get_nowait())
        self.assertNotIn(listener, station.listeners)

    def test_up_next_matches_shuffled_playable_rotation(self):
        second = dict(self.song, id='song2', title='Second')
        pending = dict(self.song, id='song3', title='Pending', status='pending')
        missing = dict(self.song, id='song4', title='Not downloaded')
        self.catalog['songs'] = [self.song, pending, missing, second]
        self.store.replace(self.catalog)
        self.store.path(self.song).write_bytes(b'cached')
        self.store.path(second).write_bytes(b'cached')
        station = Station(self.store, 'station1', self.stop)
        first = station.rotation.take([self.song, second])
        other = second if first['id'] == self.song['id'] else self.song
        self.assertEqual(station.playback()['up_next']['title'], other['title'])
        self.assertEqual(station.playback()['up_next']['title'], other['title'])
        self.assertEqual(station.rotation.take([self.song, second])['title'], other['title'])
        self.assertEqual(station.playback()['up_next']['title'], first['title'])
        self.catalog['songs'] = []
        self.store.replace(self.catalog)
        self.assertIsNone(station.playback()['up_next'])

    def test_api_requests_cannot_self_approve(self):
        broadcasts = Broadcasts(self.store,self.stop)
        app = create_app(self.store,broadcasts,SimpleNamespace(last_success=None,error=None),self.stop)
        client = app.test_client()
        result = client.post('/api/requests',json=dict(type='song',station_id='station1',title='A',artist='B',status='approved'))
        self.assertEqual(result.status_code,202)
        self.assertNotIn('status',self.store.pending()[0])
        self.assertEqual(self.store.pending()[0]['station'], 'Test Station')
        self.assertNotIn('station_id', self.store.pending()[0])
        self.assertEqual(client.post('/api/requests',json=dict(type='station',name='X'),headers={'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(client.post('/api/requests',json=[]).status_code,400)
        self.assertEqual(client.get('/stream/missing').status_code,404)
        self.assertEqual(client.get('/').status_code,200)

    def test_nested_sheet_catalog_edits_deletions_sort_and_duplicates(self):
        songs = [dict(title='First',artist='Artist',status='approved'), dict(title='Second',artist='Artist',status='approved')]
        data = dict(schema_version=2,stations=[dict(name='Rock',status='approved',songs=songs)])
        self.store.replace(normalize_catalog(data))
        first = self.store.approved()[0]
        songs.reverse()
        self.store.replace(normalize_catalog(data))
        self.assertEqual([s['title'] for s in self.store.approved()], ['Second','First'])
        self.assertEqual(first['id'], self.store.approved()[1]['id'])
        songs[1]['title']='Edited'
        self.store.replace(normalize_catalog(data))
        self.assertNotIn(first['id'], [s['id'] for s in self.store.approved()])
        songs.pop()
        songs.append(dict(songs[0]))
        self.store.replace(normalize_catalog(data))
        self.assertEqual(len({s['id'] for s in self.store.approved()}),2)
        songs.clear()
        self.store.replace(normalize_catalog(data))
        self.assertEqual(self.store.approved(),[])
        data['stations'].clear()
        self.store.replace(normalize_catalog(data))
        self.assertEqual(self.store.snapshot()['stations'],[])

    def test_tab_rename_retires_broadcast_and_reuses_audio_cache(self):
        data = dict(schema_version=2,stations=[dict(name='Rock',status='approved',songs=[
            dict(title='Test',artist='Synth',status='approved',youtube_id='')])])
        self.store.replace(normalize_catalog(data))
        old_song = self.store.approved()[0]
        broadcasts = Broadcasts(self.store,self.stop)
        broadcasts.refresh()
        old = broadcasts.get(old_song['station_id'])
        listener = old.subscribe()
        data['stations'][0]['name']='Classic Rock'
        self.store.replace(normalize_catalog(data))
        broadcasts.refresh()
        new_song = self.store.approved()[0]
        new = broadcasts.get(new_song['station_id'])
        try:
            self.assertIsNone(broadcasts.get(old_song['station_id']))
            self.assertTrue(old.retired.is_set())
            self.assertIsNone(listener.get(timeout=2))
            self.assertEqual(self.store.path(old_song),self.store.path(new_song))
            data['stations'].clear()
            self.store.replace(normalize_catalog(data))
            broadcasts.refresh()
            self.assertEqual(broadcasts.stations,{})
            self.assertTrue(new.retired.is_set())
        finally:
            self.stop.set()
            old.thread.join(2)
            new.thread.join(2)

    def test_sync_translates_catalog_and_reports_moderation_warnings(self):
        broadcasts = SimpleNamespace(refresh=lambda:None)
        sync = SheetSync(self.store,broadcasts,'url','secret')
        data = dict(schema_version=2,stations=[dict(name='Rock',status='approved',songs=[])],warnings=['Rock: incomplete row'])
        with patch.object(sync,'call',return_value=data):
            sync.pull()
        self.assertEqual(self.store.snapshot()['stations'][0]['name'],'Rock')
        self.assertEqual(sync.warnings,data['warnings'])
        self.assertIsNotNone(sync.last_success)

    def test_stale_request_terminal_rejection_is_preserved_locally(self):
        item = self.store.enqueue(dict(type='song',station='Removed',title='A',artist='B'))
        sync = SheetSync(self.store,None,'url','secret')
        with patch.object(sync,'call',return_value=dict(acknowledged=[item['id']],rejected=[dict(id=item['id'],error='Station deleted')])):
            sync.push()
        self.assertEqual(self.store.pending(),[])
        self.assertEqual(self.store.diagnostics()['rejected_requests'],1)

    def test_old_outbox_station_reference_translated_before_upload(self):
        item=self.store.enqueue(dict(type='song',station_id='station1',title='A',artist='B'))
        sync=SheetSync(self.store,None,'url','secret')
        with patch.object(sync,'call',return_value=dict(acknowledged=[item['id']])) as call:
            sync.push()
        submitted=call.call_args.kwargs['requests'][0]
        self.assertEqual(submitted['station'],'Test Station')
        self.assertNotIn('station_id',submitted)

    def test_failed_legacy_upload_keeps_name_after_new_catalog_replaces_ids(self):
        item=self.store.enqueue(dict(type='song',station_id='station1',title='A',artist='B'))
        sync=SheetSync(self.store,None,'url','secret')
        with patch.object(sync,'call',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                sync.push()
        self.store.replace(normalize_catalog(dict(schema_version=2,stations=[])))
        with patch.object(sync,'call',return_value=dict(acknowledged=[item['id']])) as call:
            sync.push()
        self.assertEqual(call.call_args.kwargs['requests'][0]['station'],'Test Station')

    def test_listener_slot_is_released(self):
        station = Station(self.store,'station1',self.stop)
        station.current = {'title':'test'}
        broadcasts = SimpleNamespace(get=lambda _:station)
        app = create_app(self.store,broadcasts,SimpleNamespace(last_success=None,error=None),self.stop,1)
        with app.test_request_context('/stream/station1'):
            response = app.view_functions['stream']('station1')
            self.assertEqual(app.view_functions['stream']('station1')[1],503)
            response.close()
            again = app.view_functions['stream']('station1')
            self.assertEqual(again.status_code,200)
            again.close()
        self.assertEqual(len(station.listeners),0)


if __name__ == '__main__':
    unittest.main()
