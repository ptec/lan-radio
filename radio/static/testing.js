(() => {
  const $ = id => document.getElementById(id);
  let songs = [], stations = [], current = null, visible = [];
  const drafts = new Map();
  let busy = false;
  let scanTimer;
  function scanStatus(scan) {
    if (!scan) return;
    const flagged = songs.filter(s => s.metadata_review?.state === 'review').length;
    $('review-status').textContent = `${scan.running ? 'Scanning' : 'Scan idle'}: ${scan.completed} / ${scan.total} recordings. ${flagged} catalog rows need review. ${scan.errors} search errors.`;
    $('review-start').disabled = scan.running;
    $('review-all').disabled = scan.running;
    clearTimeout(scanTimer);
    if (scan.running) scanTimer = setTimeout(pollScan, 3000);
  }
  async function pollScan() {
    try {
      const result = await api('/api/debug/review');
      songs.forEach(song => { song.metadata_review = result.songs[song.id] || {state:'unchecked'}; });
      scanStatus(result.scan);
      // Do not rebuild focused inputs while someone is correcting a row.
      if (!busy && !document.activeElement?.closest('#songs')) render();
    } catch(e) { $('review-status').textContent = 'Could not update scan status: '+e.message+' Use Show scan results to retry.'; }
  }
  function updateSaveAll() {
    $('save-all').textContent = `Save & sync all (${drafts.size})`;
    $('save-all').disabled = busy || !drafts.size;
  }
  function setBusy(value) {
    busy = value;
    for (const id of ['refresh','sync','station','filter','search']) $(id).disabled = value;
    document.querySelectorAll('#songs input, #songs button').forEach(element => {
      if (value) { element.dataset.wasDisabled = String(element.disabled); element.disabled = true; }
      else if (element.dataset.wasDisabled !== undefined) { element.disabled = element.dataset.wasDisabled === 'true'; delete element.dataset.wasDisabled; }
    });
    window.debugSuggestions?.close(); updateSaveAll();
  }
  async function api(url, body) {
    const response = await fetch(url, body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Request failed');
    return data;
  }
  function message(text) { $('message').textContent = text; }
  async function saveChanges(ids) {
    if (busy) return;
    const entries = ids.filter(id => drafts.has(id)).map(id => [id, drafts.get(id)]);
    if (!entries.length) { message('No unsaved changes.'); return; }
    const invalid = entries.find(([,d]) => !d.values.title.trim() || !d.values.artist.trim() || d.values.title.length > 200 || d.values.artist.length > 200 || (d.values.youtube_id.trim() && !/^[A-Za-z0-9_-]{11}$/.test(d.values.youtube_id.trim())));
    if (invalid) { message(`Check title, artist and YouTube ID for "${invalid[1].values.title}". Nothing was saved.`); return; }
    setBusy(true);
    let saved = 0; const errors = [];
    try {
      for (let offset = 0; offset < entries.length; offset += 50) {
        const batch = entries.slice(offset, offset + 50);
        message(`Saving batch ${Math.floor(offset/50)+1} of ${Math.ceil(entries.length/50)} (${batch.length} songs)...`);
        try {
          const result = await api('/api/debug/edits', {edits:batch.map(([id,draft]) => ({id,request_id:draft.requestId,original:draft.original,changes:draft.values}))});
          for (const [id,draft] of batch) {
            const reply = result.results.find(item => item.id === id);
            if (reply?.saved === true) { drafts.delete(id); saved++; }
            else errors.push(`${draft.values.title}: ${reply?.error || 'Save was not acknowledged'}`);
          }
        } catch(error) { errors.push('Batch failed: '+error.message); break; }
      }
      if (saved) {
        message(`${saved} saved to Sheets. Refreshing the catalog…`);
        try { await api('/api/debug/refresh', {}); }
        catch(error) { errors.push('Edits were saved, but Sheets refresh failed: '+error.message+' Use Sync with Sheets to retry.'); }
      }
      try { await load(); } catch(error) { errors.push('Could not reload local catalog: '+error.message); }
      message(`${saved} of ${entries.length} saved to Sheets. ${drafts.size} unsaved change(s) remain.` + (errors.length ? '\n'+errors.join('\n') : ' Catalog updated.'));
    } finally { setBusy(false); }
  }
  function preview(song) {
    current = song.id;
    $('preview-name').textContent = song.title + ' · ' + song.artist;
    $('preview').src = '/api/debug/audio/' + encodeURIComponent(song.id);
    $('preview').play().catch(() => message('Press Play in the preview player.'));
  }
  function render() {
    window.debugSuggestions?.close();
    const query = $('search').value.toLowerCase();
    const reviewSongs = [...songs, ...[...drafts.entries()].filter(([id]) => !songs.some(song => song.id === id)).map(([,draft]) => draft.song)];
    visible = reviewSongs.filter(s => (!$('station').value || s.station_id === $('station').value) &&
      `${s.title} ${s.artist}`.toLowerCase().includes(query) &&
      ($('filter').value === 'all' || $('filter').value === 'review' && s.metadata_review?.state === 'review' || $('filter').value === 'review-error' && s.metadata_review?.state === 'error' || $('filter').value === 'review-unchecked' && (!s.metadata_review || s.metadata_review.state === 'unchecked') || $('filter').value === 'failed' && s.download_status === 'failed' || $('filter').value === 'ready' && s.cached));
    $('result-count').textContent = `${visible.length} of ${songs.length} songs`;
    $('songs').replaceChildren(...visible.map((song, index) => {
      const card = document.createElement('tr');
      const station = document.createElement('td'); station.textContent = stations.find(s => s.id === song.station_id)?.name || '';
      card.append(station);
      const info = document.createElement('td'), stack = document.createElement('div'); stack.className = 'status-stack';
      const badge = document.createElement('span');
      badge.className = 'status-badge ' + (song.download_status === 'failed' ? 'failed' : song.cached ? 'ready' : '');
      badge.textContent = song.cached ? 'Cached' : song.download_status === 'failed' ? 'Download failed' : song.download_status === 'downloading' ? 'Downloading' : 'Queued';
      const status = document.createElement('span'); status.className = 'status-secondary'; status.textContent = song.status;
      stack.append(badge, status); info.append(stack);
      const reviewBadge = document.createElement('span'); reviewBadge.className = 'metadata-badge';
      const reviewState = song.metadata_review?.state || 'unchecked';
      reviewBadge.textContent = {review:'Needs review: no exact iTunes match',matched:'iTunes match',error:'iTunes search failed',unchecked:'Not scanned'}[reviewState];
      if (reviewState === 'review') reviewBadge.className += ' mismatch';
      stack.append(reviewBadge);
      const play = document.createElement('button'); play.type = 'button'; play.textContent = 'Preview'; play.disabled = !song.cached; play.onclick = () => preview(song);
      play.setAttribute('aria-label', 'Preview ' + song.title);
      const form = document.createElement('form'); form.id = 'edit-song-' + index;
      const inputs = {};
      const unsaved = document.createElement('span'); unsaved.className = 'unsaved'; unsaved.setAttribute('role', 'status');
      function changed() {
        const values = Object.fromEntries(Object.entries(inputs).map(([key,input]) => [key,input.value]));
        const dirty = Object.keys(values).some(key => values[key] !== (song[key] || ''));
        if (dirty) {
          const previous = drafts.get(song.id);
          const requestId = previous && JSON.stringify(previous.values) === JSON.stringify(values) ? previous.requestId : `${Date.now()}-${Math.random()}`;
          drafts.set(song.id, {values, song, requestId, original: previous?.original || Object.fromEntries(['title','artist','status','youtube_id'].map(k => [k,song[k] || '']))});
        }
        else drafts.delete(song.id);
        card.className = ((dirty ? 'dirty ' : '') + (reviewState === 'review' ? 'needs-review' : '')).trim();
        unsaved.textContent = dirty ? 'Unsaved changes' : '';
        updateSaveAll();
      }
      for (const [key, label] of [['title','Title'],['artist','Artist'],['youtube_id','YouTube ID']]) {
        const wrapper = document.createElement('td');
        const input = document.createElement('input'); input.name = key; input.value = song[key] || ''; input.maxLength = key === 'youtube_id' ? 11 : 200; input.required = key !== 'youtube_id';
        input.value = drafts.get(song.id)?.values[key] ?? input.value;
        inputs[key] = input;
        input.oninput = changed;
        input.setAttribute('form', form.id); input.setAttribute('aria-label', label + ' for ' + song.title);
        if (key === 'youtube_id') input.pattern = '[A-Za-z0-9_-]{11}';
        wrapper.append(input); card.append(wrapper);
      }
      const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Save & sync';
      save.setAttribute('aria-label', 'Save and sync ' + song.title);
      form.append(play, save);
      changed();
      window.debugSuggestions?.attach(inputs, changed);
      form.onsubmit = async event => {
        event.preventDefault(); await saveChanges([song.id]);
      };
      const controls = document.createElement('td'); controls.className = 'row-controls'; controls.append(form, unsaved);
      card.append(info, controls);
      if (song.download_status === 'failed' && song.status === 'approved') {
        const retry = document.createElement('button'); retry.textContent = 'Retry download';
        retry.onclick = async () => { retry.disabled = true; try { await api(`/api/stations/${encodeURIComponent(song.station_id)}/songs/${encodeURIComponent(song.id)}/retry`, {}); await load(); } catch(e) { message(e.message); } finally { retry.disabled = false; } };
        controls.append(retry);
      }
      return card;
    }));
    if (!visible.length) {
      const row = document.createElement('tr'), cell = document.createElement('td');
      cell.colSpan = 6; cell.textContent = 'No matching songs.'; row.append(cell); $('songs').append(row);
    }
  }
  let statsVersion = 0;
  function renderStats(data) {
    const {songs, stations} = data;
    const hours = Math.floor(data.uptime_seconds / 3600), minutes = Math.floor(data.uptime_seconds % 3600 / 60);
    const metrics = [
      ['Uptime', `${hours}h ${minutes}m ${data.uptime_seconds % 60}s`, 'Since service start'],
      ['Catalog', songs.length, `${stations.length} stations`],
      ['Audio cache', data.cache_files, `${(data.cache_bytes/1048576).toFixed(1)} MB on disk`],
      ['Downloading', songs.filter(s => s.download_status === 'downloading').length, 'Current catalog songs'],
      ['Failed', songs.filter(s => s.download_status === 'failed').length, 'Current catalog songs'],
      ['Requests', data.pending_requests, 'Waiting to sync'],
    ];
    $('stats').replaceChildren(...metrics.map(([label, value, detail]) => {
      const tile = document.createElement('div'); tile.className = 'metric';
      const name = document.createElement('span'), count = document.createElement('strong'), note = document.createElement('small');
      name.textContent = label; count.textContent = value; note.textContent = detail;
      tile.append(name, count, note); return tile;
    }));
    $('sync-detail').textContent = 'Last catalog sync: ' + (data.last_sync ? new Date(data.last_sync*1000).toLocaleString() : 'Never') + (data.sync_error ? ' ? ' + data.sync_error : '');
    $('stats-updated').textContent = 'Updated ' + new Date().toLocaleTimeString() + ' ? refreshes every 5 seconds';
  }
  async function refreshStats() {
    const version = ++statsVersion;
    try {
      const data = await api('/api/debug');
      if (version === statsVersion) renderStats(data);
    } catch(error) {
      if (version === statsVersion) $('stats-updated').textContent = 'Statistics refresh failed: ' + error.message + ' Retrying?';
    } finally { setTimeout(refreshStats, 5000); }
  }
  async function load() {
    ++statsVersion;
    const data = await api('/api/debug'); songs = data.songs; stations = data.stations;
    const selection = $('station').value;
    $('station').replaceChildren(new Option('All stations',''), ...stations.map(s => new Option(s.name,s.id)));
    $('station').value = stations.some(s => s.id === selection) ? selection : '';
    renderStats(data);
    render();
    scanStatus(data.review_scan);
  }
  for (const [id, force] of [['review-start',false],['review-all',true]]) $(id).onclick = async () => {
    $(id).disabled = true;
    try { const result = await api('/api/debug/review',{force}); scanStatus(result.scan); await pollScan(); }
    catch(e) { $('review-status').textContent = 'Could not start scan: '+e.message; $(id).disabled = false; }
  };
  $('review-refresh').onclick = async () => { if (busy) return; $('station').value = ''; $('search').value = ''; $('filter').value = 'review'; render(); await pollScan(); };
  $('save-all').onclick = () => saveChanges([...drafts.keys()]);
  for (const [id,mode] of [['cache-unused','unused'],['cache-all','all']]) $(id).onclick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      message('Checking cache files…');
      const plan = await api('/api/debug/cache', {mode});
      const warning = mode === 'all' ? 'This resets downloads and rebuilds approved songs. Listening may be interrupted.' : 'Only files not referenced by the local catalog will be removed.';
      if (!window.confirm(`Delete ${plan.files} cached audio files (${(plan.bytes/1048576).toFixed(1)} MB)?\n${warning}`)) { message('Cache cleanup cancelled.'); return; }
      if (mode === 'all') { $('preview').pause(); $('preview').removeAttribute('src'); $('preview').load(); }
      message('Removing cached audio…');
      const result = await api('/api/debug/cache', {mode,confirm:true});
      await load(); message(result.message + (mode === 'all' ? ' Approved songs will download again through the normal queue.' : ''));
    } catch(e) { message('Cache cleanup failed: '+e.message); }
    finally { setBusy(false); }
  };
  $('refresh').onclick = async () => {
    if (busy) return; setBusy(true); message('Reloading the server’s local catalog…');
    try { await load(); message(`Local catalog reloaded: ${songs.length} songs. Sheets was not contacted. ${drafts.size} unsaved change(s) preserved.`); }
    catch(e) { message('Reload failed: '+e.message); } finally { setBusy(false); }
  };
  $('sync').onclick = async () => {
    if (busy) return; setBusy(true); message('Requesting a sync with Google Sheets…');
    try {
      await api('/api/sync',{});
      for (let attempt = 0; attempt < 150; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        const health = await api('/api/health');
        if (!health.sync.running && !health.sync.requested) {
          await load();
          message((health.sync_error ? 'Sync finished with errors: '+health.sync_error : 'Sheets sync complete. Catalog reloaded.') + ` ${drafts.size} unsaved edit(s) preserved; use Save & sync to submit them.`);
          return;
        }
        message(health.sync.running ? 'Syncing with Sheets… queued requests are uploaded, then the catalog is downloaded.' : 'Sync queued. Waiting for the server…');
      }
      message('Sync is still running. Reload the local catalog later to check its status.');
    } catch(e) { message('Sync failed: '+e.message); } finally { setBusy(false); }
  };
  for (const id of ['station','filter']) $(id).onchange = render;
  $('search').oninput = render;
  $('preview').onerror = () => message('Preview unavailable. Refresh to check whether the recording changed.');
  load().catch(e => message(e.message)).finally(() => setTimeout(refreshStats, 5000));
})();
