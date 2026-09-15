// DOM-level interaction checks; no browser, network, or audio device required.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
class Element {
  constructor(){this.children=[];this.value='';this.textContent='';this.hidden=false;this.attrs={};}
  append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this.append(...children);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}
  setAttribute(name,value){this.attrs[name]=value;}
  addEventListener(name,handler){this['on'+name]=handler;}
  focus(){this.focused=true;}
  querySelector(selector){return get('#song '+selector);}
}
const nodes=new Map(),get=selector=>{if(!nodes.has(selector))nodes.set(selector,new Element());return nodes.get(selector);};
let played=0,requests=[];
get('#audio').play=()=>{played++;return Promise.resolve();};
get('#song-filter').value='all';
const stations=[{id:'a',name:'Jazz',status:'approved',ready:2,approved:2,now_playing:{title:'So What',artist:'Miles Davis'},up_next:{title:'Take Five',artist:'Dave Brubeck'}},
 {id:'b',name:'Rock',status:'approved',ready:1,approved:1,now_playing:{title:'Rock song',artist:'Band'},up_next:{title:'Another song',artist:'Band'}}];
const songs=[{title:'So What',artist:'Miles Davis',status:'approved',cached:true},{title:'Pending song',artist:'Artist',status:'pending'}, {title:'Rejected song',artist:'Artist',status:'rejected'}];
const context={document:{querySelector:get,createElement:()=>new Element()},console,Date,encodeURIComponent,setInterval:()=>0,
 fetch:async(url,options)=>{
   requests.push({url,options});
   const body=url==='/api/stations'?{stations}:url==='/api/health'?{sync:{configured:true},pending_requests:0}:url==='/api/sync'?{message:'Sync queued'}:{songs};
   return {ok:true,json:async()=>body};
 }};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../radio/static/app.js'),'utf8'),context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await settle();
 assert.equal(get('#station-title').textContent,'Jazz');
 assert.equal(get('#next-title').textContent,'Take Five');
 assert.equal(get('#song-rows').children.length,3);
 assert.equal(played,0,'Opening page must not autoplay');
 get('#stations').children[1].children[0].onclick();await settle();
 assert.equal(get('#station-title').textContent,'Rock');assert.equal(played,0,'Browsing must not change audio');
 assert.equal(get('#song input[name="station_id"]').value,'b');
 get('#request-toggle').onclick();assert.equal(get('#request-panel').hidden,false);
 assert.equal(get('#request-toggle').attrs['aria-expanded'],'true');
 get('#song-search').value='Miles';get('#song-search').oninput();assert.equal(get('#song-rows').children.length,1);
 get('#song-search').value='';get('#song-filter').value='rejected';get('#song-filter').onchange();assert.equal(get('#song-rows').children.length,1);
 get('#tune').onclick();await settle();assert.equal(played,1);assert(get('#audio').src.startsWith('/stream/b?'));
 get('#stations').children[0].children[0].onclick();await settle();assert.equal(get('#listening').textContent,'Rock');assert.equal(played,1);
 await get('#sync').onclick();assert.equal(get('#sync-message').textContent,'Sync queued');assert(requests.some(r=>r.url==='/api/sync'&&r.options.method==='POST'));
 console.log('Interface checks passed: initial selection, up next, all statuses, independent browsing/listening, request target, search/filter, tuning, sync.');
})().catch(error=>{console.error(error);process.exitCode=1;});
