"""Password-protected maintenance routes; deliberately absent from navigation."""
import hmac
import hashlib
import json
import os
import re
import secrets
import time
from functools import wraps
from urllib.parse import urlsplit

from flask import jsonify, render_template, request, Response, send_file, redirect
from itsdangerous import URLSafeTimedSerializer, BadSignature
from .store import media_key
from .review import MetadataReview, review_key


def register_testing(app, store, broadcasts, sync, search, stop):
    started = time.monotonic()
    password = os.getenv('TESTING_PASSWORD', '')
    signer = URLSafeTimedSerializer(secrets.token_hex(32), salt='radio-debug')
    review = MetadataReview(store, search, stop)

    def authenticated():
        try:
            return signer.loads(request.cookies.get('radio_debug', ''), max_age=28800) == 'debug'
        except BadSignature:
            return False

    @app.route('/admin/login', methods=['GET', 'POST'])
    def debug_login():
        if not password:
            return Response('Set TESTING_PASSWORD and restart to enable debugging.', status=503)
        error = None
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin and urlsplit(origin).netloc != request.host:
                return Response('Cross-origin request rejected', status=403)
            if hmac.compare_digest(request.form.get('password', '').encode(), password.encode()):
                response = redirect('/admin')
                response.set_cookie('radio_debug', signer.dumps('debug'), max_age=28800,
                                    httponly=True, samesite='Strict', secure=request.is_secure)
                response.headers['Cache-Control'] = 'no-store'
                return response
            error = 'Incorrect password.'
        return render_template('debug-login.html', error=error), 401 if error else 200

    @app.after_request
    def private_debug_response(response):
        if request.path.startswith(('/admin', '/api/admin')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def protected(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not password:
                return Response('Set TESTING_PASSWORD and restart to enable testing.', status=503)
            if not authenticated():
                if request.path == '/admin':
                    return redirect('/admin/login')
                return jsonify(error='Sign in at /admin to continue.'), 401
            if request.method == 'POST':
                if not request.is_json:
                    return jsonify(error='JSON required'), 415
                origin = request.headers.get('Origin')
                if origin and urlsplit(origin).netloc != request.host:
                    return jsonify(error='Cross-origin request rejected'), 403
            return fn(*args, **kwargs)
        return wrapped

    @app.get('/admin')
    @protected
    def testing_page():
        return render_template('testing.html')

    @app.post('/api/admin/cache')
    @protected
    def testing_cache():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('mode') not in ('unused', 'all'):
            return jsonify(error='Choose unused or all'), 400
        mode = body['mode']
        if body.get('confirm') is not True:
            return jsonify(**store.clean_cache(mode, dry_run=True))
        result = store.clean_cache(mode)
        return jsonify(**result, message=f"Deleted {result['deleted']} cached audio files. {result['failed']} files could not be removed (they may be in use); retry cleanup for those files.")

    @app.get('/api/admin')
    @protected
    def testing_catalog():
        catalog = store.snapshot()
        states = store.media_states()
        reviews = review.results()
        active = {station['id'] for station in catalog['stations'] if station['status'] == 'approved'}
        songs = [dict(song, metadata_review=reviews.get(review_key(song), dict(state='unchecked')),
                      cached=store.path(song).is_file(),
                      download_status='ready' if store.path(song).is_file() else states.get(media_key(song), 'queued' if song['status'] == 'approved' and song['station_id'] in active else 'not_scheduled'))
                 for song in catalog['songs']]
        files = list(store.cache.glob('*.mp3'))
        return jsonify(stations=catalog['stations'], songs=songs, uptime_seconds=int(time.monotonic()-started),
                       cache_files=len(files), cache_bytes=sum(p.stat().st_size for p in files if p.exists()),
                       review_scan=review.status(), last_sync=sync.last_success, sync_error=sync.error, **store.diagnostics())

    @app.post('/api/admin/review')
    @protected
    def review_start():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(error='Invalid scan request'), 400
        try:
            started = review.start(force=body.get('force') is True, scope=body.get('scope'), song_id=body.get('id'), tool=body.get('tool', 'metadata'))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if not started:
            return jsonify(error='An iTunes scan is already running. Both tools share this scan.'), 409
        return jsonify(scan=review.status()), 202

    @app.get('/api/admin/review')
    @protected
    def review_status():
        results = review.results()
        return jsonify(scan=review.status(), songs={song['id']:results.get(review_key(song), dict(state='unchecked'))
                       for song in store.snapshot()['songs']})

    @app.get('/api/admin/audio/<song_id>')
    @protected
    def testing_audio(song_id):
        song = next((s for s in store.snapshot()['songs'] if s['id'] == song_id), None)
        if not song or not store.path(song).is_file():
            return jsonify(error='Cached audio is not available'), 404
        return send_file(store.path(song), mimetype='audio/mpeg', conditional=True, max_age=0)

    @app.post('/api/admin/refresh')
    @protected
    def testing_refresh():
        with sync.lock:
            if sync.running:
                return jsonify(error='A sync is running. Use Sync with Sheets when it finishes.'), 409
            if not sync.url or not sync.token:
                return jsonify(error='Google Sheets is not configured'), 503
            try:
                sync.pull()
            except Exception as exc:
                return jsonify(error=sync.safe_error(exc)), 502
        return jsonify(message='Catalog refreshed from Sheets.')

    @app.post('/api/admin/edits')
    @protected
    def testing_edits():
        body = request.get_json(silent=True)
        edits = body.get('edits') if isinstance(body, dict) else None
        if not isinstance(edits, list) or not 1 <= len(edits) <= 50:
            return jsonify(error='Expected 1 to 50 edits'), 400
        with sync.lock:
            if sync.running:
                return jsonify(error='A sync is running. Wait until it finishes.'), 409
            if not sync.url or not sync.token:
                return jsonify(error='Google Sheets is not configured'), 503
            catalog = store.snapshot()
            songs = {s['id']:s for s in catalog['songs']}
            stations = {s['id']:s for s in catalog['stations']}
            outgoing, results, seen = [], [], set()
            for edit in edits:
                if not isinstance(edit, dict) or not isinstance(edit.get('id'), str):
                    return jsonify(error='Invalid edit'), 400
                key = edit['id']
                if key in seen:
                    return jsonify(error='Duplicate edit'), 400
                seen.add(key)
                song, changes = songs.get(key), edit.get('changes')
                if not song:
                    results.append(dict(id=key,saved=False,error='Song changed or was removed. Reload and review.'))
                    continue
                original = {f:song.get(f,'') for f in ('title','artist','status','youtube_id')}
                original['notes'] = song.get('notes', '')
                supplied = edit.get('original')
                if not isinstance(supplied, dict) or dict(supplied, notes=supplied.get('notes', '')) != original:
                    results.append(dict(id=key,saved=False,error='Song changed. Reload and review.'))
                    continue
                if not isinstance(changes, dict) or any(not isinstance(changes.get(f),str) or not 1 <= len(changes[f].strip()) <= 200 for f in ('title','artist')) or not isinstance(changes.get('youtube_id',''),str) or (changes.get('youtube_id','').strip() and not re.fullmatch(r'[A-Za-z0-9_-]{11}', changes['youtube_id'].strip())):
                    results.append(dict(id=key,saved=False,error='Invalid title, artist or YouTube ID'))
                    continue
                if changes.get('status', song['status']) not in ('approved', 'pending', 'rejected') or not isinstance(changes.get('notes', song.get('notes', '')), str) or len(changes.get('notes', song.get('notes', ''))) > 2000:
                    results.append(dict(id=key, saved=False, error='Invalid moderation status or notes (maximum 2000 characters)'))
                    continue
                station = stations[song['station_id']]
                request_id = edit.get('request_id', '')
                if not isinstance(request_id, str) or len(request_id) > 200:
                    return jsonify(error='Invalid edit request ID'), 400
                item = dict(id=key,request_id=request_id,station=station['name'],station_status=station['status'],original=original,
                            changes={f:changes.get(f,'').strip() for f in ('title','artist','youtube_id')})
                item['changes'].update(status=changes.get('status', song['status']), notes=changes.get('notes', song.get('notes', '')).strip())
                item['request_token'] = hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
                outgoing.append(item)
            if outgoing:
                try:
                    response = sync.call(action='edit_batch', edits=outgoing)
                    replies = {r['id']:r for r in response.get('results',[]) if isinstance(r,dict) and isinstance(r.get('id'),str)}
                    for item in outgoing:
                        reply = replies.get(item['id'], {})
                        moderation_changed = any(item['changes'][f] != item['original'][f] for f in ('status', 'notes'))
                        if moderation_changed and reply.get('moderation_version') != 1:
                            reply = dict(saved=False, error='Deploy the updated Code.gs web app before saving moderation or notes.')
                        results.append(dict(id=item['id'], saved=reply.get('saved') is True,
                                            error=sync.safe_error(reply.get('error') or 'Save was not acknowledged') if reply.get('saved') is not True else None))
                except Exception as exc:
                    return jsonify(error=sync.safe_error(exc)+' Delivery may have succeeded; edits remain unsaved until acknowledged.'), 502
        return jsonify(results=results)

    @app.post('/api/admin/edit')
    @protected
    def testing_edit():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error='Invalid edit'), 400
        changes = body.get('changes')
        if not isinstance(changes, dict) or any(not isinstance(changes.get(f), str) or not 1 <= len(changes[f].strip()) <= 200 for f in ('title', 'artist')):
            return jsonify(error='Title and artist are required (maximum 200 characters)'), 400
        video = changes.get('youtube_id', '')
        if not isinstance(video, str) or (video.strip() and not re.fullmatch(r'[A-Za-z0-9_-]{11}', video.strip())):
            return jsonify(error='YouTube ID must be empty or an 11-character video ID'), 400
        if 'status' in changes and changes['status'] not in ('approved', 'pending', 'rejected'):
            return jsonify(error='Invalid moderation status'), 400
        if 'notes' in changes and (not isinstance(changes['notes'], str) or len(changes['notes']) > 2000):
            return jsonify(error='Invalid notes'), 400
        changes = {f: v.strip() for f, v in changes.items() if f in ('title', 'artist', 'youtube_id', 'status', 'notes')}
        changes.setdefault('youtube_id', '')
        with sync.lock:
            if sync.running:
                return jsonify(error='A sync is running. Try again when it finishes.'), 409
            if not sync.url or not sync.token:
                return jsonify(error='Google Sheets is not configured'), 503
            catalog = store.snapshot()
            song = next((s for s in catalog['songs'] if s['id'] == body.get('id')), None)
            if not song:
                return jsonify(error='Song changed or was removed. Reload the catalog.'), 409
            station = next(s for s in catalog['stations'] if s['id'] == song['station_id'])
            original = {f: song.get(f, '') for f in ('title', 'artist', 'status', 'youtube_id')}
            original['notes'] = song.get('notes', '')
            supplied = body.get('original')
            if not isinstance(supplied, dict) or dict(supplied, notes=supplied.get('notes', '')) != original:
                return jsonify(error='Song changed. Reload before editing.'), 409
            try:
                result = sync.call(action='edit', station=station['name'], station_status=station['status'],
                                   original=original, changes=changes)
                if any(f in changes and changes[f] != original[f] for f in ('status', 'notes')) and result.get('moderation_version') != 1:
                    return jsonify(error='Deploy the updated Code.gs web app before saving moderation or notes.'), 502
                if result.get('conflict'):
                    return jsonify(error=result.get('error', 'Spreadsheet row changed. Sync and reload.')), 409
            except Exception as exc:
                return jsonify(error=sync.safe_error(exc) + ' Reload and sync before retrying; delivery may have succeeded.'), 502
            if body.get('defer_refresh') is True:
                return jsonify(message='Saved to Sheets. Catalog refresh pending.')
            try:
                sync.pull()
            except Exception as exc:
                return jsonify(message='Saved to Sheets, but catalog refresh failed. Use Sync now.', warning=sync.safe_error(exc))
        return jsonify(message='Saved to Sheets and refreshed. Changed recordings will download through the normal queue.')
