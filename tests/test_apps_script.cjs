const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const HEADERS=['Title','Artist','YouTube Id','Status','Notes'];
class Sheet {
  constructor(name,rows=[]){this.name=name;this.rows=rows;this.raw=[];}
  getName(){return this.name;}
  getDataRange(){return {getValues:()=>this.rows.length?this.rows.map(r=>[...r]):[['']]};}
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
const context={ContentService:{MimeType:{JSON:'json'},createTextOutput:text=>({text,setContent(value){this.text=value;return this;},setMimeType(){return this;}})},
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>k==='SHEETS_TOKEN'?'secret':'sheet',setProperty(){}})},
  LockService:{getScriptLock:()=>{throw Error('Script must not acquire a lock');}},
  SpreadsheetApp:{openById:()=>ss,getActiveSpreadsheet:()=>ss,flush(){},newDataValidation:()=>validation}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../google-apps-script/Code.gs'),'utf8'),context);

const call=(action,args={},method='GET')=>JSON.parse(context[method==='GET'?'doGet':'doPost']({parameter:{q:JSON.stringify({action,...args})}}).text);
const rock=new Sheet('station:Rock',[HEADERS,['Song','Artist','abcdefghijk','pending','Old note']]);sheets=[rock];
assert.deepEqual(call('getStations').content,['station:Rock']);
assert.equal(call('getStation',{stationId:'station:Rock'}).content[0].youtubeId,'abcdefghijk');
let result=call('updateStation',{stationId:'station:Rock',state:{'Song:Artist':{title:'Renamed',artist:'Artist',youtubeId:'',status:'not-approved',notes:'New note'}}},'POST');
assert.equal(result.ok,true);assert.equal(result.content[0].notes,'New note');assert.equal(result.content[0].youtubeId,'');assert.equal(result.content[0].status,'not-approved');
result=call('updateStation',{stationId:'station:Rock',state:{'Renamed:Artist':{notes:''},'New:Artist':{title:'=Literal',artist:'Artist',notes:'=Note'}}},'POST');
assert.equal(result.content[0].notes,'');assert.equal(rock.rows[2][0],'=Literal');assert.equal(rock.raw[0][0],"'=Literal");
assert.equal(call('createStation',{stationId:'pending:Jazz'},'POST').ok,true);
assert.deepEqual(sheets[1].rows[0],HEADERS);
assert.equal(call('getStation',{stationId:'missing'}).ok,false);
assert.equal(call('updateStation',{stationId:'station:Rock',state:null},'POST').ok,false);
assert.equal(call('unknown').ok,false);
console.log('Station API tests passed: reads, creation, edits, notes, clearing, literal values and errors.');
