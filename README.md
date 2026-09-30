# Local Frequency — Flask LAN radio

One continuous broadcast per station, with a browser receiver, Google Sheets approval, durable offline request storage, and one serial download/conversion process. Python 3.11+ and FFmpeg with libmp3lame are required.

## Run

From this directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env with your Apps Script deployment URL and secret.
python run.py
```

On Linux/macOS, activate with `source .venv/bin/activate` and copy using `cp .env.example .env`.

Open `http://localhost:8080` on the server, or `http://SERVER_LAN_IP:8080` on other devices. Allow inbound TCP 8080 through the server's private-network firewall. Use the server's Wi-Fi/Ethernet IPv4 address, not `0.0.0.0`. Click Tune in to start audio (browsers require a user gesture).

YouTube extraction may require a supported JavaScript runtime such as Deno, depending on upstream requirements. See the [yt-dlp installation documentation](https://github.com/yt-dlp/yt-dlp#installation). Keep yt-dlp current with `python -m pip install -U "yt-dlp[default]"`. Use content you have permission to download and broadcast.

## Testing and correcting recordings

Under **Cache maintenance**, **Delete unused audio** removes managed MP3 files not referenced by any current local catalog song (including pending/rejected rows). Sync first to incorporate spreadsheet changes. **Clear all cached audio** removes managed MP3s and resets download state so approved songs rebuild through the download queue. Both show counts and require confirmation. Files currently locked by playback may be skipped and reported for retry. Active temporary download directories are left to workers; downloads that started before a full reset cannot publish stale results. Catalog data, requests, and metadata-review results are preserved.

Admin saves are grouped by station using `updateStation`. The returned song values are checked before edits are marked saved. Failed rows remain unsaved. Deploy the revised Apps Script and Python service together; the previous API is not compatible.

The debug page also offers an advisory **iTunes metadata review**. Start **Scan new / failed checks** or **Rescan all songs** to run a paced background scan (about one unique title/artist pair every five seconds). Exact means case-sensitive title and artist equality against up to 20 search results. Missing results and spelling/capitalization differences appear under **Needs metadata review**; connection or provider failures appear separately under **iTunes search failed**. Approval and playback are never changed. Results are saved locally and reused across stations; saved title/artist edits require a new scan. The scan continues if you close the page, but stops when the service shuts down; scan new checks to resume afterward. Filters and counts use the current catalog. iTunes may lack a valid song, so flags are suggestions for human review, not evidence that audio is wrong.

Set a separate `TESTING_PASSWORD` in `.env` and restart, then open `/admin` (for example, `http://radio.local/admin`). Sign in using that password; no username is needed. Sign-in lasts eight hours or until the service restarts. There is no homepage link. Password sign-in over HTTP is suitable only for a trusted LAN; use HTTPS on untrusted networks.

The page shows service uptime since app startup, cache size, download counts, queued requests, and last sync. Filter by station, search, and preview the actual cached MP3 with seeking without interrupting the broadcast. **Next cached song** steps through the filtered list. Previewing does not automatically identify recordings or approve songs. Refresh the catalog to update statistics and download states.

Deploy the updated `google-apps-script/Code.gs` web app before using **Save to spreadsheet**. Edits immediately update Title, Artist, and YouTube ID in the matching station tab and pull the catalog back. Approval is preserved. Changed recordings use a new cache key and approved songs join the normal download queue. Old cached files are retained, including audio used by other stations. Blank YouTube ID uses search; an 11-character ID selects a specific video. Automatic-search results from earlier downloads do not have a recorded source video ID.

Edits match the original row contents rather than row numbers or spreadsheet IDs. Changed, deleted, or duplicate rows require resolving the conflict in Sheets and syncing again. If saving succeeds but refreshing fails, use Sync now; do not assume the save failed. Google Sheets UI edits made at the exact same moment cannot be locked by Apps Script, so avoid editing the same row in both interfaces simultaneously.

## Google Sheet setup (deployment)

The station collection shows audio download progress separately from moderation status. Failed downloads show **Download failed** with a **Retry download** button for approved songs. Retry adds the recording back to the normal download queue, bypassing the automatic one-hour retry delay; it waits for the download worker's current batch to finish. Cached audio is shared across stations, so one retry also covers matching recordings on other stations.

Song requests offer iTunes suggestions while you type in either half of the combined title/artist field. Click a suggestion, or use the arrow keys and Enter, to fill both fields. Manual entry is always available. Searches are sent through the server to Apple; no API key is needed. Results are cached for ten minutes and shared across listeners, with a maximum of 20 provider searches per minute. Selecting a result still requires sending the request and normal administrator approval.

1. Open **Extensions → Apps Script** in your spreadsheet and paste `google-apps-script/Code.gs`.
2. Each tab is a station, named exactly as listeners should see it. There are no prefixes, metadata tabs, receipt tabs, or station approval flags.
3. Use these five columns in order: **Title, Artist, YouTube Id, Status, Notes**. Song statuses are `pending`, `approved`, and `not-approved`. Only approved songs play.
4. Deploy as a web app and put its `/exec` URL in `SHEETS_URL`. This script has no authentication: an Anyone deployment allows anyone with the URL to read and modify the data.
5. Start the service and click **Sync now**. New station requests create ordinary tabs. New song requests are added as pending songs.

## Spreadsheet editing

Add, edit, sort, or delete whole song rows directly in Sheets. Rename or delete tabs to rename or remove stations. The next successful sync replaces the local catalog. Every sheet is a playlist; keep instructions and unrelated data in a separate spreadsheet.

For an existing installation, manually rename old prefixed tabs to their desired display names and remove obsolete bookkeeping tabs after backing up the spreadsheet. The app will not rename or delete your sheets automatically. Arrange columns in the order above and replace old `rejected` values with `not-approved`. Existing cached audio is retained.

## HTTP bridge

`radio/gas.py` uses `requests.get` for `getStations` and `getStation`, and `requests.post` for `createStation` and `updateStation`. JSON is URL-encoded in the `q` parameter; POST bodies are empty. Responses contain `ok` and `content`. There is no shared secret, session wrapper, or automatic HTTP retry. Requests follows Google's redirects and verifies TLS certificates. Connection timeout is 10 seconds; read inactivity timeout is 45 seconds.

A catalog sync lists the tabs, then reads each station. Edits are grouped by station and matched by `title:artist`; returned values are checked before they are marked saved. Ambiguous keys or changed rows require manual review. These checks cannot prevent a simultaneous human edit between the read and write. A failed full catalog read retains the previous local catalog.

## Local storage

SQLite persists the offline catalog, queued requests, download states, and iTunes review results across restarts and coordinates the web and download processes. Audio is stored separately as MP3 files, addressed by a stable hash of normalized title, artist, and optional YouTube ID. This avoids invalid filenames, long paths, and ambiguous delimiter combinations while sharing recordings across stations. No database or audio-cache migration is required by this sync change.

## Browsing songs and syncing

The left sidebar contains a scrollable station list with each station's current song and a **Tune in** button. Click a station name to open it in the main view without interrupting your current audio. The first available station is selected automatically; playback still requires a click. The receiver identifies the station you are actually listening to when you browse another one.

The main view shows **Now playing** and **Up next**. Up next previews the actual shuffled queue and only includes approved, cached audio. Refreshing the UI does not reshuffle it. It may change after downloads or catalog edits. Metadata describes the server broadcast and can lead audible playback by the client buffer delay.

Each station plays every distinct available recording once per shuffled cycle. The next cycle is shuffled again, with its first song chosen to differ from the last song of the previous cycle whenever at least two recordings are available. With only one playable recording, repetition is unavoidable. Newly approved/downloaded songs join the remaining cycle; deleted, unapproved, or unavailable recordings drop out. These updates do not restart the cycle or replay songs already consumed in it. A service restart or station rename starts a fresh rotation. Songs share a shuffle slot when their cache identity (normalized title, artist, and optional YouTube ID) matches.

The station collection lists all song rows, including rejected songs and locally queued requests, with search and status filters. **Request a song** opens an inline form above the list, automatically targeting the selected station; no scrolling to the bottom is needed. Song requests remain disabled for pending stations. The sidebar also retains **Request a station**. **Sync now**, sync status, and expandable error history live at the bottom of the sidebar. On narrow screens the sidebar becomes a compact area above the main view with a scrollable station list.

Uploaded requests show **Pending approval**, and local requests show **Waiting to sync**. Approved songs awaiting download show **Preparing audio**; rejected songs remain visible but never enter playback.

**Sync now** is available to all clients on the trusted LAN. The button schedules work in the background, uploads queued requests, then refreshes the catalog. Repeated clicks while queued/running are coalesced, and a global cooldown (30 seconds by default) limits subsequent manual syncs. Sync does not approve songs. The header reports progress, the next queued sync time, errors, and the last successful catalog update.

Automatic sync uses the oldest queued request's creation time plus five minutes. New requests join that batch without postponing the deadline; creation times survive restarts. A backlog already overdue at startup syncs promptly. Existing legacy requests without timestamps begin their delay when first detected. The service drains up to 1,000 requests per cycle in batches of 100. Outstanding requests after a failure or during an ongoing cycle retry after another five minutes. When the outbound queue is empty, there are no background Sheets calls. If the upload succeeds but the catalog fetch fails, use **Sync now** to retry; an empty queue does not trigger a retry by itself.

On a fresh installation, click **Sync now** to load an existing Sheet. After manual moderation in the Sheet, click it again to fetch those changes. The browser's five-second UI refresh only reads the local service; it never calls Sheets.

The old `SYNC_SECONDS` and `REQUEST_SYNC_SECONDS` settings are no longer used. Existing `.env` files can keep them harmlessly, or replace them with the new settings from `.env.example`. Defaults already provide the requested five-minute behavior. No Apps Script redeployment is needed for these two features if the station-tab version is already deployed.

API additions: `GET /api/stations/<station_id>/songs` returns all song statuses and locally queued requests. `/api/stations` includes `now_playing` and `up_next` metadata. `POST /api/sync` with a JSON body (`{}`) schedules synchronization, returning 202, 429 during cooldown, or 503 when Sheets is not configured. `GET /api/health` includes sync progress/deadlines. These endpoints follow the existing trusted-LAN access model.

## Runtime behavior

### Diagnosing sync failures

The header and server console now report the underlying sync error: timeout, connection or certificate failure, HTTP status, non-JSON response, Apps Script rejection, or catalog validation failure. Expand **Recent sync failures** to see the last ten failed attempts, retained across successful syncs and service restarts. The same sanitized history is available as `recent_sync_failures` in `/api/health`. Request URLs are redacted.

If you change `.env`, restart the service. For non-JSON responses, verify the deployed `/exec` URL and access settings. Deploy the matching Code.gs version for API errors. Inspect Apps Script Executions for recurring failures. Keep TLS verification enabled.

- New listener connections accumulate about four seconds of 128 kbps audio before the first response chunk is sent. This gives the browser a startup buffer to reduce initial stuttering. The app displays a buffering message while connecting. Tuning, switching stations, and reconnecting all use this buffer; afterward audio continues at the normal live cadence. This adds approximately four seconds of listening delay plus the browser's own buffering, without changing the shared station clock.
- Startup loads the saved catalog immediately without contacting Sheets. Automatic synchronization happens only when outbound requests are queued, after the configured delay; manual synchronization is always available when Sheets is configured. A failed upload does not block the catalog fetch in that sync cycle. Pending request uploads retry on the normal queue schedule after failure. Existing station names and title/artist checks prevent ordinary duplicates; a deleted row may be recreated by a later retry.
- Approved songs download and convert concurrently in a separate Python process. The queue is built in station round-robin order: one song from each approved station, then the next song from each station, so clean-install startup brings every station online progressively. The default pool is `max(1, min(8, CPU count - 1))`; set `DOWNLOAD_WORKERS` to a positive value to override it (the service clamps overrides to 32). Each job uses its own yt-dlp and FFmpeg subprocess, while the bounded pool limits total resource use. yt-dlp searches YouTube; FFmpeg normalizes to stereo 44.1 kHz / 128 kbps MP3 with the bit reservoir disabled. This permits new listeners to decode from any complete frame. Files become visible atomically after validation. Failures retry after an hour and are logged; details are also stored in SQLite's `media` table. On a one-CPU host the default is one job. Jobs already running finish when the service stops.
- Each station runs continuously even with zero listeners. Cached MP3 frames are paced against a monotonic clock and fanned out in approximately 261 ms chunks. A late listener receives upcoming live frames, not the beginning of a playlist. A queue exceeding about eight seconds (31 normal audio chunks) disconnects the slow listener. Reconnect to live resets browser buffering. Stations with no playable content show as preparing; their stream returns 503.
- Browser/device buffers mean listeners may differ by several seconds. This is live radio, not synchronized multiroom audio. The displayed song describes the server broadcast and can lead audible playback by the buffer delay. Tracks may have small encoder-padding gaps. Service restarts restart station rotation; station changes take effect at track boundaries, while revocations are checked during playback after catalog sync.
- The cache deduplicates by normalized title/artist and optional video ID, across stations. Keep `data/` across restarts. It contains SQLite, complete MP3s, and transient downloads. No automatic eviction is performed. Stop the service before manually removing cached files. Unapproved audio is retained on disk but excluded from playback.
- Use **one service process** via `python run.py`; it starts Waitress with listener slots plus spare API threads. Do not use Flask's debug reloader or multiple WSGI workers. A file lock prevents duplicate runtimes using the same data directory. Default capacity is 24 listeners; each consumes a WSGI thread and approximately 128 kbps of server outbound bandwidth. This targets a small trusted LAN. API requests are limited to five per client IP per minute and 1,000 queued requests.
- Shutdown waits for the active download/conversion to finish (each command has a 15-minute timeout). Streaming threads stop immediately. If a download worker crashes unexpectedly, restart the service; existing cached broadcasts continue. This version does not supervise/restart that worker automatically.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8080` | LAN bind address and port |
| `DATA_DIR` | `data` beside run.py | Persistent storage; relative paths resolve from working directory |
| `SHEETS_URL` | empty | Apps Script deployment URL; the new API does not use a shared secret |
| `REQUEST_SYNC_DELAY_SECONDS` | `300` | Delay after the oldest queued request, and delay between upload retries (minimum 5 seconds) |
| `MANUAL_SYNC_COOLDOWN_SECONDS` | `30` | Global minimum interval between sync starts requested by clients (minimum 1 second) |
| `MAX_LISTENERS` | `24` | Global active-stream limit |
| `FFMPEG` | `ffmpeg` | Executable name or absolute path |

Without Sheets configuration the UI runs and retains station requests locally, but no catalog is created automatically. `/api/health` exposes catalog-sync status, pending request count, and aggregate download state. No authentication is required on the listening/request UI. Keep it on a trusted LAN; do not port-forward it to the internet. If using a reverse proxy, disable buffering/compression for `/stream/`, allow long-lived responses, and preserve Host. Keep `.env` private.

## Verify

```sh
python -m unittest discover -s tests -v
node tests/test_apps_script.cjs
node tests/test_interface.cjs
```

Python tests exercise FFmpeg framing, live broadcasts, snapshot replacement, edits/deletions, station retirement, cache reuse on renames, request retries and API boundaries. Node tests simulate Sheets moderation: editing, deleting, sorting, moving rows, renaming/deleting tabs, column changes, duplicate detection and migration. They do not require a Google account or YouTube downloads. Actual Sheets deployment and YouTube extraction require your configuration and network access.

Implementation uses Flask's [streaming response interface](https://flask.palletsprojects.com/en/stable/patterns/streaming/).


## Moderation and iTunes checks

The password-protected `/admin` page is also the moderation page. It opens with **All stations** and **All songs** selected; choose **Pending approval** to focus on moderation requests. The **Moderation** column edits approval and public moderator notes. The **Checks** column separates audio availability, exact iTunes metadata matching, and iTunes explicit-content advisories. Changes remain drafts until **Save & sync** or **Save & sync all** acknowledges them. A changed spreadsheet row produces a conflict rather than overwriting someone else's decision.

Deploy the updated `google-apps-script/Code.gs` as a new version of your existing web-app deployment **before using moderation saves**, restart the Flask service, then sync with Sheets. Use the five columns in the documented order; Notes is column five. Notes are visible to listeners through the moderation status information indicator (hover, focus and open, or tap); do not use them for private comments.

Both expandable iTunes tools support **Scan unchecked**, **Scan pending songs**, and **Rescan all songs**. Pending scans process only unchecked/failed songs awaiting moderation. Each row also has **Details / rescan** with individual metadata and explicit-rating scan buttons. Both checks share one lookup and update together. Completed results, including no-match/unknown results, persist across restarts and are shared by identical title/artist pairs across stations. Editing title or artist makes the old findings inapplicable; save the edit and scan the new identity. Individual rescans and Rescan all deliberately refresh results. Scans are paced and only one runs at a time; scans never approve, reject, or download a song.

Explicit advisories are **Explicit**, **Edited version**, **Not marked explicit**, **Conflicting versions**, **Rating unknown**, or **Search failed/unchecked**. They describe exact title/artist matches in the iTunes results, not analysis of the downloaded audio. Multiple conflicting ratings remain ambiguous; a missing rating is never treated as clean. Use the optional YouTube ID and preview to verify a recording. No paid lyrics service or API key is required.

### Sheets connection diagnostics

Run `python diagnose_sheets.py` in the same environment as the service for five read-only station-list requests and timing summaries. It does not change Sheets or the local catalog. HTTP, TLS, timeout, and invalid-response failures are reported without printing request URLs or payloads. An unsuccessful write response does not establish whether Google saved the changes; sync and review before resubmitting.

Requests supports `REQUESTS_CA_BUNDLE` for an administrator-provided CA bundle. TLS verification remains enabled. The simpler client is not proof that intermittent network failures are resolved.

Successful station writes update the local catalog from the returned playlist immediately. Station creation responses update the station list while retaining known playlists. Save & sync reloads local data only; it does not fetch Sheets again. Lazy request uploads also use their responses. Manual Sync with Sheets still fetches all stations to incorporate direct spreadsheet edits. The last full catalog-sync timestamp is not advanced by a partial station update.
