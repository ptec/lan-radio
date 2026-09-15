/* Moderation tabs: station:Rock (live), pending:Rock (awaiting approval).
 * Each tab is a complete playlist. No row IDs or cross-sheet references.
 * Set SHEETS_TOKEN in Script Properties, run setup, deploy as a Web app. */
const SONG_HEADERS = ['Title', 'Artist', 'Status', 'YouTube ID'];
const RECEIPTS = 'metadata:Request receipts';
const RECEIPT_HEADERS = ['Request token', 'Outcome', 'Received at'];

function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  PropertiesService.getScriptProperties().setProperty('SPREADSHEET_ID', ss.getId());
  receiptSheet(ss);
  ss.getSheets().filter(s => tabInfo(s)).forEach(formatStation);
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Radio moderation')
    .addItem('Format station tabs', 'setup').addToUi();
}

function tabInfo(sheet) {
  const match = /^(station|pending):(.+)$/.exec(sheet.getName());
  if (!match || !match[2].trim()) return null;
  return {name:match[2].trim(), status:match[1] === 'station' ? 'approved' : 'pending'};
}

function columns(sheet) {
  const values = sheet.getDataRange().getDisplayValues();
  const headers = (values[0] || []).map(v => String(v).trim().toLowerCase());
  const positions = SONG_HEADERS.map(h => headers.indexOf(h.toLowerCase()));
  if (positions.slice(0,3).some(i => i < 0) ||
      SONG_HEADERS.some(h => headers.filter(v => v === h.toLowerCase()).length > 1)) {
    throw Error('Use unique Title, Artist, Status headers in row 1');
  }
  return {values, positions};
}

function formatStation(sheet) {
  if (!sheet.getLastRow()) sheet.appendRow(SONG_HEADERS);
  const {positions} = columns(sheet);
  sheet.setFrozenRows(1);
  sheet.getRange(1,1,1,sheet.getLastColumn()).setFontWeight('bold');
  sheet.getRange(2,positions[2]+1,Math.max(1,sheet.getMaxRows()-1),1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(['pending','approved','rejected'],true).setAllowInvalid(false).build());
  sheet.autoResizeColumns(1,sheet.getLastColumn());
}

function receiptSheet(ss) {
  let sheet = ss.getSheetByName(RECEIPTS);
  if (!sheet) {
    sheet = ss.insertSheet(RECEIPTS);
    sheet.appendRow(RECEIPT_HEADERS);
    sheet.hideSheet();
  }
  const header = sheet.getDataRange().getDisplayValues()[0];
  if (JSON.stringify(header) !== JSON.stringify(RECEIPT_HEADERS)) throw Error('Request receipt headers were changed');
  return sheet;
}

function catalog(ss) {
  const stations = [], warnings = [];
  for (const sheet of ss.getSheets()) {
    const info = tabInfo(sheet);
    if (!info) continue;
    const songs = [];
    try {
      const {values, positions} = columns(sheet);
      values.slice(1).forEach((row,index) => {
        const [title,artist,status,video] = positions.map(i => i < 0 ? '' : String(row[i] || '').trim());
        if (!title && !artist && !status && !video) return;
        if (!title || !artist) {
          warnings.push(sheet.getName() + ' row ' + (index+2) + ': incomplete song; skipped');
          return;
        }
        songs.push({title,artist,status:status.toLowerCase() || 'pending',youtube_id:video});
      });
    } catch (err) {
      warnings.push(sheet.getName() + ': ' + err.message + '; playlist paused');
    }
    stations.push({...info,songs});
  }
  const unique = new Map();
  for (const station of stations) {
    const old = unique.get(station.name);
    if (old) warnings.push('Duplicate station name: ' + station.name + '; using the approved tab if present');
    if (!old || station.status === 'approved') unique.set(station.name,station);
  }
  return {ok:true,schema_version:2,stations:[...unique.values()],warnings};
}

function field(r,key) {
  if (typeof r[key] !== 'string' || !r[key].trim() || r[key].length > 200) throw Error('Invalid ' + key);
  return r[key].trim();
}

function stationName(value) {
  if (!value || value.length > 91 || /[\[\]*?:/\\]/.test(value)) throw Error('Station names: 1–91 characters, no [ ] * ? : / or backslash');
  return value;
}

function submitOne(ss,r) {
  if (r.type === 'station') {
    const name = stationName(field(r,'name'));
    if (ss.getSheetByName('station:'+name) || ss.getSheetByName('pending:'+name)) return 'already exists';
    formatStation(ss.insertSheet('pending:'+name));
    return 'submitted';
  }
  if (r.type !== 'song') throw Error('Invalid request type');
  const name = field(r,'station'), title = field(r,'title'), artist = field(r,'artist');
  const sheet = ss.getSheets().find(s => {const info=tabInfo(s); return info && info.status==='approved' && info.name===name;});
  // A stale request must never recreate a tab deleted/renamed by a moderator.
  if (!sheet) return 'rejected: station was removed, renamed, or is not approved';
  const {values,positions} = columns(sheet);
  if (values.slice(1).some(row => String(row[positions[0]]||'').trim().toLowerCase()===title.toLowerCase() &&
      String(row[positions[1]]||'').trim().toLowerCase()===artist.toLowerCase())) return 'already exists';
  const row = new Array(sheet.getLastColumn()).fill('');
  row[positions[0]] = "'" + title;
  row[positions[1]] = "'" + artist;
  row[positions[2]] = 'pending';
  sheet.appendRow(row);
  return 'submitted';
}

function json(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function doGet() { return json({ok:false,error:'Use authenticated POST'}); }

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    const data = JSON.parse(e.postData.contents);
    const props = PropertiesService.getScriptProperties(), token=props.getProperty('SHEETS_TOKEN');
    if (!token || data.token!==token) return json({ok:false,error:'Unauthorized'});
    lock.waitLock(25000);
    const ss = SpreadsheetApp.openById(props.getProperty('SPREADSHEET_ID'));
    if (data.action==='catalog') return json(catalog(ss));
    if (data.action!=='submit' || !Array.isArray(data.requests) || data.requests.length>100) throw Error('Invalid request');
    const receipts = receiptSheet(ss);
    // Delivery tokens are not pointers to rows/tabs. Retain after deletion.
    const seen = new Map(receipts.getDataRange().getDisplayValues().slice(1).map(r=>[r[0],r[1]]));
    const acknowledged=[], rejected=[], errors=[];
    for (const r of data.requests) {
      try {
        if (!r || typeof r.id!=='string' || !/^[0-9a-f-]{36}$/.test(r.id)) throw Error('Invalid request token');
        let outcome = seen.get(r.id);
        if (!outcome) {
          outcome = submitOne(ss,r);
          receipts.appendRow([r.id,outcome,new Date().toISOString()]);
          SpreadsheetApp.flush();
          seen.set(r.id,outcome);
        }
        acknowledged.push(r.id);
        if (outcome.startsWith('rejected:')) rejected.push({id:r.id,error:outcome});
      } catch (err) { errors.push({id:r && r.id,error:String(err.message)}); }
    }
    return json({ok:true,acknowledged,rejected,errors});
  } catch (err) { return json({ok:false,error:String(err.message)}); }
  finally { if (lock.hasLock()) lock.releaseLock(); }
}

/* Optional conversion of the old Stations/Songs layout. Creates independent
 * tabs; leaves originals intact. Refuses to overwrite existing targets. */
function migrateLegacy() {
  const ss=SpreadsheetApp.getActiveSpreadsheet();
  function read(name) {
    const sheet=ss.getSheetByName(name);
    if (!sheet) throw Error('Missing legacy '+name+' tab');
    const values=sheet.getDataRange().getDisplayValues(), headers=values.shift();
    return values.filter(r=>r[0]).map(r=>Object.fromEntries(headers.map((h,i)=>[h,String(r[i]||'').trim()])));
  }
  const stations=read('Stations'), songs=read('Songs'), names=new Set();
  const planned=stations.map(s=>{
    const prefix=s.status.toLowerCase()==='approved'?'station:':s.status.toLowerCase()==='rejected'?'archived:':'pending:';
    const name=prefix+stationName(s.name);
    if (names.has(name) || ss.getSheetByName(name)) throw Error('Target already exists: '+name);
    names.add(name);
    return {name,songs:songs.filter(song=>song.station_id===s.id)};
  });
  if (songs.some(song=>!stations.some(s=>s.id===song.station_id))) throw Error('Legacy song has an unknown station; fix it before migration');
  for (const plan of planned) {
    const sheet=ss.insertSheet(plan.name);
    formatStation(sheet);
    for (const song of plan.songs) sheet.appendRow(["'"+song.title,"'"+song.artist,song.status||'pending',"'"+song.youtube_id]);
  }
  setup();
}
