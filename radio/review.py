"""Persistent advisory iTunes checks; never change approval or downloaded audio."""
import hashlib
import json
import threading
import time


def review_key(song):
    return hashlib.sha256(json.dumps([song['title'], song['artist']], ensure_ascii=False).encode()).hexdigest()


class MetadataReview:
    def __init__(self, store, search, stop):
        self.store, self.search, self.stop = store, search, stop
        self.lock = threading.Lock()
        self.progress = dict(running=False, completed=0, total=0, errors=0)

    def results(self):
        with self.store.connect() as db:
            results = {key:dict(state=state, checked_at=at, explicit_state='unchecked')
                       for key, state, at in db.execute('SELECT key, state, checked_at FROM metadata_reviews')}
            for key, body in db.execute('SELECT key, body FROM review_details'):
                if key in results:
                    results[key].update(json.loads(body))
            return results

    def status(self):
        with self.lock:
            return dict(self.progress)

    def check(self, song):
        details = dict(explicit_state='error', candidates=[])
        try:
            self.search.invalidate(song['title'], song['artist'])
            candidates = self.search.search(song['title'], song['artist'], limit=20)
            matches = [s for s in candidates if s['title'] == song['title'] and s['artist'] == song['artist']]
            state = 'matched' if matches else 'review'
            ratings = {s.get('explicitness', 'unknown') for s in matches}
            rating = next(iter(ratings)) if len(ratings) == 1 else 'ambiguous' if ratings else 'unknown'
            if rating not in ('explicit', 'cleaned', 'notExplicit', 'ambiguous'):
                rating = 'unknown'
            details = dict(explicit_state=rating, candidates=candidates)
        except Exception:
            state = 'error'
        with self.store.connect() as db:
            key = review_key(song)
            db.execute('INSERT OR REPLACE INTO metadata_reviews VALUES (?, ?, ?)', (key, state, time.time()))
            db.execute('INSERT OR REPLACE INTO review_details VALUES (?, ?)', (key, json.dumps(details)))
        return state

    def start(self, force=False, scope=None, song_id=None, tool='metadata'):
        scope = scope or ('all' if force else 'unchecked')
        if scope not in ('all', 'unchecked', 'pending', 'song') or tool not in ('metadata', 'explicit'):
            raise ValueError('Invalid scan scope or tool')
        with self.lock:
            if self.progress['running']:
                return False
            known = self.results()
            songs = self.store.snapshot()['songs']
            if scope == 'song':
                songs = [s for s in songs if s['id'] == song_id]
                if not songs:
                    raise ValueError('Song was removed or changed. Reload the catalog.')
            if scope == 'pending':
                songs = [s for s in songs if s['status'] == 'pending']
            unique = {review_key(song):song for song in songs}
            field = 'state' if tool == 'metadata' else 'explicit_state'
            queue = [song for key, song in unique.items() if scope in ('all', 'song') or
                     known.get(key, {}).get(field, 'unchecked') in ('unchecked', 'error')]
            self.progress = dict(running=True, completed=0, total=len(queue), errors=0)
            threading.Thread(target=self.run, args=(queue,), daemon=True, name='itunes-review').start()
            return True

    def run(self, queue):
        try:
            for index, song in enumerate(queue):
                if self.stop.is_set() or (index and self.stop.wait(5)):
                    break
                state = self.check(song)
                with self.lock:
                    self.progress['completed'] += 1
                    self.progress['errors'] += state == 'error'
        finally:
            with self.lock:
                self.progress['running'] = False
