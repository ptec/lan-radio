import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def media_key(song):
    value = [song['title'].strip().casefold(), song['artist'].strip().casefold(), song.get('youtube_id', '')]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


class Store:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache = self.root / 'cache'
        self.cache.mkdir(exist_ok=True)
        self.db = self.root / 'radio.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS media (key TEXT PRIMARY KEY, state TEXT, error TEXT, retry REAL);
                CREATE TABLE IF NOT EXISTS rejected_requests (id TEXT PRIMARY KEY, body TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS sync_failures (id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at REAL, error TEXT);
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def snapshot(self):
        with self.connect() as db:
            row = db.execute('SELECT body FROM snapshot WHERE id=1').fetchone()
        return json.loads(row[0]) if row else {'stations': [], 'songs': []}

    def replace(self, data):
        # Validate the whole response before replacing the last known good catalog.
        for name, fields in [('stations', ['id', 'name', 'status']), ('songs', ['id', 'station_id', 'title', 'artist', 'status'])]:
            if not isinstance(data.get(name), list):
                raise ValueError('Invalid catalog')
            seen = set()
            for row in data[name]:
                if not isinstance(row, dict) or any(not isinstance(row.get(f), str) or not row[f].strip() for f in fields):
                    raise ValueError('Invalid catalog row')
                if row['id'] in seen:
                    raise ValueError('Duplicate catalog ID')
                seen.add(row['id'])
                if name == 'songs' and not isinstance(row.get('youtube_id', ''), str):
                    raise ValueError('Invalid YouTube ID')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO snapshot VALUES (1, ?)', (json.dumps(data),))

    def enqueue(self, body):
        item = dict(body, id=str(uuid.uuid4()), created_at=time.time())
        with self.connect() as db:
            if db.execute('SELECT count(*) FROM outbox').fetchone()[0] >= 1000:
                raise ValueError('Request queue is full; try again after synchronization')
            db.execute('INSERT INTO outbox VALUES (?, ?)', (item['id'], json.dumps(item)))
        return item

    def pending(self, limit=100):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM outbox ORDER BY rowid LIMIT ?', (limit,))]

    def acknowledge(self, ids):
        with self.connect() as db:
            db.executemany('DELETE FROM outbox WHERE id=?', [(i,) for i in ids])

    def update_pending(self, item):
        with self.connect() as db:
            db.execute('UPDATE outbox SET body=? WHERE id=?', (json.dumps(item), item['id']))

    def reject_request(self, request_id, error):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO rejected_requests SELECT id, body, ? FROM outbox WHERE id=?',
                       (error, request_id))

    def approved(self, station=None):
        data = self.snapshot()
        active = {s['id'] for s in data['stations'] if s['status'].lower() == 'approved'}
        return [s for s in data['songs'] if s['status'].lower() == 'approved' and s['station_id'] in active and (station is None or s['station_id'] == station)]

    def path(self, song):
        return self.cache / (media_key(song) + '.mp3')

    def media_state(self, key, state, error='', retry=0):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?)', (key, state, error[-1500:], retry))

    def retry_due(self, key):
        with self.connect() as db:
            row = db.execute('SELECT retry FROM media WHERE key=?', (key,)).fetchone()
        return not row or row[0] <= time.time()

    def media_states(self):
        with self.connect() as db:
            return dict(db.execute('SELECT key, state FROM media'))

    def retry_download(self, key):
        # Only a failed recording can be requeued. Concurrent clicks cannot
        # reset a running job or enqueue the same recording twice.
        with self.connect() as db:
            return db.execute("UPDATE media SET state='queued', error='', retry=0 WHERE key=? AND state='failed'",
                              (key,)).rowcount == 1

    def diagnostics(self):
        with self.connect() as db:
            return {'pending_requests': db.execute('SELECT count(*) FROM outbox').fetchone()[0],
                    'recent_sync_failures': [dict(occurred_at=r[0], error=r[1]) for r in db.execute('SELECT occurred_at, error FROM sync_failures ORDER BY id DESC LIMIT 10')],
                    'rejected_requests': db.execute('SELECT count(*) FROM rejected_requests').fetchone()[0],
                    'downloads': dict(db.execute('SELECT state, count(*) FROM media GROUP BY state'))}

    def record_sync_failure(self, error):
        with self.connect() as db:
            db.execute('INSERT INTO sync_failures (occurred_at, error) VALUES (?, ?)', (time.time(), error))
            db.execute('DELETE FROM sync_failures WHERE id NOT IN (SELECT id FROM sync_failures ORDER BY id DESC LIMIT 10)')
