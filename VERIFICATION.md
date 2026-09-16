# Verification

## Plain-language listening interface

Player control checks also pass for the mobile station drawer opening, closing on selection, moving back to the sidebar at desktop widths, volume adjustment, mute, and unmuting from zero volume. Playback messages are positioned outside the layout to avoid shifting the player or song view. Visual browser verification remains outstanding.

The interface interaction checks pass for Play/Stop, releasing the stream when stopped, resuming the listening station while browsing another, reconnecting without changing the browsed station, and recovering the Play button after a stream error. Existing station browsing, filtering, requests, tuning, and sync checks pass. Song suggestion checks also pass. The user guide matches the new Listen and Reconnect labels.

Desktop/mobile visual rendering and physical audio playback have not been verified for this interface update.

## Parallel, fair download startup

The download worker now derives a bounded default pool from CPU count, supports `DOWNLOAD_WORKERS`, and queues uncached approved songs round-robin by station. Tests verify fairness, cached/unapproved filtering, stable station order, and worker-count overrides. The full Python suite passes after this change.

## Shuffled station rotation

All 36 Python tests passed. Shuffle tests exercise complete cycles and non-repeating boundaries over 30 random seeds for 2-, 3-, and 10-song libraries, repeated previews, additions/removals/reordering, duplicate recordings, and empty/single-song stations. The station-level up-next test verifies that only cached, approved songs enter the same queue used for playback.

## Sync diagnostics (September 15, 2026)

A read-only catalog request using the active project's virtual environment and .env succeeded: HTTP 200, schema version 2, two stations, 171 songs, no warnings. Normalization and saving to an isolated SQLite database passed. The existing running service reported no current sync error. The earlier failure could not be reproduced or attributed because the previous code discarded exception details.

Added safe error reporting and persistent last-ten failure history. Tests cover network error categories, HTTP/non-JSON responses, Apps Script rejection details, secret redaction, and retaining failure history after success/restart.

## Startup buffering (September 15, 2026)

All 26 Python tests passed. New checks confirm the first response waits for approximately two seconds of encoded audio, preserves chunk order, continues without repeated buffering, discards incomplete startup data on disconnection, and independently buffers each new connection. Browser JavaScript syntax was checked. Actual audible startup behavior on LAN clients remains to be verified.

Verified in the build environment on September 11, 2026:

- Thirteen Python tests cover FFmpeg frame parsing, broadcast pacing, late joins, approval revocation, complete catalog replacement, row edits/deletions/reordering/duplicates, station retirement on rename/deletion, cache reuse, durable request retries, migration of queued requests, undeliverable requests, API approval enforcement, and listener cleanup.
- Nine Apps Script scenarios under a mocked Sheet runtime cover independent station tabs, edits/deletes/sorts/moves, renames/deletions of tabs, column reordering, incomplete rows, malformed headers, pending-only requests, receipt persistence after deletion, stale request rejection, and conversion from the legacy layout.
- The initial version's Waitress HTTP smoke test covered homepage, health and request persistence. The revised API is covered by Flask test-client checks; a real Google deployment has not been exercised.

The build sandbox requires an ACL adaptation for Python temporary directories; the test harness applied that adaptation without changing application behavior. Dependencies were downloaded from PyPI into the workspace after pip's temporary-directory creation failed.

Not verified: a deployed Google Apps Script against a real Sheet; real YouTube extraction; audible browser playback across multiple physical LAN devices. These require your Sheet configuration and target environment. Automated audio tests use a generated sine wave.

## Song browsing and on-demand synchronization

All 23 Python tests passed after this update. Ten new tests cover approved/pending/local song visibility, pending stations, deletion visibility, requests beyond the first batch, idle/startup behavior, five-minute batching without deadline postponement, restart persistence, manual sync coalescing/cooldown, multi-batch upload ordering, failure retries, and cross-origin/configuration checks. Existing audio and moderation tests also pass. The new browser JavaScript passes Node's syntax check.

No Google account was contacted during these tests. The active .env and cached data were preserved. Browser rendering and a real Sheets sync still need verification in the configured runtime.

## Station-focused interface overhaul

All 31 Python tests passed, including up-next rotation, wraparound, and skipping uncached/unapproved songs. Node DOM interaction checks passed for initial station selection, up-next display, browsing without changing audio, request targeting, search/status filters, tuning, and manual sync. An isolated HTTP preview served the new page and stylesheet successfully. JavaScript syntax passed.

Browser automation reported no available browser, so desktop/mobile visual rendering has not been verified. The isolated preview used sample data and did not contact Google or change the live catalog.
