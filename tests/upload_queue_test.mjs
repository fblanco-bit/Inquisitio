import fs from 'fs';
import assert from 'node:assert/strict';
const source = fs.readFileSync('/mnt/data/inquisitio_work/app/web/app.js','utf8');
const start = source.indexOf('// Separate queues preserve');
const endMarker = 'renderStagedFiles("update");';
const end = source.indexOf(endMarker,start) + endMarker.length;
assert(start>0 && end>start);
const nodes = new Map();
class Node {
  constructor(name='') {this.name=name; this.events={}; this.children=[]; this.files=[]; this.value=''; this.hidden=false; this.textContent=''; this.attributes={};}
  addEventListener(key,fn) {this.events[key]=fn;}
  setAttribute(key,val) {this.attributes[key]=val;}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren() {this.children=[];}
  fire(key,payload={}) { this.events[key]?.({currentTarget:this,preventDefault() {},dataTransfer:{files:[]},...payload}); }
  get classList() {return {add(){},remove(){}};}
}
const byId = name => {if(!nodes.has(name)) nodes.set(name,new Node(name));return nodes.get(name);};
const messages=[];
const document={createElement:tag=>new Node(tag)};
const make = (name,n) => ({name,size:n,lastModified:n});
const api = new Function('byId','toast','document',source.slice(start,end)+'; return {stagedEvidence,clearStagedFiles,addStagedFiles};')(byId,msg=>messages.push(msg),document);
const initialA=Array.from({length:6},(_,i)=>make(`202_${i+1}.pdf`,i+10));
const initialB=Array.from({length:8},(_,i)=>make(`205_${i+1}.pdf`,i+100));
byId('evidenceFiles').files=initialA;
byId('evidenceFiles').fire('change');
assert.equal(api.stagedEvidence.initial.length,6);
byId('evidenceFiles').files=initialB;
byId('evidenceFiles').fire('change');
assert.equal(api.stagedEvidence.initial.length,14);
assert.equal(byId('pendingEvidenceList').children.length,14);
byId('evidenceFiles').files=[initialA[0]];
byId('evidenceFiles').fire('change');
assert.equal(api.stagedEvidence.initial.length,14);
byId('pendingEvidenceList').children[0].children[1].fire('click');
assert.equal(api.stagedEvidence.initial.length,13);
byId('dropZone').fire('drop',{dataTransfer:{files:[initialA[0]]}});
assert.equal(api.stagedEvidence.initial.length,14);
byId('additionalEvidence').files=initialB;
byId('additionalEvidence').fire('change');
assert.equal(api.stagedEvidence.update.length,8);
byId('additionalEvidence').files=initialA;
byId('additionalEvidence').fire('change');
assert.equal(api.stagedEvidence.update.length,14);
byId('clearUpdateButton').fire('click');
assert.equal(api.stagedEvidence.update.length,0);
assert.equal(byId('updateFileSummary').textContent,'No additional PDFs selected');
assert(source.includes('const files = [...stagedEvidence.initial];'));
assert(source.includes('const files = [...stagedEvidence.update];'));
assert(source.includes('files.forEach(file => data.append("evidence", file, file.name));'));
console.log(JSON.stringify({test:'queue state through actual JS event handlers',result:'PASS',initial_batch_count:2,initial_files_queued:14,update_batches:2,duplicate_detection:'PASS',remove_and_readd:'PASS',clear_queue:'PASS',request_uses_queue:'PASS',browser_end_to_end:'BLOCKED_BY_ADMINISTRATOR'},null,2));
