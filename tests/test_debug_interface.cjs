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
const html=fs.readFileSync(path.join(__dirname,'../radio/templates/admin.html'),'utf8');
const nodes=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
nodes.get('filter').value=html.match(/<select id="filter">[\s\S]*?<option value="([^"]+)" selected>/)[1];
assert.equal(nodes.get('filter').value,'all','Default view must include all moderation statuses');
const data={stations:[{id:'station',name:'Rock'}],songs:[{id:'song',station_id:'station',title:'Song',artist:'Artist',status:'approved',youtube_id:'',cached:true,download_status:'ready'}],
  uptime_seconds:120,cache_files:1,cache_bytes:1024,downloads:{failed:1},pending_requests:0,last_sync:null};
const saves=[], scans=[];
let scheduledRefresh;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../radio/static/testing.js'),'utf8'),{
  document:{getElementById:id=>nodes.get(id)||null,createElement:()=>new Element(),querySelectorAll:()=>[]},
  window:{},
  setTimeout:fn=>{scheduledRefresh=fn;return 1;},
  clearTimeout:()=>{},
  localStorage:{getItem:()=>null},Option:function(text,value){this.textContent=text;this.value=value;},
  fetch:async(url,options)=>{if(url==='/api/admin/review'){if(options?.method==='POST') scans.push(JSON.parse(options.body));return {ok:true,json:async()=>({scan:{running:false,completed:1,total:1,errors:0},songs:{song:{state:'matched',explicit_state:'explicit'}}})};}if(url==='/api/admin/edits'){saves.push(...JSON.parse(options.body).edits);return {ok:true,json:async()=>({results:JSON.parse(options.body).edits.map(e=>({id:e.id,saved:true}))})};}return {ok:true,json:async()=>JSON.parse(JSON.stringify(data))};},console,
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
    assert.equal(nodes.get('songs').children[0].children.length,8);
    assert.equal(nodes.get('songs').children[0].children[2].children[0].value,'Song');
    assert.equal(nodes.get('result-count').textContent,'1 of 1 songs');
    const row = nodes.get('songs').children[0], title = row.children[2].children[0];
    title.value = 'Corrected'; title.oninput();
    assert.equal(row.className,'dirty');
    assert.equal(row.children[7].children[1].textContent,'Unsaved changes');
    nodes.get('search').oninput();
    const restored = nodes.get('songs').children[0];
    assert.equal(restored.children[2].children[0].value,'Corrected');
    restored.children[2].children[0].value='Song';restored.children[2].children[0].oninput();
    assert.equal(restored.className,'');
    restored.children[2].children[0].value='Fixed';restored.children[2].children[0].oninput();
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
    nodes.get('search').value='';nodes.get('search').oninput();
    const moderation = nodes.get('songs').children[0].children[5];
    moderation.children[0].value='rejected';moderation.children[0].onchange();
    const notes = moderation.children[1].children[1];notes.value='Clean version required';notes.oninput();
    assert.equal(nodes.get('save-all').disabled,false);
    await nodes.get('save-all').onclick();
    assert.equal(saves.at(-1).changes.status,'rejected');assert.equal(saves.at(-1).changes.notes,'Clean version required');
    await nodes.get('review-pending').onclick();assert.equal(scans.at(-1).scope,'pending');
    await nodes.get('explicit-start').onclick();assert.equal(scans.at(-1).tool,'explicit');assert.equal(scans.at(-1).scope,'unchecked');
    await nodes.get('explicit-refresh').onclick();assert.equal(nodes.get('filter').value,'explicit');assert.equal(nodes.get('songs').children.length,1);
    data.stations.push({id:'country',name:'Country'});
    data.songs.push({id:'second',station_id:'country',title:'Country song',artist:'Other artist',status:'pending',cached:false});
    nodes.get('filter').value='all';nodes.get('station').value='';
    await nodes.get('refresh').onclick();
    assert.equal(nodes.get('songs').children.length,2,'All stations includes approved and pending songs across stations');
    assert.equal(nodes.get('songs').children[1].children[1].textContent,'Country');
    nodes.get('station').value='country';nodes.get('station').onchange();
    assert.equal(nodes.get('songs').children.length,1);
    nodes.get('station').value='';nodes.get('station').onchange();
    assert.equal(nodes.get('songs').children.length,2);
    // A resumed scan's small queue must not replace the full catalog totals.
    data.review_scan={running:false,completed:1,total:1,errors:0};
    data.songs[0].metadata_review={state:'matched',explicit_state:'unknown'};
    data.songs[1].metadata_review={state:'error',explicit_state:'error'};
    await nodes.get('refresh').onclick();
    for (const id of ['review-status','explicit-status']) {
      assert.match(nodes.get(id).textContent,/Entire catalog: 1 of 2 songs checked; 1 left to scan/);
      assert.match(nodes.get(id).textContent,/including 1 failed checks to retry/);
      assert.match(nodes.get(id).textContent,/Last scan: 1 of 1 distinct/);
    }
    // Older metadata-only results must not count as completed explicit checks.
    data.songs[1].metadata_review={state:'review'};
    data.review_scan={running:false,completed:0,total:0,errors:0};
    nodes.get('station').value='country';
    await nodes.get('refresh').onclick();
    assert.match(nodes.get('review-status').textContent,/2 of 2 songs checked; 0 left to scan/);
    assert.match(nodes.get('explicit-status').textContent,/1 of 2 songs checked; 1 left to scan/);
    // A failure after opening the page must produce a Retry button on polling.
    nodes.get('station').value='';nodes.get('filter').value='all';
    await nodes.get('refresh').onclick();
    let first = nodes.get('songs').children[0];
    first.children[2].children[0].value='Unsaved title';
    first.children[2].children[0].oninput();
    data.songs[0].cached=false;data.songs[0].download_status='failed';
    await scheduledRefresh();
    first = nodes.get('songs').children[0];
    assert(first.children[7].children.some(child=>child.textContent==='Retry download'));
    assert.equal(first.children[2].children[0].value,'Unsaved title');
    first.children[2].children[0].value=data.songs[0].title;
    first.children[2].children[0].oninput();
    nodes.get('filter').value='failed';nodes.get('filter').onchange();
    assert.equal(nodes.get('songs').children.length,1);
    data.songs[0].download_status='queued';
    await scheduledRefresh();
    for (const row of nodes.get('songs').children) {
      assert(!row.children[7]?.children.some(child=>child.textContent==='Retry download'));
    }
    console.log('Debug page initial load renders statistics and editable song rows.');
  } catch(error){console.error(error);process.exitCode=1;}
});
