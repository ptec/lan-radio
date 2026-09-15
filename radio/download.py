import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from .store import Store, media_key

LOG = logging.getLogger(__name__)


def download(song, store, ffmpeg):
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
        output.replace(store.path(song))  # same filesystem: readers see only complete files


def worker(directory, ffmpeg, stop):
    logging.basicConfig(level=logging.INFO)
    store = Store(directory)
    while not stop.is_set():
        for song in store.approved():
            if stop.is_set():
                return
            key = media_key(song)
            if not any(media_key(current) == key for current in store.approved()):
                continue  # the catalog may have changed during the last download
            if store.path(song).is_file() or not store.retry_due(key):
                continue
            store.media_state(key, 'downloading')
            try:
                download(song, store, ffmpeg)
                store.media_state(key, 'ready')
            except Exception as exc:
                LOG.warning('Download failed for %s: %s', song['title'], exc)
                store.media_state(key, 'failed', str(exc), time.time() + 3600)
        stop.wait(5)
