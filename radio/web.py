import queue
import re
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit
from flask import Flask, Response, jsonify, render_template, request


# Cached MP3s are normalized to 128 kbps. Accumulate complete frames for
# approximately two seconds before sending the first bytes to a new listener.
STARTUP_BUFFER_BYTES = 128000 // 8 * 2


def buffered_audio(listener, stop):
    startup = bytearray()
    primed = False
    while not stop.is_set():
        try:
            chunk = listener.get(timeout=10)
        except queue.Empty:
            return
        if chunk is None or stop.is_set():
            return
        if not primed:
            startup.extend(chunk)
            if len(startup) < STARTUP_BUFFER_BYTES:
                continue
            first = bytes(startup)
            startup.clear()
            primed = True
            yield first
        else:
            yield chunk


def create_app(store, broadcasts, sync, stop, max_listeners=24):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 8192
    slots = threading.BoundedSemaphore(max_listeners)
    rate_lock = threading.Lock()
    requests_by_ip = defaultdict(deque)

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/stations')
    def stations():
        result = []
        for station in store.snapshot()['stations']:
            if station['status'].lower() not in ('approved', 'pending'):
                continue
            live = broadcasts.get(station['id'])
            songs = store.approved(station['id'])
            playback = live.playback() if live else dict(now_playing=None, up_next=None)
            result.append(dict(id=station['id'], name=station['name'], status=station['status'],
                               **playback,
                               ready=sum(store.path(s).is_file() for s in songs), approved=len(songs)))
        return jsonify(stations=result)

    @app.get('/api/stations/<station_id>/songs')
    def station_songs(station_id):
        catalog = store.snapshot()
        station = next((s for s in catalog['stations'] if s['id'] == station_id and s['status'].lower() in ('approved', 'pending')), None)
        if not station:
            return jsonify(error='Station not found'), 404
        songs = [dict(title=s['title'], artist=s['artist'], status=s['status'].lower(),
                      queued=False, cached=store.path(s).is_file())
                 for s in catalog['songs'] if s['station_id'] == station_id]
        known = {(s['title'].casefold().strip(), s['artist'].casefold().strip()) for s in songs}
        for item in store.pending(limit=1000):
            if item.get('type') != 'song' or not (item.get('station') == station['name'] or item.get('station_id') == station_id):
                continue
            key = (item['title'].casefold().strip(), item['artist'].casefold().strip())
            if key not in known:
                songs.append(dict(title=item['title'], artist=item['artist'], status='pending', queued=True, cached=False))
                known.add(key)
        return jsonify(station=station, songs=songs)

    @app.post('/api/sync')
    def manual_sync():
        if not request.is_json:
            return jsonify(error='JSON required'), 415
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error='Cross-origin requests are not allowed'), 403
        result = sync.request_manual()
        if result == 'unconfigured':
            return jsonify(error='Google Sheets is not configured'), 503
        if result == 'cooldown':
            return jsonify(error='A sync just started. Please wait before syncing again.'), 429
        return jsonify(message='Sync scheduled. Queued requests will upload before the catalog refreshes.'), 202

    @app.get('/api/health')
    def health():
        return jsonify(last_sheet_sync=sync.last_success, sync_error=sync.error,
                       sync=sync.status() if hasattr(sync, 'status') else {},
                       catalog_warnings=getattr(sync, 'warnings', []), **store.diagnostics())

    @app.post('/api/requests')
    def new_request():
        if not request.is_json:
            return jsonify(error='JSON required'), 415
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error='Cross-origin requests are not allowed'), 403
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('type') not in ('song', 'station'):
            return jsonify(error='type must be song or station'), 400
        fields = ['name'] if body['type'] == 'station' else ['station_id', 'title', 'artist']
        if any(not isinstance(body.get(f), str) or not 1 <= len(body[f].strip()) <= 200 for f in fields):
            return jsonify(error='Fill all fields (maximum 200 characters each)'), 400
        clean = {f: body[f].strip() for f in fields}
        clean['type'] = body['type']
        if clean['type'] == 'station':
            if len(clean['name']) > 91 or re.search(r'[\[\]*?:/\\]', clean['name']):
                return jsonify(error='Station names: maximum 91 characters; no [ ] * ? : / or backslash'), 400
        else:
            names = {s['id']: s['name'] for s in store.snapshot()['stations'] if s['status'].lower() == 'approved'}
            if clean['station_id'] not in names:
                return jsonify(error='Choose an approved station'), 400
            clean['station'] = names[clean.pop('station_id')]
        with rate_lock:
            now = time.monotonic()
            for ip in list(requests_by_ip):
                while requests_by_ip[ip] and requests_by_ip[ip][0] < now - 60:
                    requests_by_ip[ip].popleft()
                if not requests_by_ip[ip]:
                    del requests_by_ip[ip]
            recent = requests_by_ip[request.remote_addr]
            if len(recent) >= 5:
                return jsonify(error='Please wait a minute before requesting more'), 429
            recent.append(now)
        try:
            item = store.enqueue(clean)
        except ValueError as exc:
            return jsonify(error=str(exc)), 503
        return jsonify(id=item['id'], status='pending', message='Saved locally; awaiting Sheets sync and administrator approval'), 202

    @app.get('/stream/<station_id>')
    def stream(station_id):
        station = broadcasts.get(station_id)
        active = {s['id'] for s in store.snapshot()['stations'] if s['status'].lower() == 'approved'}
        if not station or station_id not in active:
            return jsonify(error='Station not found'), 404
        if not station.current:
            return jsonify(error='Station is waiting for approved audio'), 503
        if not slots.acquire(blocking=False):
            return jsonify(error='Listener capacity reached'), 503
        listener = station.subscribe()
        released = False

        def cleanup():
            nonlocal released
            if not released:
                released = True
                station.unsubscribe(listener)
                slots.release()

        def audio():
            try:
                yield from buffered_audio(listener, stop)
            finally:
                cleanup()

        response = Response(audio(), mimetype='audio/mpeg', headers={
            'Cache-Control': 'no-store, no-transform', 'X-Accel-Buffering': 'no',
            'icy-name': 'LAN Radio', 'icy-br': '128', 'Accept-Ranges': 'none'})
        response.call_on_close(cleanup)
        return response

    return app
