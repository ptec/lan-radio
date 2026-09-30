"""Read-only Sheets connection probe. Does not change Sheets or the local catalog."""
import argparse
import logging
import os
import platform
import ssl
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from radio.gas import request, GasError as SyncError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempts', type=int, default=5, choices=range(1, 11))
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name('.env'))
    url = os.getenv('SHEETS_URL', '')
    if not url:
        parser.error('Configure SHEETS_URL first.')
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    print(f'{platform.system()}; Python {platform.python_version()}; {ssl.OPENSSL_VERSION}; Requests {requests.__version__}')
    print('Custom CA bundle configured:', bool(os.getenv('REQUESTS_CA_BUNDLE') or os.getenv('CURL_CA_BUNDLE')))
    print('Proxy environment configured:', any(os.getenv(k) for k in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')))
    print('Mode: requests.get, single attempts, no automatic retries')
    successes = 0
    for index in range(args.attempts):
        started = time.monotonic()
        try:
            result = request(dict(action='getStations'), url)
            successes += 1
            print(f'Attempt {index+1}: OK, {len(result)} stations, {time.monotonic()-started:.2f}s')
        except SyncError as exc:
            print(f'Attempt {index+1}: {exc}')
        except Exception as exc:
            # Never print arbitrary exception strings that could contain URLs.
            print(f'Attempt {index+1}: local diagnostic failure ({type(exc).__name__})')
        if index + 1 < args.attempts:
            time.sleep(2)
    print(f'{successes}/{args.attempts} catalog reads succeeded. No changes were written.')
    return 0 if successes == args.attempts else 1


if __name__ == '__main__':
    raise SystemExit(main())
