const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor(){this.handlers={};this.attrs={};this.volume=1;this.muted=false;this.open=false;}
  addEventListener(event, fn){this.handlers[event]=fn;}
  setAttribute(key,value){this.attrs[key]=value;}
  append(child){child.parent=this;}
  prepend(child){child.parent=this;}
  showModal(){this.open=true;}
  close(){this.open=false;}
  focus(){this.focused=true;}
  getBoundingClientRect(){return {left:0,right:300,top:0,bottom:800};}
}
const nodes=new Map();
const get=key=>{if(!nodes.has(key))nodes.set(key,new Element());return nodes.get(key);};
const media={matches:true,addEventListener(event,fn){this.change=fn;}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../radio/static/player-controls.js'),'utf8'),{
  document:{querySelector:get},matchMedia:()=>media,
});
assert.equal(get('.sidebar').parent,get('#station-drawer'));
get('#stations-open').handlers.click();assert.equal(get('#station-drawer').open,true);
assert.equal(get('#stations-close').focused,true);
get('#stations').handlers.click({target:{closest:s=>s==='.station-card'?{}:null}});
assert.equal(get('#station-drawer').open,false);
get('#stations-open').handlers.click();media.matches=false;media.change();
assert.equal(get('#station-drawer').open,false);assert.equal(get('.sidebar').parent,get('.shell'));
get('#volume').value='0.3';get('#volume').handlers.input();assert.equal(get('#audio').volume,0.3);
get('#mute').handlers.click();assert.equal(get('#audio').muted,true);assert.equal(get('#mute').textContent,'Unmute');
get('#volume').value='0';get('#volume').handlers.input();get('#mute').handlers.click();
assert.equal(get('#audio').volume,0.5);assert.equal(get('#audio').muted,false);
console.log('Player controls passed: drawer placement, opening, selection, resizing, volume and mute.');
