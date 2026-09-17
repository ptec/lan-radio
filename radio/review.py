"""Advisory iTunes comparisons; never alter catalog or approval."""
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
            return {key:dict(state=state, checked_at=at) for key, state, at in db.execute('SELECT key, state, checked_at FROM metadata_reviews')}

    def status(self):
        with self.lock:
            return dict(self.progress)

    def check(self, song):
        try:
            candidates = self.search.search(song['title'], song['artist'], limit=20)
            state = 'matched' if any(s['title'] == song['title'] and s['artist'] == song['artist'] for s in candidates) else 'review'
        except Exception:
            state = 'error'
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO metadata_reviews VALUES (?, ?, ?)', (review_key(song), state, time.time()))
        return state

    def start(self, force=False):
        with self.lock:
            if self.progress['running']:
                return False
            known = self.results()
            unique = {review_key(song):song for song in self.store.snapshot()['songs']}
            queue = [song for key,song in unique.items() if force or known.get(key, {}).get('state') not in ('matched', 'review')]
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
