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

test('investigation shortcuts open the requested section without changing the record',()=>{
  const source=section('./static/workspace.js','  function openWorkspace(', '  function rememberDraft()');
  for (const choice of ['investigation','history','unavailable']) {
    const calls=[],elements={};
    for (const id of ['workspace-details','investigation-history']) elements[id]={open:false,
      scrollIntoView(){calls.push(`scroll:${id}`);},querySelector(){return {focus(){calls.push(`focus:${id}`);}};}};
    elements['investigation-workspace']={hidden:choice==='unavailable'};
    const context={el:id=>elements[id],document:{querySelector(){return {click(){calls.push('analysis');}};}}};
    vm.runInNewContext(source+'\nopenWorkspace;',context)(choice==='history');
    assert.equal(elements['workspace-details'].open,choice==='investigation');
    assert.equal(elements['investigation-history'].open,choice==='history');
    assert.equal(calls.length,choice==='unavailable'?0:3);
  }
});

test('compact disclosure keeps all engineer fields in the same saved form',()=>{
  const html=readFileSync(new URL('./static/index.html',import.meta.url),'utf8');
  assert.match(html,/<details id="workspace-details">/);
  assert.ok(html.indexOf('id="investigation-error"')<html.indexOf('<details id="workspace-details">'),'workspace errors must remain visible when details are collapsed');
  assert.match(html,/<details class="record-context">/);
  const form=html.slice(html.indexOf('<form id="investigation-record"'),html.indexOf('</form>',html.indexOf('<form id="investigation-record"')));
  for (const name of ['title','meta_owner','meta_incident','meta_category','impact','symptoms','conclusion'])
    assert.equal((form.match(new RegExp(`name="${name}"`,'g'))||[]).length,1,name);
  assert.match(form,/id="record-actions"/);
});

test('measure details retain every field and expose verification when its status requires it',()=>{
  const source=section('./static/workspace.js','  function renderRows() {','  function renderRecord() {');
  for (const status of ['proposed','verification_pending','verified','not_verified']) {
    const node=()=>({children:[],append(...children){this.children.push(...children);},replaceChildren(){this.children=[];}});
    const containers=Object.fromEntries(['record-timeline','record-causes','record-actions'].map(id=>[id,node()]));
    const item={title:'Measure',purpose:'preventive',owner:'Engineer',due_unix:null,status,importance:'high',effort:'small',
      service:'alpha',rationale:'Observed',verification_plan:'Repeat',verification:'Result',ticket:'T-1',evidence_ids:['obs-1']};
    const fields=new Map(),context={el:id=>containers[id],record:{timeline:[],causes:[],action_items:[item]},
      document:{createElement:node},snapshot:{catalog:{services:['alpha']}},localDate:()=>'',epoch:()=>null,
      field(parent,label,value,change){fields.set(label,{parent,value,change});},
      chooseReferences(parent,value){assert.equal(value,item);},rowRemove(){}};
    vm.runInNewContext(source+'\nrenderRows;',context)();
    const row=containers['record-actions'].children[0],details=row.children[0],extra=details.children[1];
    assert.equal(fields.size,12);
    assert.equal(details.open,status!=='proposed');
    for (const label of ['Мера','Назначение','Ответственный','Срок','Статус']) assert.equal(fields.get(label).parent,row);
    for (const label of ['Основание меры','План проверки эффекта','Результат проверки эффекта','Сервис','Тикет (номер или ссылка)','Важность','Трудоёмкость']) assert.equal(fields.get(label).parent,extra);
    fields.get('Статус').change('verification_pending'); assert.equal(details.open,true);
    fields.get('Результат проверки эффекта').change('Checked'); assert.equal(item.verification,'Checked');
  }
});

test('download keeps an attached fallback link alive until explicitly replaced',()=>{
  const source=section('./static/workspace.js','  let downloadUrl = null;','  async function exportInvestigation() {');
  const box={hidden:true,children:[],replaceChildren(){this.children=[];},append(...nodes){this.children.push(...nodes);}};
  const revoked=[],links=[];
  const context={el:()=>box,Blob,URL:{createObjectURL:()=>`blob:${links.length}`,revokeObjectURL:x=>revoked.push(x)},
    document:{createElement:()=>{const link={click(){assert.ok(box.children.includes(link));}};links.push(link);return link;},createTextNode:x=>x}};
  const make=vm.runInNewContext(source+'\nprepareDownload;',context);
  make('one','one.md','text/markdown');
  assert.equal(box.hidden,false);assert.equal(links[0].download,'one.md');assert.deepEqual(revoked,[]);
  make('two','two.json','application/json');
  assert.deepEqual(revoked,['blob:1']);assert.equal(box.children.length,2);
});

test('export refuses stale revisions, unsaved edits and a superseded investigation',async()=>{
  const source=section('./static/workspace.js','  async function exportInvestigation() {','  // Object key order');
  for (const problem of ['none','stale','edited','switched']) {
    const saved={id:'card',revision:2,record:{title:'saved'}};
    const downloads=[],errors=[];
    const context={session:saved,generation:1,snapshot:{id:'original-snapshot'},el:()=>({value:'json'}),
      readRecord:()=>({title:problem==='edited' ? 'unsaved' : 'saved'}),sameRecord:(a,b)=>JSON.stringify(a)===JSON.stringify(b),
      api:async()=>{if(problem==='switched')context.generation++;return {...saved,revision:problem==='stale'?3:2};},
      prepareDownload:(...args)=>downloads.push(args),message:e=>errors.push(e.message)};
    await vm.runInNewContext(source+'\nexportInvestigation;',context)();
    assert.equal(downloads.length,problem==='none'?1:0,problem);
    assert.equal(errors.length,['stale','edited'].includes(problem)?1:0,problem);
    if(downloads.length)assert.equal(JSON.parse(downloads[0][0]).snapshot.id,'original-snapshot');
  }
});

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
    rememberDraft(){},clearTimer(){},renderRanking(){},renderOutcome(){},renderRecord(){},controls(){},openWorkspace(){},
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
