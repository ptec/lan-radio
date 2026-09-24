"""Frame-aligned, paced MPEG-1 Layer III broadcasting, independent of listeners."""
import logging
import math
import queue
import random
import threading
import time
from .store import media_key

LOG = logging.getLogger(__name__)
FRAME_SECONDS = 1152 / 44100
LISTENER_QUEUE_CHUNKS = math.ceil(8 / (10 * FRAME_SECONDS))


class ShuffleRotation:
    """A station-owned shuffle bag. Call under the station lock."""
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.remaining = []
        self.played = set()
        self.last = None

    def prepare(self, songs):
        available = {}
        for song in songs:
            available.setdefault(media_key(song), song)
        self.remaining = [key for key in self.remaining if key in available]
        additions = [key for key in available if key not in self.played and key not in self.remaining]
        self.rng.shuffle(additions)
        self.remaining.extend(additions)
        if not self.remaining and available:
            self.played.clear()
            self.remaining = list(available)
            self.rng.shuffle(self.remaining)
        # Also repair the boundary if catalog changes removed the planned next
        # song. Repeated previews never reshuffle an already planned queue.
        if len(self.remaining) > 1 and self.remaining[0] == self.last:
            other = self.rng.randrange(1, len(self.remaining))
            self.remaining[0], self.remaining[other] = self.remaining[other], self.remaining[0]
        return available

    def peek(self, songs):
        available = self.prepare(songs)
        return available[self.remaining[0]] if self.remaining else None

    def take(self, songs):
        song = self.peek(songs)
        if song is not None:
            self.last = self.remaining.pop(0)
            self.played.add(self.last)
        return song


def frames(path):
    # Cache is always normalized to 128 kbps, 44.1 kHz MP3 with no ID3/Xing.
    with open(path, 'rb') as source:
        while header := source.read(4):
            if len(header) != 4 or header[0] != 255 or header[1] != 251 or header[2] & 0xFC != 0x90:
                raise ValueError('Invalid normalized MP3 frame')
            size = 144 * 128000 // 44100 + ((header[2] >> 1) & 1)
            rest = source.read(size - 4)
            if len(rest) != size - 4:
                raise ValueError('Truncated MP3 frame')
            yield header + rest


class Station:
    def __init__(self, store, station_id, stop):
        self.store, self.id, self.stop = store, station_id, stop
        self.lock = threading.Lock()
        self.listeners = set()
        self.current = None
        self.slow_disconnects = 0
        self.late_chunks = 0
        self.max_lateness = 0.0
        self.last_late_at = None
        self.cache_errors = 0
        self.rotation = ShuffleRotation()
        self.retired = threading.Event()
        self.thread = threading.Thread(target=self.run, name='station-' + station_id, daemon=True)

    def subscribe(self):
        listener = queue.Queue(maxsize=LISTENER_QUEUE_CHUNKS)  # about eight seconds
        with self.lock:
            self.listeners.add(listener)
        return listener

    def unsubscribe(self, listener):
        with self.lock:
            self.listeners.discard(listener)

    def publish(self, chunk):
        with self.lock:
            for listener in list(self.listeners):
                try:
                    listener.put_nowait(chunk)
                except queue.Full:
                    self.slow_disconnects += 1
                    self.listeners.remove(listener)
                    while not listener.empty():
                        try:
                            listener.get_nowait()
                        except queue.Empty:
                            break
                    listener.put_nowait(None)

    def diagnostics(self):
        with self.lock:
            return dict(station_id=self.id, thread_alive=self.thread.is_alive(), listeners=len(self.listeners),
                        queue_capacity_chunks=LISTENER_QUEUE_CHUNKS,
                        max_queue_chunks=max((q.qsize() for q in self.listeners), default=0),
                        slow_disconnects=self.slow_disconnects, late_chunks=self.late_chunks,
                        max_lateness_ms=round(self.max_lateness * 1000), last_late_at=self.last_late_at,
                        cache_errors=self.cache_errors)

    def playback(self):
        with self.lock:
            current = self.current
            songs = [s for s in self.store.playback_songs(self.id) if self.store.path(s).is_file()]
            following = self.rotation.peek(songs)
        return dict(now_playing=current, up_next=dict(title=following['title'], artist=following['artist']) if following else None)

    def run(self):
        while not self.stop.is_set() and not self.retired.is_set():
            with self.lock:
                songs = [s for s in self.store.playback_songs(self.id) if self.store.path(s).is_file()]
                song = self.rotation.take(songs)
                self.current = dict(title=song['title'], artist=song['artist'], started_at=time.time()) if song else None
            if song is None:
                self.stop.wait(1)
                continue
            deadline = time.monotonic()
            try:
                batch = []
                for frame in frames(self.store.path(song)):
                    if self.stop.is_set() or self.retired.is_set():
                        batch = []
                        break
                    batch.append(frame)
                    if len(batch) == 10:
                        # Re-check approval while playing so revocation stops promptly.
                        if not self.store.playback_approved(self.id, song['id']):
                            batch = []
                            break
                        lateness = max(0, time.monotonic() - deadline)
                        with self.lock:
                            self.max_lateness = max(self.max_lateness, lateness)
                            if lateness > .1:
                                self.late_chunks += 1
                                self.last_late_at = time.time()
                        self.publish(b''.join(batch))
                        deadline += len(batch) * FRAME_SECONDS
                        batch = []
                        self.stop.wait(max(0, deadline - time.monotonic()))
                        deadline = max(deadline, time.monotonic() - .25)
                if batch and not self.stop.is_set() and not self.retired.is_set():
                    self.publish(b''.join(batch))
                    deadline += len(batch) * FRAME_SECONDS
                    self.stop.wait(max(0, deadline - time.monotonic()))
            except (OSError, ValueError):
                with self.lock:
                    self.cache_errors += 1
                LOG.exception('Bad cache entry for %s', song['id'])
                self.store.path(song).unlink(missing_ok=True)
                self.stop.wait(1)
        self.current = None
        self.publish(None)


class Broadcasts:
    def __init__(self, store, stop):
        self.store, self.stop = store, stop
        self.lock = threading.Lock()
        self.stations = {}

    def refresh(self):
        with self.lock:
            catalog = self.store.snapshot()['stations']
            active = {s['id'] for s in catalog if s['status'].lower() == 'approved'}
            for key in list(self.stations):
                if key not in active:
                    self.stations.pop(key).retired.set()
            for s in catalog:
                if s['status'].lower() == 'approved' and s['id'] not in self.stations:
                    station = Station(self.store, s['id'], self.stop)
                    self.stations[s['id']] = station
                    station.thread.start()

    def diagnostics(self):
        with self.lock:
            stations = list(self.stations.values())
        return [station.diagnostics() for station in stations]

    def get(self, station_id):
        with self.lock:
            return self.stations.get(station_id)
