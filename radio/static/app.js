const $ = selector => document.querySelector(selector);
let stations = [], selected = null, tuned = null, songs = [], paused = false;
let connecting = false, tuneVersion = 0, songVersion = 0, refreshing = false;
const cards = new Map();
async function api(url, options) {
  const response = await fetch(url, {cache:'no-store', ...options});
  const body = await response.json();
  if (!response.ok) throw Error(body.error || 'Request failed');
  return body;
}
function selectedStation() { return stations.find(s => s.id === selected); }
function renderMain() {
  const s = selectedStation();
  $('#station-title').textContent = s?.name || 'Choose a station';
  $('#station-description').textContent = s ? s.status === 'pending' ? 'This station is awaiting approval.' : `${s.ready} songs available` : 'Choose a station from the list.';
  $('#station-badge').textContent = s?.status === 'pending' ? 'Pending' : s ? 'Live radio' : 'Staff Radio';
  $('#now-title').textContent = s?.now_playing?.title || 'Waiting for music';
  $('#now-artist').textContent = s?.now_playing?.artist || '';
  $('#next-title').textContent = s?.up_next?.title || 'Nothing queued yet';
  $('#next-artist').textContent = s?.up_next?.artist || '';
  $('#tune').disabled = !s?.now_playing || s.status !== 'approved';
  $('#tune').textContent = tuned === selected && tuned && !paused ? 'Listening' : 'Listen';
  if (tuned === selected && tuned && !paused) $('#tune').disabled = true;
  $('#request-toggle').disabled = !s || s.status !== 'approved';
  $('#song input[name="station_id"]').value = selected || '';
  $('#song button').disabled = !s || s.status !== 'approved';
  $('#listening').textContent = tuned ? stations.find(s => s.id === tuned)?.name || 'Station no longer available' : 'Not listening';
  const playing = stations.find(station => station.id === tuned)?.now_playing;
  $('#playing-song').textContent = playing ? `${playing.title} · ${playing.artist}` : 'Choose a station';
  $('#play-stop').setAttribute('data-playing', String(!!tuned && !paused));
  $('#listening-label').textContent = connecting ? 'Connecting to:' : paused ? 'Stopped:' : 'Listening to:';
  $('#play-stop').textContent = tuned && !paused ? 'Stop' : 'Play';
  $('#play-stop').disabled = !(tuned && !paused) && !stations.some(station => station.id === (tuned || selected) && station.now_playing);
  $('#live').disabled = !stations.some(s => s.id === tuned && s.now_playing);
}
function selectStation(id) {
  if (selected === id) return;
  selected = id; songs = []; songVersion++;
  $('#song-search').value = ''; $('#song-filter').value = 'all';
  $('#request-panel').hidden = true; $('#request-toggle').setAttribute('aria-expanded','false');
  $('#message').textContent = '';
  renderMain(); renderStations(); renderSongs();
  $('#collection-message').textContent = 'Loading songs…';
  loadSongs();
}
function tune(id, browse = true) {
  if (browse) selectStation(id);
  tuned = id; paused = false; connecting = true;
  const version = ++tuneVersion;
  $('#player-message').textContent = 'Buffering about two seconds of live audio…';
  $('#audio').src = '/stream/' + encodeURIComponent(id) + '?t=' + Date.now();
  $('#audio').play().catch(() => {
    if (version === tuneVersion) { paused = true; $('#player-message').textContent = 'Press Play to try again.'; }
  }).finally(() => { if (version === tuneVersion) { connecting = false; renderMain(); renderStations(); } });
  renderMain(); renderStations();
}
$('#tune').onclick = () => { if (selected) tune(selected); };
$('#live').onclick = () => { if (tuned) tune(tuned, false); };
$('#play-stop').onclick = () => {
  if (tuned && !paused) {
    ++tuneVersion; connecting = false; paused = true;
    $('#audio').pause(); $('#audio').removeAttribute('src'); $('#audio').load();
    $('#player-message').textContent = '';
    renderMain(); renderStations();
  } else if (tuned || selected) tune(tuned || selected, false);
};
$('#audio').addEventListener('pause', () => { if (!connecting) { paused = true; renderMain(); renderStations(); } });
$('#audio').addEventListener('play', () => { if (paused && tuned) tune(tuned, false); });
$('#audio').addEventListener('playing', () => { $('#player-message').textContent = ''; });
$('#audio').addEventListener('error', () => { paused = true; connecting = false; renderMain(); renderStations(); $('#player-message').textContent = 'Connection lost. Press Reconnect to try again.'; });

function renderStations() {
  $('#station-count').textContent = stations.length;
  const ids = new Set(stations.map(s => s.id));
  for (const [id, card] of cards) if (!ids.has(id)) { card.remove(); cards.delete(id); }
  if (!stations.length) {
    $('#stations').textContent = 'No stations yet. Sync your catalog or request a station below.';
    return;
  }
  if (!cards.size) $('#stations').replaceChildren();
  for (const s of stations) {
    let card = cards.get(s.id);
    if (!card) {
      card = document.createElement('section');
      card.tabIndex = 0;
      card.setAttribute('role', 'group');
      card.setAttribute('aria-label', s.name);
      card.addEventListener('click', event => {
        // Tune in remains an explicit action; every other part of the card
        // selects it for browsing.
        if (!event.target.closest('.station-tune')) selectStation(card.dataset.stationId);
      });
      card.addEventListener('keydown', event => {
        if ((event.key === 'Enter' || event.key === ' ') && event.target === card) {
          event.preventDefault(); selectStation(card.dataset.stationId);
        }
      });
      const select = document.createElement('button'); select.className = 'station-select'; select.onclick = () => selectStation(s.id);
      const info = document.createElement('p');
      const play = document.createElement('button'); play.className = 'station-tune'; play.onclick = () => tune(s.id);
      card.append(select, info, play); cards.set(s.id, card); $('#stations').append(card);
    }
    card.dataset.stationId = s.id;
    card.className = 'station-card' + (s.id === selected ? ' active' : '');
    card.children[0].textContent = s.name; card.children[0].setAttribute('aria-pressed', String(s.id === selected));
    card.children[1].textContent = s.now_playing ? `${s.now_playing.title} · ${s.now_playing.artist}` : s.status === 'pending' ? 'Awaiting approval' : 'Waiting for music';
    card.children[2].disabled = !s.now_playing || s.status !== 'approved';
    const listening = tuned === s.id && !paused;
    card.children[2].textContent = listening ? 'Listening' : 'Listen';
    if (listening) card.children[2].disabled = true;
    card.children[2].setAttribute('aria-label', (listening ? 'Listening to ' : 'Listen to ') + s.name);
  }
}
function renderSongs() {
  const search = $('#song-search').value.trim().toLocaleLowerCase(), filter = $('#song-filter').value;
  const visible = songs.map((song,index) => ({song,index})).filter(({song}) => (filter === 'all' || song.status === filter) && `${song.title} ${song.artist}`.toLocaleLowerCase().includes(search));
  $('#song-rows').replaceChildren(...visible.map(({song,index}) => {
    const row = document.createElement('tr');
    for (const [i, value] of [String(index+1).padStart(2,'0'), song.title, song.artist].entries()) {
      const cell = document.createElement('td'); cell.textContent = value; if (!i) cell.className='number'; row.append(cell);
    }
    const cell=document.createElement('td'), badge=document.createElement('span');
    badge.className = 'song-status ' + (song.status === 'approved' ? 'approved' : song.status === 'rejected' ? 'rejected' : 'pending');
    badge.textContent = song.queued ? 'Waiting to sync' : song.status === 'pending' ? 'Pending approval' : song.status === 'rejected' ? 'Rejected' : song.status === 'approved' ? song.cached ? 'Approved' : 'Preparing audio' : song.status;
    if (song.status === 'approved' && !song.cached) {
      badge.textContent = song.download_status === 'failed' ? 'Download failed' : song.download_status === 'downloading' ? 'Downloading audio' : 'Queued for download';
      if (song.download_status === 'failed') badge.className = 'song-status rejected';
    }
    cell.append(badge);
    if (song.can_retry) {
      const retry = document.createElement('button'), stationId = selected;
      retry.type = 'button'; retry.className = 'quiet download-retry'; retry.textContent = 'Retry download';
      retry.setAttribute('aria-label', 'Retry download of ' + song.title + ' by ' + song.artist);
      retry.onclick = async () => {
        retry.disabled = true;
        try {
          const result = await api('/api/stations/' + encodeURIComponent(stationId) + '/songs/' + encodeURIComponent(song.id) + '/retry',
            {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
          if (selected === stationId) $('#message').textContent = result.message;
        } catch (error) { if (selected === stationId) $('#message').textContent = error.message; }
        finally { retry.disabled = false; if (selected === stationId) await loadSongs(); }
      };
      cell.append(retry);
    }
    row.append(cell); return row;
  }));
  const approved = songs.filter(s => s.status === 'approved').length, pending = songs.filter(s => s.status === 'pending').length;
  $('#collection-summary').textContent = `${songs.length} songs · ${approved} approved · ${pending} pending`;
  $('#collection-message').textContent = visible.length ? '' : songs.length ? 'No matching songs. Try another title, artist, or status.' : selected ? 'No songs here yet. Be the first to request one.' : 'Select a station to see its collection.';
}
async function loadSongs() {
  if (!selected) return;
  const id=selected, version=++songVersion;
  try {
    const body=await api('/api/stations/'+encodeURIComponent(id)+'/songs');
    if (id !== selected || version !== songVersion) return;
    songs=body.songs; renderSongs();
  } catch(error) {
    if (id===selected && version===songVersion) $('#collection-message').textContent=error.message;
  }
}
$('#song-search').oninput=renderSongs; $('#song-filter').onchange=renderSongs;
$('#request-toggle').onclick=() => {
  const panel=$('#request-panel'); panel.hidden=!panel.hidden;
  $('#request-toggle').setAttribute('aria-expanded',String(!panel.hidden));
  if (!panel.hidden) $('#song input[name="title"]').focus();
};
function renderHealth(health) {
  const state=health.sync || {}, now=Date.now()/1000;
  $('#sync').disabled=!state.configured || state.running || state.requested || state.manual_available_at>now;
  $('#sync-state').textContent=!state.configured ? 'Sheets not configured' : state.running ? 'Syncing…' : state.requested ? 'Sync queued…' : health.sync_error ? 'Sync failed — expand details' : state.next_sync_at ? 'Next sync '+new Date(state.next_sync_at*1000).toLocaleTimeString() : 'No queued requests · manual sync available';
  $('#health').textContent=[health.sync_error,...(health.catalog_warnings||[]),`${health.pending_requests} requests queued. ${health.rejected_requests||0} undeliverable.`, 'Last catalog update: '+(health.last_sheet_sync ? new Date(health.last_sheet_sync*1000).toLocaleString() : 'not yet')].filter(Boolean).join(' | ');
  const failures=health.recent_sync_failures||[]; $('#sync-history').hidden=!failures.length;
  $('#sync-errors').replaceChildren(...failures.map(f => {const li=document.createElement('li'); li.textContent=new Date(f.occurred_at*1000).toLocaleString()+': '+f.error; return li;}));
}
async function refresh() {
  if (refreshing) return; refreshing=true;
  try {
    const [catalog,health]=await Promise.all([api('/api/stations'),api('/api/health')]);
    stations=catalog.stations;
    if (!stations.some(s=>s.id===selected)) {
      selected=stations.find(s=>s.status==='approved')?.id || stations[0]?.id || null;
      songs=[]; songVersion++; $('#song-search').value=''; $('#song-filter').value='all';
      $('#request-panel').hidden=true; $('#request-toggle').setAttribute('aria-expanded','false'); renderSongs();
    }
    renderStations(); renderMain(); renderHealth(health); await loadSongs();
  } catch(error) { $('#sync-state').textContent='Service unavailable'; $('#health').textContent=error.message; }
  finally { refreshing=false; }
}
$('#sync').onclick=async()=>{
  $('#sync').disabled=true;
  try { $('#sync-message').textContent=(await api('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).message; }
  catch(error) { $('#sync-message').textContent=error.message; }
  await refresh();
};
for (const type of ['song','station']) $('#'+type).onsubmit=async event=>{
  event.preventDefault(); const form=event.currentTarget, button=form.querySelector('button'), target=selected; button.disabled=true;
  try {
    const body=await api('/api/requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,...Object.fromEntries(new FormData(form))})});
    $('#message').textContent=body.message;
    if (type==='station' || target===selected) form.reset();
    if (type==='station') $('#sync-message').textContent=body.message;
    renderMain(); await loadSongs(); await refresh();
  } catch(error) { (type==='station' ? $('#sync-message') : $('#message')).textContent=error.message; }
  finally { button.disabled=false; if(type==='song') renderMain(); }
};
refresh(); setInterval(refresh,5000);
