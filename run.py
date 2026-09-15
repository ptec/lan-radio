import logging
import multiprocessing
import os
import shutil
import threading
from pathlib import Path
from dotenv import load_dotenv
from filelock import FileLock, Timeout
from waitress import serve
from radio.store import Store
from radio.audio import Broadcasts
from radio.download import worker
from radio.sync import SheetSync
from radio.web import create_app


def main():
    load_dotenv(Path(__file__).with_name('.env'))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    ffmpeg = os.getenv('FFMPEG', 'ffmpeg')
    if not shutil.which(ffmpeg):
        raise SystemExit('ffmpeg is missing from PATH; set FFMPEG in .env')
    store = Store(os.getenv('DATA_DIR', str(Path(__file__).parent / 'data')))
    lock = FileLock(str(store.root / 'service.lock'))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise SystemExit('Another radio service is already using this DATA_DIR')
    stop = threading.Event()
    context = multiprocessing.get_context('spawn')
    worker_stop = context.Event()
    broadcasts = Broadcasts(store, stop)
    sync = SheetSync(store, broadcasts, os.getenv('SHEETS_URL', ''), os.getenv('SHEETS_TOKEN', ''),
                     request_delay=max(5, int(os.getenv('REQUEST_SYNC_DELAY_SECONDS', '300'))),
                     manual_cooldown=max(1, int(os.getenv('MANUAL_SYNC_COOLDOWN_SECONDS', '30'))))
    sync_thread = threading.Thread(target=sync.run, args=(stop,), daemon=True)
    process = context.Process(target=worker, args=(str(store.root), ffmpeg, worker_stop), name='audio-downloads')
    listeners = max(1, int(os.getenv('MAX_LISTENERS', '24')))
    try:
        process.start()
        sync_thread.start()
        serve(create_app(store, broadcasts, sync, stop, listeners),
              host=os.getenv('HOST', '0.0.0.0'), port=int(os.getenv('PORT', '8080')),
              threads=listeners + 8, channel_timeout=30)
    finally:
        stop.set()
        worker_stop.set()
        # Allow the current bounded download/conversion to finish cleanly.
        if process.pid:
            process.join()
        sync_thread.join(timeout=95)
        lock.release()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
