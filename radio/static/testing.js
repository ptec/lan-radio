(() => {
  const $ = id => document.getElementById(id);
  let songs = [], stations = [], current = null, visible = [];
  const drafts = new Map();
  let busy = false;
  let scanTimer;
  function scanStatus(scan) {
    scan = scan || {running:false,completed:0,total:0,errors:0};
    const batch = scan.total ? ` ${scan.running ? 'Current' : 'Last'} scan: ${scan.completed} of ${scan.total} distinct title/artist lookups processed; ${scan.errors} failed.` : ' No scan running.';
    for (const [id, field, completedStates] of [
      ['review-status','state',['matched','review']],
      ['explicit-status','explicit_state',['explicit','cleaned','notExplicit','ambiguous','unknown']],
    ]) {
      const checked = songs.filter(song => completedStates.includes(song.metadata_review?.[field])).length;
      const failed = songs.filter(song => song.metadata_review?.[field] === 'error').length;
      const remaining = songs.length - checked;
      $(id).textContent = `Entire catalog: ${checked} of ${songs.length} songs checked; ${remaining} left to scan` +
        (failed ? ` (including ${failed} failed checks to retry)` : '') + '.' + batch;
    }
    const flagged = songs.filter(s => s.metadata_review?.state === 'review').length;
    $('review-status').textContent += ` ${flagged} songs need metadata review.`;
    for (const id of ['review-start','review-all','review-pending','explicit-start','explicit-all','explicit-pending']) $(id).disabled = scan.running;
    clearTimeout(scanTimer);
    if (scan.running) scanTimer = setTimeout(pollScan, 3000);
  }
  async function pollScan() {
    try {
      const result = await api('/api/admin/review');
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
    document.querySelectorAll('#songs input, #songs button, #songs select, #songs textarea').forEach(element => {
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
          const result = await api('/api/admin/edits', {edits:batch.map(([id,draft]) => ({id,original:draft.original,changes:draft.values}))});
          for (const [id,draft] of batch) {
            const reply = result.results.find(item => item.id === id);
            if (reply?.saved === true) { drafts.delete(id); saved++; }
            else errors.push(`${draft.values.title}: ${reply?.error || 'Save was not acknowledged'}`);
          }
        } catch(error) { errors.push('Batch failed: '+error.message); break; }
      }
      try { await load(); } catch(error) { errors.push('Could not reload local catalog: '+error.message); }
      message(`${saved} of ${entries.length} saved to Sheets. ${drafts.size} unsaved change(s) remain.` + (errors.length ? '\n'+errors.join('\n') : ' Catalog updated.'));
    } finally { setBusy(false); }
  }
  function preview(song) {
    current = song.id;
    $('preview-name').textContent = song.title + ' · ' + song.artist;
    $('preview').src = '/api/admin/audio/' + encodeURIComponent(song.id);
    $('preview').play().catch(() => message('Press Play in the preview player.'));
  }
  function render() {
    window.debugSuggestions?.close();
    const query = $('search').value.toLowerCase();
    const reviewSongs = [...songs, ...[...drafts.entries()].filter(([id]) => !songs.some(song => song.id === id)).map(([,draft]) => draft.song)];
    const counts = new Map(), sequence = new Map();
    for (const song of reviewSongs) {
      const number = (counts.get(song.station_id) || 0) + 1;
      counts.set(song.station_id, number); sequence.set(song.id, number);
    }
    const digits = Math.max(2, String(Math.max(0, ...counts.values())).length);
    $('sequence-heading').setAttribute('style', `width:calc(${digits}ch + 24px)`);
    visible = reviewSongs.filter(s => (!$('station').value || s.station_id === $('station').value) &&
      `${s.title} ${s.artist}`.toLowerCase().includes(query) &&
      ($('filter').value === 'all' || $('filter').value === s.status || $('filter').value === 'explicit' && ['explicit','ambiguous'].includes(s.metadata_review?.explicit_state) || $('filter').value === 'explicit-unknown' && s.metadata_review?.explicit_state === 'unknown' || $('filter').value === 'explicit-unchecked' && (!s.metadata_review?.explicit_state || s.metadata_review.explicit_state === 'unchecked') || ['cleaned','notExplicit'].includes($('filter').value) && $('filter').value === s.metadata_review?.explicit_state || $('filter').value === 'review' && s.metadata_review?.state === 'review' || $('filter').value === 'review-error' && s.metadata_review?.state === 'error' || $('filter').value === 'review-unchecked' && (!s.metadata_review || s.metadata_review.state === 'unchecked') || $('filter').value === 'failed' && s.download_status === 'failed' || $('filter').value === 'ready' && s.cached));
    $('result-count').textContent = `${visible.length} of ${songs.length} songs`;
    $('songs').replaceChildren(...visible.map((song, index) => {
      const card = document.createElement('tr');
      const number = document.createElement('td'); number.className = 'sequence-number';
      number.textContent = String(sequence.get(song.id)).padStart(digits, '0'); card.append(number);
      const station = document.createElement('td'); station.textContent = stations.find(s => s.id === song.station_id)?.name || '';
      card.append(station);
      const info = document.createElement('td'), stack = document.createElement('div'); stack.className = 'status-stack';
      const badge = document.createElement('span');
      badge.className = 'status-badge ' + (song.download_status === 'failed' ? 'failed' : song.cached ? 'ready' : '');
      badge.textContent = song.cached ? 'Cached' : song.download_status === 'failed' ? 'Download failed' : song.download_status === 'downloading' ? 'Downloading' : (song.status !== 'approved' || song.download_status === 'not_scheduled') ? 'Not scheduled' : 'Queued';
      stack.append(badge); info.append(stack);
      const reviewBadge = document.createElement('span'); reviewBadge.className = 'metadata-badge';
      const reviewState = song.metadata_review?.state || 'unchecked';
      reviewBadge.textContent = {review:'Needs review: no exact iTunes match',matched:'iTunes match',error:'iTunes search failed',unchecked:'Not scanned'}[reviewState];
      if (reviewState === 'review') reviewBadge.className += ' mismatch';
      stack.append(reviewBadge);
      const explicit = document.createElement('span'); explicit.className = 'metadata-badge';
      explicit.textContent = 'iTunes: ' + ({explicit:'Explicit',cleaned:'Edited version',notExplicit:'Not marked explicit',ambiguous:'Conflicting versions',unknown:'Rating unknown',error:'Search failed',unchecked:'Rating unchecked'}[song.metadata_review?.explicit_state || 'unchecked']);
      if (['explicit','ambiguous'].includes(song.metadata_review?.explicit_state)) explicit.className += ' mismatch';
      stack.append(explicit);
      const details = document.createElement('details'), summary = document.createElement('summary');
      summary.textContent = 'Details / rescan'; details.append(summary);
      const explanation = document.createElement('p'); explanation.textContent = 'iTunes catalog findings do not verify this audio. ' + (song.metadata_review?.checked_at ? 'Checked ' + new Date(song.metadata_review.checked_at*1000).toLocaleString() : 'Not checked for this title and artist.'); details.append(explanation);
      for (const candidate of song.metadata_review?.candidates || []) {
        const result = document.createElement('p'); result.textContent = `${candidate.title} · ${candidate.artist}${candidate.album ? ' — '+candidate.album : ''} (${candidate.explicitness || 'rating unknown'})`; details.append(result);
      }
      for (const [tool, label] of [['metadata','Rescan metadata'],['explicit','Rescan explicit rating']]) {
        const scan = document.createElement('button'); scan.type = 'button'; scan.textContent = label;
        scan.onclick = () => startScan('song',tool,song.id); details.append(scan);
      }
      stack.append(details);
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
          drafts.set(song.id, {values, song, original: previous?.original || Object.fromEntries(['title','artist','status','youtube_id','notes'].map(k => [k,song[k] || '']))});
        }
        else drafts.delete(song.id);
        card.className = ((dirty ? 'dirty ' : '') + (reviewState === 'review' ? 'needs-review' : '')).trim();
        unsaved.textContent = dirty ? 'Unsaved changes' : '';
        if (inputs.notes) { noteSummary.textContent = inputs.notes.value ? '\u24d8 Notes' : 'Add notes'; noteSummary.title = inputs.notes.value || 'Notes are visible to listeners'; decision.title = inputs.notes.value || '';  }
        if (inputs.title.value !== song.title || inputs.artist.value !== song.artist) { reviewBadge.textContent = 'Metadata: outdated — save and rescan'; explicit.textContent = 'iTunes rating: outdated'; } else { reviewBadge.textContent = {review:'Needs review: no exact iTunes match',matched:'iTunes match',error:'iTunes search failed',unchecked:'Not scanned'}[reviewState]; explicit.textContent = 'iTunes: ' + ({explicit:'Explicit',cleaned:'Edited version',notExplicit:'Not marked explicit',ambiguous:'Conflicting versions',unknown:'Rating unknown',error:'Search failed',unchecked:'Rating unchecked'}[song.metadata_review?.explicit_state || 'unchecked']); }
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
      const moderation = document.createElement('td'); moderation.className = 'moderation-cell';
      const decision = document.createElement('select'); decision.setAttribute('aria-label','Moderation for '+song.title);
      for (const value of ['pending','approved','rejected']) decision.append(new Option(value === 'rejected' ? 'Not approved' : value[0].toUpperCase()+value.slice(1),value));
      decision.value = drafts.get(song.id)?.values.status ?? song.status; decision.onchange = changed; inputs.status = decision;
      decision.setAttribute('form',form.id); moderation.append(decision);
      const noteDetails = document.createElement('details'); noteDetails.className = 'moderator-notes';
      const noteSummary = document.createElement('summary'); noteSummary.textContent = song.notes ? '\u24d8 Notes' : 'Add notes';
      noteSummary.title = song.notes || 'Notes are visible to listeners';
      const notes = document.createElement('textarea'); notes.maxLength = 2000; notes.rows = 3;
      notes.value = drafts.get(song.id)?.values.notes ?? song.notes ?? ''; notes.setAttribute('aria-label','Public moderator notes for '+song.title);
      notes.setAttribute('form',form.id); notes.oninput = changed; inputs.notes = notes;
      noteDetails.append(noteSummary,notes); moderation.append(noteDetails);
      const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Save & sync';
      save.setAttribute('aria-label', 'Save and sync ' + song.title);
      form.append(play, save);
      changed();
      window.debugSuggestions?.attach(inputs, changed);
      form.onsubmit = async event => {
        event.preventDefault(); await saveChanges([song.id]);
      };
      const controls = document.createElement('td'); controls.className = 'row-controls'; controls.append(form, unsaved);
      card.append(moderation, info, controls);
      if (song.download_status === 'failed' && song.status === 'approved') {
        const retry = document.createElement('button'); retry.textContent = 'Retry download';
        retry.onclick = async () => { retry.disabled = true; try { await api(`/api/stations/${encodeURIComponent(song.station_id)}/songs/${encodeURIComponent(song.id)}/retry`, {}); await load(); } catch(e) { message(e.message); } finally { retry.disabled = false; } };
        controls.append(retry);
      }
      return card;
    }));
    if (!visible.length) {
      const row = document.createElement('tr'), cell = document.createElement('td');
      cell.colSpan = 8; cell.textContent = 'No matching songs.'; row.append(cell); $('songs').append(row);
    }
  }
  async function playbackDiagnostics() {
    if (!$('playback-diagnostics').open) return;
    try {
      const result = await api('/api/admin/playback');
      $('playback-status').textContent = result.stations.map(s =>
        `${stations.find(station => station.id === s.station_id)?.name || s.station_id}: ${s.thread_alive ? 'running' : 'STOPPED'}\n` +
        `Listeners: ${s.listeners} | Largest queue: ${s.max_queue_chunks}/${s.queue_capacity_chunks} chunks\n` +
        `Slow disconnects: ${s.slow_disconnects} | Late chunks: ${s.late_chunks} | Worst delay: ${s.max_lateness_ms} ms\n` +
        `Last late chunk: ${s.last_late_at ? new Date(s.last_late_at*1000).toLocaleString() : 'Never'} | Cache errors: ${s.cache_errors}`
      ).join('\n\n') || 'No active stations.';
    } catch(error) { $('playback-status').textContent = 'Diagnostics unavailable: '+error.message; }
  }
  $('playback-diagnostics').ontoggle = playbackDiagnostics;
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
  function refreshDownloadRows(data) {
    // Do not replace a focused editor or interrupt a save. The next poll will
    // catch up; drafts are retained by render() when rows do need rebuilding.
    const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
    if (busy || editing) return;

    const latest = new Map(data.songs.map(song => [song.id, song]));
    let changed = false;
    for (const song of songs) {
      const update = latest.get(song.id);
      if (!update) continue;
      if (song.download_status !== update.download_status || song.cached !== update.cached) {
        song.download_status = update.download_status;
        song.cached = update.cached;
        changed = true;
      }
    }
    // This also reevaluates the Failed downloads filter and Retry buttons.
    if (changed) render();
  }

  async function refreshStats() {
    const version = ++statsVersion;
    await playbackDiagnostics();
    try {
      const data = await api('/api/admin');
      if (version === statsVersion) { renderStats(data); refreshDownloadRows(data); }
    } catch(error) {
      if (version === statsVersion) $('stats-updated').textContent = 'Statistics refresh failed: ' + error.message + ' Retrying?';
    } finally { setTimeout(refreshStats, 5000); }
  }
  async function load() {
    ++statsVersion;
    const data = await api('/api/admin'); songs = data.songs; stations = data.stations;
    const selection = $('station').value;
    $('station').replaceChildren(new Option('All stations',''), ...stations.map(s => new Option(s.name,s.id)));
    $('station').value = stations.some(s => s.id === selection) ? selection : '';
    renderStats(data);
    render();
    scanStatus(data.review_scan);
  }
  async function startScan(scope, tool, id) {
    if (id && drafts.has(id)) { message('Save this song before scanning its updated details.'); return; }
    try { const result = await api('/api/admin/review',{scope,tool,id}); scanStatus(result.scan); await pollScan(); }
    catch(e) { message('Could not start scan: '+e.message); }
  }
  for (const tool of ['metadata','explicit']) {
    const prefix = tool === 'metadata' ? 'review' : 'explicit';
    for (const [suffix,scope] of [['start','unchecked'],['pending','pending'],['all','all']]) $(prefix+'-'+suffix).onclick = () => startScan(scope,tool);
  }
  $('explicit-refresh').onclick = async () => { if (busy) return; $('station').value = ''; $('search').value = ''; $('filter').value = 'explicit'; render(); await pollScan(); };
  $('review-refresh').onclick = async () => { if (busy) return; $('station').value = ''; $('search').value = ''; $('filter').value = 'review'; render(); await pollScan(); };
  $('save-all').onclick = () => saveChanges([...drafts.keys()]);
  for (const [id,mode] of [['cache-unused','unused'],['cache-all','all']]) $(id).onclick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      message('Checking cache files…');
      const plan = await api('/api/admin/cache', {mode});
      const warning = mode === 'all' ? 'This resets downloads and rebuilds approved songs. Listening may be interrupted.' : 'Only files not referenced by the local catalog will be removed.';
      if (!window.confirm(`Delete ${plan.files} cached audio files (${(plan.bytes/1048576).toFixed(1)} MB)?\n${warning}`)) { message('Cache cleanup cancelled.'); return; }
      if (mode === 'all') { $('preview').pause(); $('preview').removeAttribute('src'); $('preview').load(); }
      message('Removing cached audio…');
      const result = await api('/api/admin/cache', {mode,confirm:true});
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
