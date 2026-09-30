"""Small HTTP client for the spreadsheet's four endpoints."""
from __future__ import annotations

import json
import os
import requests


class GasError(RuntimeError):
    pass


def request(q, url=None):
    url = url or os.getenv("SHEETS_URL")
    if not url:
        raise GasError("Google Sheets is not configured")
    action = q.get("action")
    send = requests.get if action in ("getStations", "getStation") else requests.post
    try:
        response = send(url, params={"q": json.dumps(q)}, timeout=(10, 45))
        if not response.ok:
            raise GasError(f"{action}: Google returned HTTP {response.status_code}. No success response was received.")
        data = response.json()
    except requests.exceptions.SSLError:
        raise GasError(f"{action}: TLS connection failed. Check the server's network and trusted certificates.") from None
    except requests.exceptions.Timeout:
        raise GasError(f"{action}: Google did not respond in time. Try syncing again.") from None
    except requests.exceptions.RequestException:
        raise GasError(f"{action}: Could not connect to Google.") from None
    except ValueError:
        raise GasError(f"{action}: Google returned a non-JSON response. Check the deployed /exec URL.") from None
    if not isinstance(data, dict) or data.get("ok") is not True:
        # Do not expose raw remote errors containing URLs or query data.
        raise GasError(f"{action}: Apps Script rejected the request. Check its Executions log.")
    if not isinstance(data.get("content"), list):
        raise GasError(f"{action}: Expected a list in the response content.")
    return data["content"]


def gas_get_stations(url=None):
    return request({"action": "getStations"}, url)


def gas_get_station(station_id, url=None):
    return request({"action": "getStation", "stationId": station_id}, url)


def gas_create_station(station_id, url=None):
    return request({"action": "createStation", "stationId": station_id}, url)


def gas_update_station(station_id, state, url=None):
    return request({"action": "updateStation", "stationId": station_id, "state": state}, url)


def key(song):
    return f"{song.get('title', '')}:{song.get('artist', '')}"


def diff(old_song, new_song):
    return {field: new_song[field] for field in
            ("title", "artist", "youtube_id", "status", "notes")
            if field in new_song and new_song[field] is not None
            and new_song[field] != old_song.get(field)}
