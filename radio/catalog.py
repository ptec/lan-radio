"""Translate self-contained station tabs to private runtime keys.

These keys never appear in the spreadsheet and are not required to edit it.
"""
import hashlib


def normalize_catalog(data):
    if data.get('schema_version') != 2 or not isinstance(data.get('stations'), list):
        raise ValueError('Deploy the station-tab Apps Script (schema version 2)')
    result = {'stations': [], 'songs': []}
    for station in data['stations']:
        if not isinstance(station, dict) or not isinstance(station.get('name'), str) or not station['name'].strip():
            raise ValueError('Invalid station name')
        name = station['name'].strip()
        key = hashlib.sha256(name.encode()).hexdigest()
        status = station.get('status')
        if status not in ('approved', 'pending') or not isinstance(station.get('songs'), list):
            raise ValueError('Invalid station playlist')
        result['stations'].append({'id': key, 'name': name, 'status': status})
        occurrences = {}
        for row in station['songs']:
            if not isinstance(row, dict) or any(not isinstance(row.get(f), str) or not row[f].strip() for f in ('title', 'artist', 'status')):
                raise ValueError('Invalid song row')
            if not isinstance(row.get('youtube_id', ''), str):
                raise ValueError('Invalid YouTube ID')
            song = {f: row.get(f, '').strip() for f in ('title', 'artist', 'status', 'youtube_id')}
            song['status'] = song['status'].lower()
            # Exact textual edits change identity as well as media selection.
            # Row positions are deliberately not identities: sorting is safe.
            content = hashlib.sha256((song['title'] + '\0' + song['artist'] + '\0' + song['youtube_id']).encode()).hexdigest()
            occurrences[content] = occurrences.get(content, 0) + 1
            song.update(id=f'{key}:{content}:{occurrences[content]}', station_id=key)
            result['songs'].append(song)
    return result
