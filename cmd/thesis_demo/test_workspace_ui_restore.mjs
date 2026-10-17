// Focused production-function harness, not a DOM/browser substitute. The real
// invalid-interval -> history -> restore transition is also checked in browser.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function section(file, start, end) {
  const source=readFileSync(new URL(file,import.meta.url),'utf8');
  const left=source.indexOf(start), right=source.indexOf(end,left+start.length);
  assert.ok(left>=0 && right>left,'production function boundaries changed; update harness');
  return source.slice(left,right);
}
const reset=section('./static/app.js','function resetError() {','function clearResult() {');
const choose=section('./static/workspace.js','  async function choose(value) {','  async function history() {');

function harness() {
  const fields=Array.from({length:2},()=>({attributes:{'aria-invalid':'true','aria-describedby':'old-error'},
    removeAttribute(key) { delete this.attributes[key]; }}));
  const errors=fields.map(()=>({hidden:false}));
  const elements={'analysis-error':{hidden:false},'request-status':{textContent:''},
    'profile-select':{options:[{value:'system'}],value:''},
    'start-time':{value:''},'end-time':{value:''},'investigation-question':{value:''}};
  const loaded={analysis:{profile_id:'system',start_unix:1700000000,end_unix:1700000030}};
  const context={generation:0,restoring:false,snapshot:null,session:null,
    activeStates:new Set(),api:async()=>loaded,
    rememberDraft(){},clearTimer(){},renderRanking(){},renderOutcome(){},renderRecord(){},controls(){},
    poll(){throw new Error('completed snapshot must not start polling');},
    el:id=>elements[id],$:selector=>elements[selector.slice(1)],
    $$:selector=>selector==='[aria-invalid]' ? fields : errors};
  const restore=vm.runInNewContext(reset+choose+'\nchoose;',context);
  return {context,restore,elements,fields,errors};
}
const record={id:'known',analysis_id:'saved',state:'completed',request:{question:'Known saved question'}};

test('successful restore clears all stale validation, not just the general alert',async()=>{
  const h=harness(); await h.restore(record);
  assert.equal(h.elements['analysis-error'].hidden,true);
  assert.ok(h.errors.every(error=>error.hidden));
  assert.ok(h.fields.every(field=>!('aria-invalid' in field.attributes) && !('aria-describedby' in field.attributes)));
  assert.equal(h.elements['profile-select'].value,'system');
  assert.equal(h.context.session,record);
  assert.match(h.elements['request-status'].textContent,/Открыто сохранённое расследование/);
});

test('failed snapshot read does not pretend the invalid form was restored',async()=>{
  const h=harness(); h.context.api=async()=>{throw new Error('snapshot unavailable');};
  await assert.rejects(h.restore(record),/snapshot unavailable/);
  assert.equal(h.elements['analysis-error'].hidden,false);
  assert.equal(h.context.session,null);
});

test('superseded restoration does not clear the newer request validation',async()=>{
  const h=harness(), fetchSnapshot=h.context.api;
  h.context.api=async()=>{h.context.generation++; return fetchSnapshot();};
  await h.restore(record);
  assert.equal(h.elements['analysis-error'].hidden,false);
  assert.equal(h.context.session,null);
});

test('adopting a proposal creates an unassigned draft with a separate verification plan',()=>{
  const source=section('./static/workspace.js','  function actionFromProposal(proposal, legend) {','  function readRecord() {');
  const make=vm.runInNewContext(source+'\nactionFromProposal;',{
    crypto:{randomUUID:()=> 'new-human-draft'},text:value=>value});
  const proposal={service:'alpha',purpose:'preventive',title:'Conditional change',rationale:'Observed pattern',
    verification_plan:'Compare timeouts under representative load',evidence_ids:['obs-1']};
  const draft=make(proposal,{});
  assert.equal(draft.status,'proposed'); assert.equal(draft.owner,''); assert.equal(draft.due_unix,null);
  assert.equal(draft.verification,''); assert.equal(draft.verification_plan,proposal.verification_plan);
  assert.equal(draft.purpose,'preventive'); assert.equal(draft.service,'alpha');
  draft.evidence_ids.push('obs-2'); assert.deepEqual(proposal.evidence_ids,['obs-1']);
  assert.equal('executed' in draft,false);
});

test('Markdown export keeps draft/verification distinctions and escapes injected structure',()=>{
  const source=section('./static/workspace.js','  function investigationMarkdown(value, savedSnapshot) {','  function epoch(value) {');
  const render=vm.runInNewContext(source+'\ninvestigationMarkdown;');
  const record={title:'![tracking](https://evil.invalid/i)\n# forged heading',symptoms:'<script>alert(1)</script>',impact:'unknown',conclusion:'Unresolved',timeline:[],causes:[],
    action_items:[{title:'Conditional measure',purpose:'preventive',status:'proposed',owner:'',due_unix:null,importance:'normal',effort:'unknown',verification_plan:'Repeat test',verification:'',evidence_ids:[]}]};
  const md=render({id:'unit',project:'alpha',revision:1,record},{analysis:{start_unix:1000,end_unix:1030},snapshot_sha256:'abc'});
  assert.match(md,/Черновик/); assert.match(md,/План проверки эффекта: Repeat test/);
  assert.match(md,/Фактический результат проверки: Не указано/);
  assert.ok(!md.includes('![tracking]')); assert.ok(!md.includes('<script>')); assert.ok(!md.includes('\n# forged'));
  assert.ok(md.includes('\\!\\[tracking\\]')); assert.ok(md.includes('\\<script\\>'));
});
