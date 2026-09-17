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

Debug saves are sent in batches of up to 50 edits, followed by one catalog refresh. Each row receives its own success/error result; failed rows stay unsaved. Apps Script caches station reads within each batch and records successful delivery tokens for retries. Deploy the current `Code.gs` **before restarting the updated service**: all service-to-Sheets calls now use a form-encoded POST field named `payload` containing JSON. The updated script still accepts legacy JSON POST bodies, so older services can keep running during the script update. The token stays in the POST body, not the URL. This does not make the Apps Script response generally CORS-accessible; browsers continue to call Flask.

The debug page also offers an advisory **iTunes metadata review**. Start **Scan new / failed checks** or **Rescan all songs** to run a paced background scan (about one unique title/artist pair every five seconds). Exact means case-sensitive title and artist equality against up to 20 search results. Missing results and spelling/capitalization differences appear under **Needs metadata review**; connection or provider failures appear separately under **iTunes search failed**. Approval and playback are never changed. Results are saved locally and reused across stations; saved title/artist edits require a new scan. The scan continues if you close the page, but stops when the service shuts down; scan new checks to resume afterward. Filters and counts use the current catalog. iTunes may lack a valid song, so flags are suggestions for human review, not evidence that audio is wrong.

Set a separate `TESTING_PASSWORD` in `.env` and restart, then open `/debug` (for example, `http://radio.local/debug`). Sign in using that password; no username is needed. Sign-in lasts eight hours or until the service restarts. There is no homepage link. Password sign-in over HTTP is suitable only for a trusted LAN; use HTTPS on untrusted networks.

The page shows service uptime since app startup, cache size, download counts, queued requests, and last sync. Filter by station, search, and preview the actual cached MP3 with seeking without interrupting the broadcast. **Next cached song** steps through the filtered list. Previewing does not automatically identify recordings or approve songs. Refresh the catalog to update statistics and download states.

Deploy the updated `google-apps-script/Code.gs` web app before using **Save to spreadsheet**. Edits immediately update Title, Artist, and YouTube ID in the matching station tab and pull the catalog back. Approval is preserved. Changed recordings use a new cache key and approved songs join the normal download queue. Old cached files are retained, including audio used by other stations. Blank YouTube ID uses search; an 11-character ID selects a specific video. Automatic-search results from earlier downloads do not have a recorded source video ID.

Edits match the original row contents rather than row numbers or spreadsheet IDs. Changed, deleted, or duplicate rows require resolving the conflict in Sheets and syncing again. If saving succeeds but refreshing fails, use Sync now; do not assume the save failed. Google Sheets UI edits made at the exact same moment cannot be locked by Apps Script, so avoid editing the same row in both interfaces simultaneously.

## Google Sheet setup (deployment)

The station collection shows audio download progress separately from moderation status. Failed downloads show **Download failed** with a **Retry download** button for approved songs. Retry adds the recording back to the normal download queue, bypassing the automatic one-hour retry delay; it waits for the download worker's current batch to finish. Cached audio is shared across stations, so one retry also covers matching recordings on other stations.

Song requests offer iTunes suggestions while you type in either half of the combined title/artist field. Click a suggestion, or use the arrow keys and Enter, to fill both fields. Manual entry is always available. Searches are sent through the server to Apple; no API key is needed. Results are cached for ten minutes and shared across listeners, with a maximum of 20 provider searches per minute. Selecting a result still requires sending the request and normal administrator approval.

1. Create a Google Sheet. Open **Extensions → Apps Script** and paste `google-apps-script/Code.gs` into the editor.
2. In Apps Script **Project Settings → Script Properties**, add `SHEETS_TOKEN` with a long random secret. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Put the same value in `.env`.
3. Run `setup()` in the script editor and authorize it. This saves the spreadsheet ID, creates a hidden delivery-receipt tab, and formats existing station tabs. Keep the default visible tab for instructions or notes.
4. **Deploy → New deployment → Web app**. Execute as yourself; allow access to **Anyone**. Copy the `/exec` URL into `SHEETS_URL`. The service authenticates its POST body using the secret. If your Workspace policy disallows this deployment access, an administrator must enable it or you need a different authenticated bridge.
5. Start the service and request a station in the browser. After about five minutes (or immediately after clicking **Sync now**) a **`pending:Rock`** tab appears (using the requested name). Rename it to **`station:Rock`** to approve it. To reject it, delete the tab or rename it **`archived:Rock`**.
6. Click **Sync now** after approving the station, then request songs from it. Requests upload after about five minutes, or immediately with **Sync now**. Each request is appended directly to its station tab with `pending` status. Set desired songs to `approved`, then click **Sync now** again to bring approvals into the service and start downloads.

## Moderating directly in the spreadsheet

Each station is a self-contained playlist. **There are no station IDs, song IDs, or cross-sheet references for moderators to maintain.** The station name is the text after the tab prefix. For example, `station:Rock` and `station:Country` are two separate playlists. Each uses this layout:

| Title | Artist | Status | YouTube ID |
| --- | --- | --- | --- |
| Your song title | Performing artist | approved | optional video ID |

- **Add songs:** type or paste rows directly into the desired station tab. No script or app request is needed. Approve a song by setting its Status cell to `approved`.
- **Edit songs:** change Title, Artist, or YouTube ID in place. The next catalog sync replaces the old selection. A changed recording downloads if it is not already cached.
- **Remove songs:** delete a row, clear its contents, or set Status to `rejected`. Clearing either Title or Artist makes the row incomplete and removes it from playback until it is completed again. The service never writes its cached playlist back into the Sheet.
- **Reorder songs:** sort or move whole rows to organize the collection. Playback uses a shuffled rotation, so row order does not determine playback order or reset the current shuffle.
- **Move songs between stations:** cut/paste whole song rows into another station tab. There are no links to repair. Duplicate rows for the same cached recording share a single shuffle slot; app requests for an existing title/artist do not add a duplicate or override its moderation status.
- **Add a station manually:** create a tab named `station:Jazz`, then run **Radio moderation → Format station tabs** (reload the Sheet to see the menu). You can also duplicate a station tab and rename it. An empty tab receives the four headers and a Status dropdown. Creating a `station:` tab directly is itself administrator approval.
- **Rename a station:** rename `station:Rock` to `station:Classic Rock`. At the next sync, the old station disappears and the new name appears. Existing listeners must select it again; cached music is reused.
- **Disable/delete a station:** change its prefix to `pending:` to suspend it, rename it to `archived:` to remove it from the catalog while keeping its rows, or delete the tab. Its previous broadcast stops after sync. Existing listeners may hear a few seconds of already-buffered audio.

Keep **Title**, **Artist**, and **Status** as unique headers in row 1; capitalization and surrounding spaces do not matter. You can reorder columns and add Notes or other columns—the service ignores extras. The **YouTube ID** column is optional. Empty rows are ignored; blank or unrecognized statuses never grant approval. A malformed header pauses only the affected playlist and reports a warning in the app, rather than continuing stale approvals or blocking other stations' updates.

`YouTube ID` selects an external recording; it is not a link to another spreadsheet field. Leave it blank to search artist + title, or use an exact 11-character YouTube video ID. Automatic search may select a wrong version, so the optional ID lets a moderator correct it.

| Tab prefix | Administrative meaning |
| --- | --- |
| `station:` | Approved station; approved song rows may play |
| `pending:` | Requested/suspended station; no playback |
| `archived:` | Ignored by the service; preserve rejected/retired playlists here if desired |
| `metadata:` | Service bookkeeping only; not a playlist |

Unprefixed tabs are ignored, so you can keep instructions or scratch work in the same spreadsheet. Station request names are limited to 91 characters and exclude `[ ] * ? : /` and backslash. Avoid two live tabs with the same name after trimming whitespace. If pending and approved tabs have the same station name, the approved tab takes precedence and the app reports a warning.

**Changes appear after the next successful catalog sync.** Click **Sync now** after editing or moderating the Sheet. With no outbound requests, there is no automatic catalog polling, including at startup. A successful sync replaces the whole saved catalog, including deletions. Removed or edited songs are checked during playback. A failed sync retains the last successful catalog.

The hidden **`metadata:Request receipts`** tab contains delivery tokens, outcomes, and timestamps only. These tokens do not point to station tabs, rows, or cells. Keep it intact: receipts prevent a lost HTTP response and subsequent upload retry from recreating a song or station that a moderator has since deleted. Regular moderation happens entirely in playlist tabs. A genuinely new request may add a new pending row later. A stale song request targeting a removed/renamed station is marked undeliverable locally, without recreating the old tab; its count appears in the app and details are retained in SQLite's `rejected_requests` table.

## Upgrading the previous spreadsheet layout

1. Stop the service and back up the spreadsheet and `data/` directory.
2. Replace the Apps Script with this version. If you already have the old `Stations` and `Songs` tabs, run **`migrateLegacy()` once** in the script editor. It copies songs into independent station tabs, preserves approval status, and leaves both originals unchanged for review. Approved stations use `station:`, pending stations use `pending:`, and rejected stations use `archived:`. It validates target names before copying and refuses to overwrite existing tabs. If a run fails after some copies, inspect/remove only those partial new tabs before retrying.
3. Run `setup()` if you built the station tabs manually instead. Deploy a new Apps Script version at the existing deployment URL, then replace the service files and restart.
4. Confirm the new playlists in the app. The old `Stations`/`Songs` tabs are ignored and can be archived or deleted after review. Keep `data/cache`; recording cache keys have not changed. Previously queued song requests are translated to station names from the saved catalog before upload. A request whose original station can no longer be resolved is retained locally as undeliverable.

## HTTP bridge

All operations use authenticated HTTP POST. `{"token":"…","action":"catalog"}` returns `schema_version: 2` and a `stations` array; each station contains its name, status, and its own `songs` array (title, artist, status, youtube_id). No spreadsheet IDs or cross-sheet pointers are required in this response. `{"token":"…","action":"submit","requests":[...]}` accepts station requests with `name` and song requests with a readable `station` name, title, and artist. Each transport request includes a unique `id` used only for delivery receipts. The service derives private browser/runtime keys from the catalog; none are stored in moderation rows. GET exposes no catalog. After editing a deployed script, deploy a new version. See [Apps Script web apps](https://developers.google.com/apps-script/guides/web) and [Content Service](https://developers.google.com/apps-script/guides/content).

## Browsing songs and syncing

The left sidebar contains a scrollable station list with each station's current song and a **Tune in** button. Click a station name to open it in the main view without interrupting your current audio. The first available station is selected automatically; playback still requires a click. The receiver identifies the station you are actually listening to when you browse another one.

The main view shows **Now playing** and **Up next**. Up next previews the actual shuffled queue and only includes approved, cached audio. Refreshing the UI does not reshuffle it. It may change after downloads or catalog edits. Metadata describes the server broadcast and can lead audible playback by the client buffer delay.

Each station plays every distinct available recording once per shuffled cycle. The next cycle is shuffled again, with its first song chosen to differ from the last song of the previous cycle whenever at least two recordings are available. With only one playable recording, repetition is unavoidable. Newly approved/downloaded songs join the remaining cycle; deleted, unapproved, or unavailable recordings drop out. These updates do not restart the cycle or replay songs already consumed in it. A service restart or station rename starts a fresh rotation. Songs share a shuffle slot when their cache identity (normalized title, artist, and optional YouTube ID) matches.

The station collection lists all song rows, including rejected songs and locally queued requests, with search and status filters. **Request a song** opens an inline form above the list, automatically targeting the selected station; no scrolling to the bottom is needed. Song requests remain disabled for pending stations. The sidebar also retains **Request a station**. **Sync now**, sync status, and expandable error history live at the bottom of the sidebar. On narrow screens the sidebar becomes a compact area above the main view with a scrollable station list.

Uploaded requests show **Pending approval**, and local requests show **Waiting to sync**. Approved songs awaiting download show **Preparing audio**; rejected songs remain visible but never enter playback.

**Sync now** is available to all clients on the trusted LAN. The button schedules work in the background, uploads queued requests, then refreshes the catalog. Repeated clicks while queued/running are coalesced, and a global cooldown (30 seconds by default) limits subsequent manual syncs. Sync does not approve songs or stations. The header reports progress, the next queued sync time, errors, and the last successful catalog update.

Automatic sync uses the oldest queued request's creation time plus five minutes. New requests join that batch without postponing the deadline; creation times survive restarts. A backlog already overdue at startup syncs promptly. Existing legacy requests without timestamps begin their delay when first detected. The service drains up to 1,000 requests per cycle in batches of 100. Outstanding requests after a failure or during an ongoing cycle retry after another five minutes. When the outbound queue is empty, there are no background Sheets calls. If the upload succeeds but the catalog fetch fails, use **Sync now** to retry; an empty queue does not trigger a retry by itself.

On a fresh installation, click **Sync now** to load an existing Sheet. After manual moderation in the Sheet, click it again to fetch those changes. The browser's five-second UI refresh only reads the local service; it never calls Sheets.

The old `SYNC_SECONDS` and `REQUEST_SYNC_SECONDS` settings are no longer used. Existing `.env` files can keep them harmlessly, or replace them with the new settings from `.env.example`. Defaults already provide the requested five-minute behavior. No Apps Script redeployment is needed for these two features if the station-tab version is already deployed.

API additions: `GET /api/stations/<station_id>/songs` returns all song statuses and locally queued requests. `/api/stations` includes `now_playing` and `up_next` metadata. `POST /api/sync` with a JSON body (`{}`) schedules synchronization, returning 202, 429 during cooldown, or 503 when Sheets is not configured. `GET /api/health` includes sync progress/deadlines. These endpoints follow the existing trusted-LAN access model.

## Runtime behavior

### Diagnosing sync failures

The header and server console now report the underlying sync error: timeout, connection or certificate failure, HTTP status, non-JSON response, Apps Script rejection, or catalog validation failure. Expand **Recent sync failures** to see the last ten failed attempts, retained across successful syncs and service restarts. The same sanitized history is available as `recent_sync_failures` in `/api/health`. The token and request URLs are redacted.

If you change `.env`, restart `python run.py` so the running process loads the new values. For an Unauthorized error, compare SHEETS_TOKEN with the Apps Script Script Property. For a non-JSON response, verify the deployed `/exec` URL and web-app access settings. For a schema-version error, publish a new deployment version containing the current Code.gs. For timeouts or intermittent Google errors, retry **Sync now** and inspect Apps Script's Executions page if they recur. Do not disable TLS verification to work around certificate errors.

- New listener connections accumulate about two seconds of 128 kbps audio before the first response chunk is sent. This gives the browser a startup buffer to reduce initial stuttering. The app displays a buffering message while connecting. Tuning, switching stations, and reconnecting all use this buffer; afterward audio continues at the normal live cadence. This adds approximately two seconds of listening delay plus the browser's own buffering, without changing the shared station clock.
- Startup loads the saved catalog immediately without contacting Sheets. Automatic synchronization happens only when outbound requests are queued, after the configured delay; manual synchronization is always available when Sheets is configured. A failed upload does not block the catalog fetch in that sync cycle. Receipts deduplicate completed uploads even after moderator deletions. Writes to a playlist and its receipt are separate Sheets operations: an Apps Script interruption between them can leave an unreceipted write. Existing title/artist checks limit duplicates on retry, but this is not a transactional database.
- Approved songs download and convert concurrently in a separate Python process. The queue is built in station round-robin order: one song from each approved station, then the next song from each station, so clean-install startup brings every station online progressively. The default pool is `max(1, min(8, CPU count - 1))`; set `DOWNLOAD_WORKERS` to a positive value to override it (the service clamps overrides to 32). Each job uses its own yt-dlp and FFmpeg subprocess, while the bounded pool limits total resource use. yt-dlp searches YouTube; FFmpeg normalizes to stereo 44.1 kHz / 128 kbps MP3 with the bit reservoir disabled. This permits new listeners to decode from any complete frame. Files become visible atomically after validation. Failures retry after an hour and are logged; details are also stored in SQLite's `media` table. On a one-CPU host the default is one job. Jobs already running finish when the service stops.
- Each station runs continuously even with zero listeners. Cached MP3 frames are paced against a monotonic clock and fanned out in approximately 261 ms chunks. A late listener receives upcoming live frames, not the beginning of a playlist. A queue exceeding about two seconds disconnects the slow listener. Reconnect to live resets browser buffering. Stations with no playable content show as preparing; their stream returns 503.
- Browser/device buffers mean listeners may differ by several seconds. This is live radio, not synchronized multiroom audio. The displayed song describes the server broadcast and can lead audible playback by the buffer delay. Tracks may have small encoder-padding gaps. Service restarts restart station rotation; station changes take effect at track boundaries, while revocations are checked during playback after catalog sync.
- The cache deduplicates by normalized title/artist and optional video ID, across stations. Keep `data/` across restarts. It contains SQLite, complete MP3s, and transient downloads. No automatic eviction is performed. Stop the service before manually removing cached files. Unapproved audio is retained on disk but excluded from playback.
- Use **one service process** via `python run.py`; it starts Waitress with listener slots plus spare API threads. Do not use Flask's debug reloader or multiple WSGI workers. A file lock prevents duplicate runtimes using the same data directory. Default capacity is 24 listeners; each consumes a WSGI thread and approximately 128 kbps of server outbound bandwidth. This targets a small trusted LAN. API requests are limited to five per client IP per minute and 1,000 queued requests.
- Shutdown waits for the active download/conversion to finish (each command has a 15-minute timeout). Streaming threads stop immediately. If a download worker crashes unexpectedly, restart the service; existing cached broadcasts continue. This version does not supervise/restart that worker automatically.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8080` | LAN bind address and port |
| `DATA_DIR` | `data` beside run.py | Persistent storage; relative paths resolve from working directory |
| `SHEETS_URL` / `SHEETS_TOKEN` | empty | Apps Script deployment and shared secret |
| `REQUEST_SYNC_DELAY_SECONDS` | `300` | Delay after the oldest queued request, and delay between upload retries (minimum 5 seconds) |
| `MANUAL_SYNC_COOLDOWN_SECONDS` | `30` | Global minimum interval between sync starts requested by clients (minimum 1 second) |
| `MAX_LISTENERS` | `24` | Global active-stream limit |
| `FFMPEG` | `ffmpeg` | Executable name or absolute path |

Without Sheets configuration the UI runs and retains station requests locally, but no catalog is created automatically. `/api/health` exposes catalog-sync status, pending request count, and aggregate download state. No authentication is required on the listening/request UI. Keep it on a trusted LAN; do not port-forward it to the internet. If using a reverse proxy, disable buffering/compression for `/stream/`, allow long-lived responses, and preserve Host. The Sheets token is server-side only. Keep `.env` private.

## Verify

```sh
python -m unittest discover -s tests -v
node tests/test_apps_script.cjs
node tests/test_interface.cjs
```

Python tests exercise FFmpeg framing, live broadcasts, snapshot replacement, edits/deletions, station retirement, cache reuse on renames, request retries and API boundaries. Node tests simulate Sheets moderation: editing, deleting, sorting, moving rows, renaming/deleting tabs, column changes, receipt retries and migration. They do not require a Google account or YouTube downloads. Actual Sheets deployment and YouTube extraction require your configuration and network access.

Implementation uses Flask's [streaming response interface](https://flask.palletsprojects.com/en/stable/patterns/streaming/).
