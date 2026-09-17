const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor(){this.children=[];this.value='';this.textContent='';this.attrs={};this.dataset={};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(key,value){this.attrs[key]=value;}
}
// Only expose IDs present in the real template: missing elements must fail.
const html=fs.readFileSync(path.join(__dirname,'../radio/templates/testing.html'),'utf8');
const nodes=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
nodes.get('filter').value='all';
const data={stations:[{id:'station',name:'Rock'}],songs:[{id:'song',station_id:'station',title:'Song',artist:'Artist',status:'approved',youtube_id:'',cached:true,download_status:'ready'}],
  uptime_seconds:120,cache_files:1,cache_bytes:1024,downloads:{failed:1},pending_requests:0,last_sync:null};
const saves=[];
let scheduledRefresh;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../radio/static/testing.js'),'utf8'),{
  document:{getElementById:id=>nodes.get(id)||null,createElement:()=>new Element(),querySelectorAll:()=>[]},
  window:{},
  setTimeout:fn=>{scheduledRefresh=fn;return 1;},
  localStorage:{getItem:()=>null},Option:function(text,value){this.textContent=text;this.value=value;},
  fetch:async(url,options)=>{if(url==='/api/debug/edits'){saves.push(...JSON.parse(options.body).edits);return {ok:true,json:async()=>({results:JSON.parse(options.body).edits.map(e=>({id:e.id,saved:true}))})};}return {ok:true,json:async()=>data};},console,
});
setImmediate(async()=>{
  try {
    assert.equal(nodes.get('message').textContent,'','Initial load must not report an error');
    assert.equal(nodes.get('stats').children.length,6);
    assert.equal(nodes.get('stats').children[4].children[1].textContent,0,'Historical failures must not count as current songs');
    assert.equal(nodes.has('checked'),false);
    assert.equal(nodes.has('progress'),false);
    assert.match(nodes.get('sync-detail').textContent,/Last catalog sync/);
    assert.equal(nodes.get('songs').children.length,1);
    assert.equal(nodes.get('songs').children[0].children.length,6);
    assert.equal(nodes.get('songs').children[0].children[1].children[0].value,'Song');
    assert.equal(nodes.get('result-count').textContent,'1 of 1 songs');
    const row = nodes.get('songs').children[0], title = row.children[1].children[0];
    title.value = 'Corrected'; title.oninput();
    assert.equal(row.className,'dirty');
    assert.equal(row.children[5].children[1].textContent,'Unsaved changes');
    nodes.get('search').oninput();
    const restored = nodes.get('songs').children[0];
    assert.equal(restored.children[1].children[0].value,'Corrected');
    restored.children[1].children[0].value='Song';restored.children[1].children[0].oninput();
    assert.equal(restored.className,'');
    restored.children[1].children[0].value='Fixed';restored.children[1].children[0].oninput();
    assert.equal(nodes.get('save-all').textContent,'Save & sync all (1)');
    nodes.get('search').value='hidden';nodes.get('search').oninput();
    await nodes.get('save-all').onclick();
    assert.equal(saves.length,1);assert.equal(saves[0].changes.title,'Fixed');
    assert.match(nodes.get('message').textContent,/1 of 1 saved/);
    assert.equal(nodes.get('save-all').disabled,true);
    const rowsBefore = nodes.get('songs').children;
    data.uptime_seconds=185;data.cache_files=4;
    await scheduledRefresh();
    assert.equal(nodes.get('stats').children[0].children[1].textContent,'0h 3m 5s');
    assert.equal(nodes.get('stats').children[2].children[1].textContent,4);
    assert.strictEqual(nodes.get('songs').children,rowsBefore,'Statistics polling must not rebuild song rows');
    console.log('Debug page initial load renders statistics and editable song rows.');
  } catch(error){console.error(error);process.exitCode=1;}
});
