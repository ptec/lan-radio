import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from .store import Store, media_key

LOG = logging.getLogger(__name__)


def download(song, store, ffmpeg):
    generation = store.cache_generation()
    video = song.get('youtube_id', '').strip()
    if video and not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise ValueError('youtube_id must be an 11-character YouTube video ID')
    query = 'https://www.youtube.com/watch?v=' + video if video else 'ytsearch1:' + song['artist'] + ' - ' + song['title'] + ' audio'
    with tempfile.TemporaryDirectory(dir=store.cache) as directory:
        result = subprocess.run([
            sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
            '--no-progress', '--max-downloads', '1', '--socket-timeout', '30',
            '--retries', '3', '--match-filter', '!is_live & duration <= 1800',
            '-f', 'bestaudio/best', '-o', str(Path(directory) / 'source.%(ext)s'), query
        ], capture_output=True, text=True, timeout=900)
        files = [p for p in Path(directory).glob('source.*') if p.suffix not in ('.part', '.ytdl')]
        if not files:
            raise RuntimeError('YouTube download failed: ' + result.stderr[-1000:])
        output = Path(directory) / 'normalized.mp3'
        result = subprocess.run([
            ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(files[0]), '-vn',
            '-map_metadata', '-1', '-ac', '2', '-ar', '44100', '-c:a', 'libmp3lame',
            '-b:a', '128k', '-reservoir', '0', '-write_xing', '0', '-id3v2_version', '0',
            str(output)
        ], capture_output=True, text=True, timeout=900)
        if result.returncode:
            raise RuntimeError('Conversion failed: ' + result.stderr[-1000:])
        from .audio import frames
        if sum(1 for _ in frames(output)) == 0:
            raise ValueError('Empty audio file')
        store.publish_audio(song, output, generation)


def download_workers():
    """Choose a conservative default while allowing deployment tuning."""
    configured = os.getenv('DOWNLOAD_WORKERS', '').strip()
    if configured:
        try:
            count = int(configured)
            if count != 0:
                return max(1, min(32, count))
        except ValueError:
            LOG.warning('Invalid DOWNLOAD_WORKERS=%r; using CPU-based default', configured)
    # yt-dlp is network-heavy, while FFmpeg uses CPU. Leave one CPU for Flask
    # and OS work, and cap the default so a large server does not overwhelm LAN.
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def pending_downloads(store):
    """Return approved, uncached songs in station round-robin order."""
    catalog = store.snapshot()
    station_ids = [s['id'] for s in catalog['stations'] if s['status'].lower() == 'approved']
    by_station = {station_id: [] for station_id in station_ids}
    seen = set()
    # Catalog order is retained within each station. Alternating station rows
    # means a large playlist cannot keep newly approved songs elsewhere waiting.
    for song in catalog['songs']:
        if song['station_id'] not in by_station or song['status'].lower() != 'approved':
            continue
        key = media_key(song)
        if key in seen or store.path(song).is_file() or not store.retry_due(key):
            continue
        seen.add(key)
        by_station[song['station_id']].append(song)
    queue = []
    while True:
        added = False
        for station_id in station_ids:
            if by_station[station_id]:
                queue.append(by_station[station_id].pop(0))
                added = True
        if not added:
            return queue


def _download_one(song, store, ffmpeg, stop):
    if stop.is_set():
        return
    key = media_key(song)
    generation = store.cache_generation()
    # The catalog may be edited while a queue is running. Do not start work for
    # a song that is no longer approved or has already been cached by a sibling.
    if stop.is_set() or store.path(song).is_file() or not any(media_key(current) == key for current in store.approved()):
        return
    store.media_state(key, 'downloading', generation=generation)
    try:
        download(song, store, ffmpeg)
        if store.path(song).is_file():
            store.media_state(key, 'ready', generation=generation)
    except Exception as exc:
        LOG.warning('Download failed for %s: %s', song['title'], exc)
        store.media_state(key, 'failed', str(exc), time.time() + 3600, generation=generation)


def worker(directory, ffmpeg, stop, max_workers=None):
    logging.basicConfig(level=logging.INFO)
    store = Store(directory)
    workers = max_workers if max_workers is not None else download_workers()
    LOG.info('Audio download worker using %d concurrent job(s)', workers)
    while not stop.is_set():
        queue = pending_downloads(store)
        if not queue:
            stop.wait(5)
            continue
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='audio-download') as pool:
            futures = [pool.submit(_download_one, song, store, ffmpeg, stop) for song in queue]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    LOG.exception('Unexpected download worker error')
                if stop.is_set():
                    for pending in futures:
                        pending.cancel()
                    return
