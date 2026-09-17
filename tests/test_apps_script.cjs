const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const HEADERS=['Title','Artist','Status','YouTube ID'];
class Sheet {
  constructor(name,rows=[]){this.name=name;this.rows=rows;this.raw=[];}
  getName(){return this.name;}
  getDataRange(){return {getDisplayValues:()=>this.rows.length?this.rows.map(r=>[...r]):[['']]};}
  getLastRow(){return this.rows.length;}
  getLastColumn(){return Math.max(1,...this.rows.map(r=>r.length));}
  getMaxRows(){return 1000;}
  appendRow(row){this.raw.push([...row]);this.rows.push(row.map(v=>String(v).replace(/^'/,'')));return this;}
  getRange(row,col){return {setDataValidation(){},setFontWeight(){},setValue:value=>{this.rows[row-1][col-1]=String(value).replace(/^'/,'');}};}
  setFrozenRows(){}
  autoResizeColumns(){}
  hideSheet(){this.hidden=true;}
}
let sheets=[],locked=false;
const ss={getSheets:()=>sheets,getSheetByName:name=>sheets.find(s=>s.name===name),
  insertSheet:name=>{assert(!sheets.some(s=>s.name===name));const s=new Sheet(name);sheets.push(s);return s;},getId:()=> 'sheet'};
const validation={requireValueInList(){return this;},setAllowInvalid(){return this;},build(){return {};}};
const context={ContentService:{MimeType:{JSON:'json'},createTextOutput:text=>({text,setMimeType(){return this;}})},
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>k==='SHEETS_TOKEN'?'secret':'sheet',setProperty(){}})},
  LockService:{getScriptLock:()=>({waitLock(){locked=true;},hasLock:()=>locked,releaseLock(){locked=false;}})},
  SpreadsheetApp:{openById:()=>ss,getActiveSpreadsheet:()=>ss,flush(){},newDataValidation:()=>validation}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../google-apps-script/Code.gs'),'utf8'),context);
const post=data=>JSON.parse(context.doPost({postData:{contents:JSON.stringify({token:'secret',...data})}}).text);
const catalog=()=>post({action:'catalog'});
const token=n=>String(n).padStart(8,'0')+'-1234-1234-1234-123456789abc';
const submit=(...requests)=>post({action:'submit',requests});
let passed=0;
function test(name,body){sheets=[new Sheet('Notes',[['Moderator notes']])];body();assert.equal(locked,false);passed++;console.log('PASS '+name);}

test('Form payload, batch partial outcomes and retry receipts',()=>{
  const sheet = new Sheet('station:Rock',[HEADERS,['A&B + café','Artist','approved',''],['Other','Artist','approved','']]);sheets.push(sheet);
  const edit={id:'one',request_token:'a'.repeat(64),station:'Rock',station_status:'approved',original:{title:'A&B + café',artist:'Artist',status:'approved',youtube_id:''},changes:{title:'Fixed + %','artist':'Artist',youtube_id:''}};
  const body={token:'secret',action:'edit_batch',edits:[edit,{...edit,id:'bad',request_token:'b'.repeat(64),original:{...edit.original,title:'Missing'}}]};
  const send=()=>JSON.parse(context.doPost({parameter:{payload:JSON.stringify(body)}}).text);
  const first=send();assert.equal(first.results[0].saved,true);assert.equal(first.results[1].saved,false);
  assert.equal(sheet.rows[1][0],'Fixed + %');assert.equal(send().results[0].saved,true);
  assert.equal(sheet.rows.length,3);assert.equal(locked,false);
});

test('Testing edits preserve status and notes and reject stale or duplicate rows',()=>{
  const sheet=new Sheet('station:Rock',[['Notes',...HEADERS],['keep','Song','Artist','approved','']]);sheets.push(sheet);
  const original={title:'Song',artist:'Artist',status:'approved',youtube_id:''};
  const data={action:'edit',station:'Rock',station_status:'approved',original,changes:{title:'=Literal',artist:'New artist',youtube_id:'abcdefghijk'}};
  assert.equal(post(data).ok,true);
  assert.deepEqual(sheet.rows[1],['keep','=Literal','New artist','approved','abcdefghijk']);
  assert.equal(post(data).conflict,true);
  sheet.rows.push(['other','Song','Artist','approved',''],['duplicate','Song','Artist','approved','']);
  assert.equal(post(data).conflict,true);
  sheet.name='station:Renamed';assert.equal(post(data).conflict,true);
});

test('Authentication and nested station catalog, no spreadsheet IDs',()=>{
  sheets.push(new Sheet('station:Rock',[HEADERS,['Song','Artist','approved','']]),new Sheet('pending:Country',[HEADERS]),new Sheet('metadata:Other',[['ignored']]));
  assert.equal(post({token:'bad',action:'catalog'}).ok,false);
  const c=catalog();assert.equal(c.schema_version,2);assert.equal(c.stations.length,2);
  assert.equal(c.stations[0].name,'Rock');assert.equal(c.stations[0].songs[0].artist,'Artist');
  assert(!JSON.stringify(c).includes('station_id'));assert(!JSON.stringify(c).includes('"id"'));
});
test('Moderator edits, deletes, clears, sorts, moves rows and renames/deletes tabs',()=>{
  const rock=new Sheet('station:Rock',[HEADERS,['First','Artist','approved',''],['Second','Artist','approved','']]);sheets.push(rock);
  rock.rows[1][0]='Edited';rock.rows[1][2]='rejected';assert.equal(catalog().stations[0].songs[0].title,'Edited');
  assert.equal(catalog().stations[0].songs[0].status,'rejected');
  rock.rows=[HEADERS,rock.rows[2],rock.rows[1]];assert.equal(catalog().stations[0].songs[0].title,'Second');
  const country=new Sheet('station:Country',[HEADERS,rock.rows.pop()]);sheets.push(country);
  assert.equal(catalog().stations[0].songs.length,1);assert.equal(catalog().stations[1].songs[0].title,'Edited');
  rock.rows[1]=['','','',''];assert.equal(catalog().stations[0].songs.length,0);
  country.name='station:Folk';assert.equal(catalog().stations[1].name,'Folk');
  sheets=sheets.filter(s=>s!==country);assert.equal(catalog().stations.length,1);
});
test('Column reorder, extra notes, partial rows and blank status',()=>{
  sheets.push(new Sheet('station:Rock',[['Notes','Status','Artist','Title'],['free text','','Artist','Song'],['','approved','','unfinished']]));
  const c=catalog();assert.equal(c.stations[0].songs.length,1);assert.equal(c.stations[0].songs[0].status,'pending');assert.equal(c.warnings.length,1);
  submit({id:token(1),type:'song',station:'Rock',title:'New',artist:'Other'});
  assert.deepEqual(sheets[1].rows[3],['','pending','Other','New']);
});
test('Broken headers pause only that station, not updates to the others',()=>{
  sheets.push(new Sheet('station:Rock',[['Broken'],['Old audio']]),new Sheet('station:Country',[HEADERS,['New','Artist','approved','']]));
  const c=catalog();assert(c.ok);assert.equal(c.stations[0].songs.length,0);assert.equal(c.stations[1].songs.length,1);assert.equal(c.warnings.length,1);
});
test('New station approval is a tab rename; retries never resurrect deleted tabs',()=>{
  const r={id:token(2),type:'station',name:'Jazz'};
  assert.equal(submit(r).acknowledged.length,1);
  const tab=ss.getSheetByName('pending:Jazz');assert(tab);assert.deepEqual(tab.rows[0],HEADERS);assert.equal(catalog().stations[0].status,'pending');
  tab.name='station:Jazz';assert.equal(catalog().stations[0].status,'approved');
  submit(r);assert(!ss.getSheetByName('pending:Jazz'));
  sheets=sheets.filter(s=>s!==tab);submit(r);assert.equal(catalog().stations.length,0);
});
test('Pending-only literal song writes, receipts survive moderator row deletion',()=>{
  const rock=new Sheet('station:Rock',[HEADERS]);sheets.push(rock);
  const r={id:token(3),type:'song',station:'Rock',title:'=1+1',artist:'Artist',status:'approved'};
  assert.equal(submit(r,r).acknowledged.length,2);assert.equal(rock.rows.length,2);
  assert.equal(rock.rows[1][2],'pending');assert.equal(rock.raw[0][0],"'=1+1");
  rock.rows.pop();submit(r);assert.equal(rock.rows.length,1);assert(ss.getSheetByName('metadata:Request receipts').hidden);
});
test('Stale song requests rejected without recreating a station; other requests proceed',()=>{
  const result=submit({id:token(4),type:'song',station:'Deleted',title:'Song',artist:'Artist'},
    {id:token(5),type:'station',name:'New'});
  assert.equal(result.acknowledged.length,2);assert.equal(result.rejected.length,1);assert(!ss.getSheetByName('station:Deleted'));
  assert(ss.getSheetByName('pending:New'));
});
test('Reject invalid station names and continue batch',()=>{
  const result=submit({id:token(6),type:'station',name:'Bad/Name'},{id:token(7),type:'station',name:'Good'});
  assert.equal(result.errors.length,1);assert.equal(result.acknowledged.length,1);
});
test('Legacy migration copies independent playlists without touching originals',()=>{
  const oldStations=new Sheet('Stations',[['id','name','status','created_at'],['s1','Rock','approved','']]);
  const oldSongs=new Sheet('Songs',[['id','station_id','title','artist','status','youtube_id','created_at'],['song1','s1','Song','Artist','approved','','']]);
  sheets.push(oldStations,oldSongs);const before=JSON.stringify(oldSongs.rows);context.migrateLegacy();
  assert.equal(JSON.stringify(oldSongs.rows),before);const rock=ss.getSheetByName('station:Rock');assert(rock);
  assert.deepEqual(rock.rows,[HEADERS,['Song','Artist','approved','']]);assert.equal(catalog().stations.length,1);
  assert.throws(()=>context.migrateLegacy(),/already exists/);
});
console.log(passed+' Apps Script scenario tests passed.');
