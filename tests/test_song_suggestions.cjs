const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor() { this.value=''; this.children=[]; this.attrs={}; this.handlers={}; this.hidden=false; }
  addEventListener(name, fn) { this.handlers[name]=fn; }
  fire(name, event={}) { this.handlers[name]?.(event); }
  setAttribute(name,value) { this.attrs[name]=value; }
  removeAttribute(name) { delete this.attrs[name]; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  scrollIntoView() {}
  contains(element) { return element===this || fields.includes(element); }
}
const nodes = new Map();
const get = key => { if (!nodes.has(key)) nodes.set(key,new Element()); return nodes.get(key); };
const fields = [new Element(), new Element()];
get('#song').querySelector = selector => fields[selector.includes('title') ? 0 : 1];
const timers = new Map(), pending = []; let timerId=0;
const document = {querySelector:get, createElement:()=>new Element(), addEventListener() {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../radio/static/song-suggestions.js'),'utf8'), {
  document, URLSearchParams, AbortController,
  setTimeout(fn) { timers.set(++timerId,fn); return timerId; }, clearTimeout(id) { timers.delete(id); },
  fetch(url) { return new Promise(resolve => pending.push({url,resolve})); },
  MutationObserver: class { observe() {} },
});
const flush = async () => { const callbacks=[...timers.values()]; timers.clear(); callbacks.forEach(fn=>fn()); await new Promise(setImmediate); };
const respond = async (index, songs, ok=true) => { pending[index].resolve({ok,json:async()=>({songs})}); await new Promise(setImmediate); };
const key = name => { let prevented=false; fields[1].fire('keydown',{key:name,preventDefault(){prevented=true;}}); return prevented; };

(async () => {
  fields[0].value='He'; fields[0].fire('input');
  fields[0].value='Hello'; fields[0].fire('input');
  await flush(); assert.equal(pending.length,1,'typing is debounced');
  fields[1].value='Adele'; fields[1].fire('input'); await flush();
  assert.match(pending[1].url,/title=Hello&artist=Adele/);
  await respond(1,[{title:'Hello',artist:'Adele'}]);
  await respond(0,[{title:'Stale',artist:'Wrong'}]);
  const list=get('#song-suggestions');
  assert.equal(list.children[0].children[0].textContent,'Hello','stale response ignored');
  assert.equal(key('ArrowDown'),true);
  assert.equal(fields[1].attrs['aria-activedescendant'],'song-suggestion-0');
  assert.equal(key('Enter'),true,'selection does not submit request');
  assert.equal(fields[0].value,'Hello'); assert.equal(fields[1].value,'Adele'); assert.equal(list.hidden,true);
  fields[0].fire('input'); await flush();
  await respond(2,[{title:'Skyfall',artist:'Adele'}]); list.children[0].fire('click');
  assert.equal(fields[0].value,'Skyfall'); assert.equal(fields[1].value,'Adele');
  fields[0].fire('input'); await flush(); await respond(3,[],false);
  assert.match(get('#suggestion-status').textContent,/manually/);
  assert.equal(fields[0].value,'Skyfall','provider failures preserve manual entry');
  fields[0].fire('input'); await flush(); get('#song').fire('reset');
  await respond(4,[{title:'Old',artist:'Old'}]); assert.equal(list.hidden,true);
  console.log('Song suggestions: debounce, stale responses, keyboard/click selection, errors and reset passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
