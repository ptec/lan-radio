import logging
import json
import time
import threading
import re
import ssl
from urllib.parse import quote, urlsplit
import requests
from .catalog import normalize_catalog

LOG = logging.getLogger(__name__)


class SyncError(RuntimeError):
    """An actionable error safe to display after secret redaction."""


class CatalogRedirectError(SyncError):
    """The catalog response redirect returned 404; a fresh read may succeed."""


class SheetSync:
    def __init__(self, store, broadcasts, url, token, request_delay=300, manual_cooldown=30):
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
            return dict(configured=bool(self.url and self.token), running=self.running,
                        requested=self.manual_requested, next_sync_at=self.due_at(time.time()),
                        last_completed=self.last_completed,
                        manual_available_at=(self.last_started + self.manual_cooldown) if self.last_started is not None else 0)

    def request_manual(self):
        with self.lock:
            if not self.url or not self.token:
                return 'unconfigured'
            if self.running or self.manual_requested:
                return 'queued'
            if self.last_started is not None and time.time() < self.last_started + self.manual_cooldown:
                return 'cooldown'
            self.manual_requested = True
            return 'queued'

    def call(self, **body):
        for attempt in range(3):
            try:
                return self._call_once(**body)
            except CatalogRedirectError:
                if attempt == 2:
                    raise
                LOG.warning('Catalog response redirect returned 404; requesting a fresh catalog (attempt %s/3).', attempt + 2)
                time.sleep(attempt + 1)

    def _call_once(self, **body):
        operation = {'catalog':'catalog fetch', 'edit_batch':'save edits', 'edit':'save edit',
                     'submit':'upload requests'}.get(body.get('action'), 'Sheets request')
        hops = []
        def host(url):
            try:
                value = urlsplit(url).hostname
            except (ValueError, TypeError):
                return 'unknown host'
            return value if value in ('script.google.com', 'script.googleusercontent.com', 'accounts.google.com') else 'configured or other host'
        def observe(response, *args, **kwargs):
            # Never retain URLs, headers, payloads, or redirected query tokens.
            hops.append((host(response.url), response.status_code))
        def diagnostic(message, failed_request=None):
            url = getattr(failed_request, 'url', None)
            target = host(url) if isinstance(url, str) else (hops[-1][0] if hops else host(self.url))
            stage = 'response redirect' if any(300 <= code < 400 for _, code in hops) else 'deployment request'
            chain = ' -> '.join(f'{name} HTTP {code}' for name, code in hops) or 'no HTTP response received'
            text = f'{operation}: {message} Stage: {stage}; host: {target}; responses: {chain}.'
            LOG.warning('%s', text)
            return SyncError(text)
        try:
            response = requests.post(self.url, data={'payload': json.dumps(dict(token=self.token, **body))},
                                     timeout=45, hooks={'response': observe})
        except requests.exceptions.SSLError as exc:
            # Requests/urllib3 wrap the original SSL exception in args/reason.
            pending, seen, codes = [exc], set(), []
            certificate = False
            while pending:
                error = pending.pop()
                if id(error) in seen:
                    continue
                seen.add(id(error))
                if isinstance(error, ssl.SSLCertVerificationError):
                    certificate = True
                    code = getattr(error, 'verify_code', None)
                    if isinstance(code, int): codes.append(f'verify_code={code}')
                if isinstance(error, BaseException):
                    pending.extend(error.args)
                    pending.extend(v for v in (getattr(error, 'reason', None), error.__cause__, error.__context__) if v is not None)
                # Only emit standard symbolic reason codes, never raw exception text.
                text = str(error)
                for code in ('CERTIFICATE_VERIFY_FAILED','UNEXPECTED_EOF_WHILE_READING',
                             'WRONG_VERSION_NUMBER','TLSV1_ALERT_INTERNAL_ERROR',
                             'SSLV3_ALERT_HANDSHAKE_FAILURE','TLSV1_ALERT_PROTOCOL_VERSION',
                             'TLSV1_ALERT_UNKNOWN_CA','CERTIFICATE_EXPIRED'):
                    if code in text and code not in codes: codes.append(code)
            certificate = certificate or 'CERTIFICATE_VERIFY_FAILED' in codes
            kind = 'TLS certificate verification failed' if certificate else 'TLS connection failed (certificate verification failure not established)'
            reason = ', '.join(codes) or 'no structured TLS reason available'
            raise diagnostic(f'{kind}; {reason}.', getattr(exc, 'request', None)) from None
        except requests.exceptions.Timeout as exc:
            raise diagnostic('Apps Script did not respond within 45 seconds.', exc.request) from None
        except requests.exceptions.ConnectionError as exc:
            raise diagnostic('Cannot connect to Google. Check network access, DNS and proxy settings.', exc.request) from None
        except requests.exceptions.RequestException as exc:
            raise diagnostic('HTTP request failed. Check network/proxy configuration.', exc.request) from None
        if not response.ok:
            hint = 'Check deployment access or the response redirect.' if response.status_code in (401, 403, 404) else 'Check Apps Script availability and quotas.'
            error = diagnostic(f'Apps Script returned HTTP {response.status_code}. {hint}', getattr(response, 'request', None))
            if (body.get('action') == 'catalog' and response.status_code == 404
                    and hops and hops[-1][0] == 'script.googleusercontent.com'
                    and any(name == 'script.google.com' and code == 302 for name, code in hops)):
                raise CatalogRedirectError(str(error))
            raise error
        try:
            data = response.json()
        except ValueError:
            raise SyncError('Apps Script returned a non-JSON page. Use the deployed /exec URL, execute as yourself, and allow Anyone access; the response may be a Google sign-in or error page.') from None
        if not isinstance(data, dict):
            raise SyncError('Apps Script returned an unexpected JSON value. Deploy the current Code.gs version.')
        if data.get('ok') is not True:
            detail = self.safe_error(data.get('error') or 'No error detail supplied')
            hint = ' Verify SHEETS_TOKEN matches Script Properties, then restart the service after .env changes.' if 'unauthorized' in detail.lower() else ' Check Apps Script Executions and run setup() if the spreadsheet has not been configured.'
            raise SyncError('Apps Script rejected the request: ' + detail + '.' + hint)
        return data

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
            data = self.call(action='submit', requests=outgoing)
            acknowledged = set(data.get('acknowledged', [])) & {r['id'] for r in pending}
            for rejected in data.get('rejected', []):
                if rejected.get('id') in acknowledged:
                    self.store.reject_request(rejected['id'], rejected.get('error', 'Rejected by Sheets'))
            self.store.acknowledge(acknowledged)
            if len(acknowledged) != len(pending):
                details = '; '.join(self.safe_error(e.get('error', 'Unknown error')) for e in data.get('errors', []) if isinstance(e, dict))
                raise SyncError('Some queued requests were rejected by Sheets' + (': ' + details if details else ''))

    def pull(self):
        data = self.call(action='catalog')
        self.store.replace(normalize_catalog(data))
        self.warnings = data.get('warnings', [])
        self.broadcasts.refresh()
        self.last_success = time.time()

    def tick(self):
        """Run at most one due sync. Only the background thread calls this."""
        with self.lock:
            if not self.url or not self.token:
                self.error = 'Google Sheets is not configured'
                return
            now = time.time()
            due = self.due_at(now)
            if self.running or (not self.manual_requested and (due is None or due > now)):
                return
            self.running = True
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
            # Always pull, including after upload failure, so moderation flows in.
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
