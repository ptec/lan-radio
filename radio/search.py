"""Small, shared cache for the public iTunes song search API."""
import threading
import time
from collections import OrderedDict, deque
from difflib import SequenceMatcher

import requests


class SongSearch:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.calls = deque()

    def search(self, title, artist, limit=8):
        term = ' '.join(f'{title} {artist}'.split())
        key = (title.casefold(), artist.casefold())
        # Serialize misses so concurrent listeners reuse the same result and
        # cannot exhaust the provider's modest request allowance in a burst.
        with self.lock:
            now = time.monotonic()
            if key in self.cache and now - self.cache[key][0] < 600:
                self.cache.move_to_end(key)
                return self.cache[key][1][:limit]
            while self.calls and self.calls[0] < now - 60:
                self.calls.popleft()
            if len(self.calls) >= 20:
                raise ValueError('Search is busy. Try again shortly, or enter the song manually.')
            self.calls.append(now)
            response = requests.get('https://itunes.apple.com/search', params={
                'term': term, 'media': 'music', 'entity': 'song', 'limit': 20,
            }, timeout=5)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get('results'), list):
                raise ValueError('Invalid search response')
            songs, seen = [], set()
            for item in body['results']:
                if not isinstance(item, dict):
                    continue
                name, performer = item.get('trackName'), item.get('artistName')
                if not all(isinstance(v, str) and 0 < len(v.strip()) <= 200 for v in (name, performer)):
                    continue
                identity = (name.strip(), performer.strip())
                if identity in seen:
                    continue
                seen.add(identity)
                songs.append(dict(title=name.strip(), artist=performer.strip()))
            def score(song):
                return sum(SequenceMatcher(None, query.casefold(), song[field].casefold()).ratio()
                           for field, query in [('title', title), ('artist', artist)] if query)
            songs.sort(key=score, reverse=True)
            self.cache[key] = (time.monotonic(), songs)
            self.cache.move_to_end(key)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return songs[:limit]
