"""Catalog synchronization and moderation operations.

gas.py handles HTTP. This module decides what to read or write, confirms saves,
and schedules synchronization of the local catalog and request queue.
"""

from collections import defaultdict
import logging
import time
import threading
import re
from urllib.parse import quote
from . import gas
from .catalog import normalize_catalog

LOG = logging.getLogger(__name__)


SyncError = gas.GasError


FIELDS = ('title', 'artist', 'youtube_id', 'status', 'notes')


def song_from_sheet(row):
    """Translate spreadsheet fields into the app's existing song format."""
    result = {}
    for field in FIELDS:
        sheet_field = 'youtubeId' if field == 'youtube_id' else field
        result[field] = str(row.get(sheet_field, '')).strip()

    # Retain the internal status name so cached data remains compatible.
    if result['status'] == 'not-approved':
        result['status'] = 'rejected'
    elif not result['status']:
        result['status'] = 'pending'

    return result


def song_for_sheet(row):
    """Translate an app song to the fields accepted by updateStation."""
    result = {}
    for field in FIELDS:
        sheet_field = 'youtubeId' if field == 'youtube_id' else field
        result[sheet_field] = row.get(field, '')

    if result['status'] == 'rejected':
        result['status'] = 'not-approved'

    return result


def song_key(row):
    """Use the title:artist lookup key required by the GAS API."""
    return row['title'] + ':' + row['artist']


class SheetSync:
    def __init__(self, store, broadcasts, url, token="", request_delay=300, manual_cooldown=30):
        self.store, self.broadcasts = store, broadcasts
        self.url, self.token = url, token
        self.request_delay, self.manual_cooldown = request_delay, manual_cooldown
        self.lock = threading.Lock()
        self.running = False
        self.manual_requested = False
        self.last_started = None
        self.last_completed = None
        self.retry_after = 0
        self.legacy_queued_at = None
        self.last_success = None
        self.error = None
        self.warnings = []

    def due_at(self, now):
        pending = self.store.pending(limit=1000)
        if not pending:
            self.legacy_queued_at = None
            return None
        if self.legacy_queued_at is None:
            self.legacy_queued_at = now
        oldest = min(r.get('created_at', self.legacy_queued_at) for r in pending)
        return max(oldest + self.request_delay, self.retry_after)

    def status(self):
        with self.lock:
            return dict(configured=bool(self.url), running=self.running,
                        requested=self.manual_requested, next_sync_at=self.due_at(time.time()),
                        last_completed=self.last_completed,
                        manual_available_at=(self.last_started + self.manual_cooldown) if self.last_started is not None else 0)

    def request_manual(self):
        with self.lock:
            if not self.url:
                return 'unconfigured'
            if self.running or self.manual_requested:
                return 'queued'
            if self.last_started is not None and time.time() < self.last_started + self.manual_cooldown:
                return 'cooldown'
            self.manual_requested = True
            return 'queued'

    def station_names(self):
        """Read sheet names exactly as entered by the spreadsheet owner."""
        names = gas.gas_get_stations(self.url)
        if any(not isinstance(name, str) for name in names):
            raise SyncError('Invalid station list')
        return names

    def read_station(self, name):
        """Ignore incomplete rows, but never hide a failed station request."""
        rows = gas.gas_get_station(name, self.url)
        if any(not isinstance(row, dict) for row in rows):
            raise SyncError('Invalid station entries')
        return [song_from_sheet(row) for row in rows if row.get('title') and row.get('artist')]

    def load_catalog(self):
        """Build the complete catalog before replacing any local data."""
        stations = []
        for name in self.station_names():
            stations.append(dict(name=name, status='approved', songs=self.read_station(name)))

        return dict(ok=True, schema_version=2, warnings=[], stations=stations)

    def apply_catalog_response(self, station_names=None, station_name=None, songs=None):
        """Merge write responses while preserving unrelated local playlists.

        Updates return a complete station; creation returns names only.
        Validate the merged snapshot before publishing it to playback.
        """
        current = self.store.snapshot()
        playlists = {}
        for station in current['stations']:
            playlists[station['name']] = [
                song for song in current['songs'] if song['station_id'] == station['id']
            ]

        if station_names is not None:
            if any(not isinstance(name, str) or not name.strip() for name in station_names):
                raise SyncError('Invalid station list in write response')
            playlists = {name: playlists.get(name, []) for name in station_names}

        if station_name is not None:
            playlists[station_name] = songs

        catalog = dict(schema_version=2, stations=[
            dict(name=name, status='approved', songs=playlist)
            for name, playlist in playlists.items()
        ])
        self.store.replace(normalize_catalog(catalog))
        self.broadcasts.refresh()

    def save_edit(self, **edit):
        """Use the same save rules for the single-row administration endpoint."""
        result = self.save_edits([dict(edit, id='single')])['results'][0]
        return dict(ok=True, conflict=not result['saved'],
                    error=result.get('error'), moderation_version=1)

    def save_edits(self, edits):
        """Group edits by station; report success only for confirmed values."""
        stations = set(self.station_names())
        groups = defaultdict(list)
        results = []

        # Reading and writing once per station avoids a request for every song.
        for edit in edits:
            groups[edit['station']].append(edit)

        for name, group in groups.items():
            station_exists = name in stations
            try:
                rows = self.read_station(name) if station_exists else []
            except SyncError as exc:
                results.extend(dict(id=e['id'], saved=False, error=str(exc)) for e in group)
                continue
            # Only validated edits go into the outgoing state. Keep their
            # expected values so the response can confirm each save separately.
            state = {}
            pending = []

            for edit in group:
                original = {f: edit['original'].get(f, '') for f in FIELDS}
                desired = dict(original, **edit['changes'])
                original_key = song_key(original)
                desired_key = song_key(desired)
                matches = [row for row in rows if song_key(row) == original_key]

                # Never use the API's upsert behavior to recreate a deleted row.
                # This check is not atomic with a simultaneous human sheet edit.
                row_changed = len(matches) != 1 or matches[0] != original
                duplicate_edit = original_key in state
                rename_collision = desired_key != original_key and any(
                    song_key(row) == desired_key for row in rows
                )
                station_changed = not station_exists or edit['station_status'] != 'approved'

                if station_changed or row_changed or duplicate_edit or rename_collision:
                    results.append(dict(
                        id=edit['id'],
                        saved=False,
                        error='Song changed, is duplicated, or the new title/artist already exists. Sync and review.',
                    ))
                    continue

                state[original_key] = song_for_sheet(desired)
                pending.append((edit, desired))

            if state:
                try:
                    updated = [song_from_sheet(r) for r in gas.gas_update_station(name, state, self.url)]
                    self.apply_catalog_response(station_name=name, songs=updated)
                    for edit, desired in pending:
                        # An HTTP success alone does not confirm an edit was applied.
                        saved = sum(r == desired for r in updated) == 1
                        results.append(dict(id=edit['id'], saved=saved, moderation_version=1,
                                            error=None if saved else 'Sheets did not return the requested values. Sync and review.'))
                except SyncError as exc:
                    results.extend(dict(id=e['id'], saved=False, error=str(exc) + ' Delivery may have succeeded; sync and review.') for e, _ in pending)
        return dict(ok=True, results=results)

    def submit_requests(self, requests):
        """Upload queued requests without changing existing song approvals."""
        stations = set(self.station_names())
        acknowledged = []
        rejected = []
        errors = []
        groups = defaultdict(list)

        # Create new stations first, then group song requests by their station.
        for request in requests:
            if request['type'] == 'station':
                try:
                    name = request['name']
                    if name not in stations:
                        returned_names = gas.gas_create_station(name, self.url)
                        if name not in returned_names:
                            raise SyncError('Sheets did not confirm the new station')
                        self.apply_catalog_response(station_names=returned_names)
                        stations = set(returned_names)
                    acknowledged.append(request['id'])
                except SyncError as exc:
                    errors.append(dict(id=request['id'], error=str(exc)))
            else:
                groups[request['station']].append(request)
        for name, group in groups.items():
            station_exists = name in stations
            if not station_exists:
                for r in group:
                    acknowledged.append(r['id'])
                    rejected.append(dict(id=r['id'], error='Station was removed, renamed, or is not approved'))
                continue
            try:
                rows = self.read_station(name)
                existing = {(r['title'].lower(), r['artist'].lower()) for r in rows}
                state = {}

                # Existing songs count as delivered. Do not reset their status
                # to pending just because somebody requests the same song again.
                for r in group:
                    if (r['title'].lower(), r['artist'].lower()) not in existing:
                        # Colon-separated keys can collide even for different pairs.
                        if any(song_key(v) == song_key(r) for v in rows) or song_key(r) in state:
                            raise SyncError('Ambiguous title/artist key; review this request in Sheets.')
                        state[song_key(r)] = song_for_sheet(dict(r, status='pending'))
                        existing.add((r['title'].lower(), r['artist'].lower()))
                if state:
                    updated = [song_from_sheet(r) for r in gas.gas_update_station(name, state, self.url)]
                    self.apply_catalog_response(station_name=name, songs=updated)
                    returned_songs = [song_for_sheet(row) for row in updated]

                    for requested_song in state.values():
                        if requested_song not in returned_songs:
                            raise SyncError('Sheets did not confirm the requested songs')

                acknowledged.extend(r['id'] for r in group)
            except SyncError as exc:
                errors.extend(dict(id=r['id'], error=str(exc)) for r in group)
        return dict(ok=True, acknowledged=acknowledged, rejected=rejected, errors=errors)

    def safe_error(self, error):
        text = str(error) or type(error).__name__
        for secret in (self.token, self.url):
            if secret:
                for value in (secret, quote(secret, safe='')):
                    text = text.replace(value, '[redacted]')
        text = re.sub(r'https?://\S+', '[URL redacted]', text)
        return ' '.join(text.split())[:700]

    def push(self):
        pending = self.store.pending()
        if pending:
            # Migrate previously queued requests locally; no sheet IDs are sent.
            station_names = {s['id']: s['name'] for s in self.store.snapshot()['stations']}
            outgoing = []
            for item in pending:
                item = dict(item)
                if item['type'] == 'song' and 'station' not in item:
                    item['station'] = station_names.get(item.get('station_id'), '(removed station)')
                item.pop('station_id', None)
                # Persist names before the network call: a failed upload followed
                # by a successful v2 pull must not lose the legacy ID mapping.
                self.store.update_pending(item)
                outgoing.append(item)
            data = self.submit_requests(requests=outgoing)
            acknowledged = set(data.get('acknowledged', [])) & {r['id'] for r in pending}
            for rejected in data.get('rejected', []):
                if rejected.get('id') in acknowledged:
                    self.store.reject_request(rejected['id'], rejected.get('error', 'Rejected by Sheets'))
            self.store.acknowledge(acknowledged)
            if len(acknowledged) != len(pending):
                details = '; '.join(self.safe_error(e.get('error', 'Unknown error')) for e in data.get('errors', []) if isinstance(e, dict))
                raise SyncError('Some queued requests were rejected by Sheets' + (': ' + details if details else ''))

    def pull(self):
        data = self.load_catalog()
        self.store.replace(normalize_catalog(data))
        self.warnings = data.get('warnings', [])
        self.broadcasts.refresh()
        self.last_success = time.time()

    def tick(self):
        """Run at most one due sync. Only the background thread calls this."""
        with self.lock:
            if not self.url:
                self.error = 'Google Sheets is not configured'
                return
            now = time.time()
            due = self.due_at(now)
            if self.running or (not self.manual_requested and (due is None or due > now)):
                return
            self.running = True
            refresh_catalog = self.manual_requested
            self.manual_requested = False
            self.last_started = now
        errors = []
        try:
            # Drain the initial backlog in bounded batches. Requests arriving
            # during this cycle may remain for the next lazy sync.
            batches = (len(self.store.pending(limit=1000)) + 99) // 100
            try:
                for _ in range(batches):
                    self.push()
            except Exception as exc:
                detail = 'Request upload failed: ' + self.safe_error(exc)
                errors.append(detail)
                LOG.warning('%s', detail)
            # Lazy uploads use write responses; manual sync reads all stations.
            if refresh_catalog:
                try:
                    self.pull()
                except Exception as exc:
                    detail = 'Catalog sync failed: ' + self.safe_error(exc)
                    errors.append(detail)
                    LOG.warning('%s', detail)
            self.error = '; '.join(errors) or None
            if self.error:
                try:
                    self.store.record_sync_failure(self.error)
                except Exception as exc:
                    LOG.warning('Could not save sync failure history: %s', self.safe_error(exc))
        finally:
            with self.lock:
                self.last_completed = time.time()
                self.retry_after = self.last_completed + self.request_delay
                self.running = False

    def run(self, stop):
        self.broadcasts.refresh()  # No network fetch on startup.
        while not stop.is_set():
            self.tick()
            stop.wait(1)
