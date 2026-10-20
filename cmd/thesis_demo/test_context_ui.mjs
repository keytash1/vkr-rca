import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const source=readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const left=source.indexOf('function renderIncidentContext('),right=source.indexOf('function renderBaselineApplicability(',left);
function render(values) {
 const element=()=>({children:[],append(...x){this.children.push(...x);}}),parent=element();
 const context={document:{createElement:element},textElement(tag,text){return {tag,text};}};
 vm.runInNewContext(source.slice(left,right)+'\nrenderIncidentContext;',context)(parent,values?{id:'obs-test',values}:null);
 return parent.children;
}
test('no context leaves old UI unchanged; incomplete context is visible',()=>{
 assert.deepEqual(render(null),[]);
 for(const status of ['unavailable','truncated']) {
  const [box]=render({source_status:status,record_count:0});assert.equal(box.open,true);
  assert.match(JSON.stringify(box),/Пустой ответ не доказывает/);
 }
});
test('useful checks, consent distinction and source text stay plain text',()=>{
 const [box]=render({source_status:'available',record_count:1,categories:['CONNECTION_REFUSED'],
  records:[{source_timestamp_ns:'101000000000',fields:{'error.type':'<script>unsafe</script>'}}]});
 const text=JSON.stringify(box);assert.match(text,/слушающий порт/);assert.match(text,/помощнику не передаётся/);
 assert.match(text,/1970-01-01 00:01:41/);assert.equal(box.open,undefined);
});
test('preceding runtime records stay separate and SIGKILL is not presented as OOM',()=>{
 const [box]=render({source_status:'available',record_count:1,lookback_seconds:60,preceding_record_count:1,
  categories:['EXIT_EVENT'], records:[{period:'BEFORE_INCIDENT',source_timestamp_ns:'101000000000',fields:{'container.exit_code':137}}]});
 const text=JSON.stringify(box);assert.match(text,/до инцидента/);assert.match(text,/не подтверждает OOM/);
 assert.match(text,/Интервал расчёта рейтинга не расширен/);assert.equal(box.open,undefined);
});
