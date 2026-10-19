import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source=readFileSync(new URL('./static/app.js',import.meta.url),'utf8');
const left=source.indexOf('function renderBaselineApplicability(');
const right=source.indexOf('async function loadEvidence(',left);
assert.ok(left>=0 && right>left);

function render(assessment) {
  const element=()=>({children:[],append(...items){this.children.push(...items);}});
  const parent=element();
  const context={document:{createElement:element},textElement(tag,text){return {tag,text};}};
  vm.runInNewContext(source.slice(left,right)+'\nrenderBaselineApplicability;',context)(parent,assessment);
  return parent.children;
}

test('old snapshots need no new field; real concerns open without a probability',()=>{
  assert.deepEqual(render(undefined),[]);
  for (const reason of ['HEALTHY_PERIOD_AFTER','HEALTHY_PERIOD_OVERLAPS','LOAD_DIFFERS_FROM_SINGLE_REFERENCE']) {
    const [box]=render({state:'REVIEW_REQUIRED',reference_rps:5,current_rps:50,reasons:[reason]});
    assert.equal(box.open,true);
    assert.match(JSON.stringify(box),/Опорная интенсивность/);
    assert.match(JSON.stringify(box),/Рейтинг не изменён/);
    assert.doesNotMatch(JSON.stringify(box),/уверенность|100%/i);
  }
});

test('configuration warning is concise and unknown messages are never interpreted as HTML',()=>{
  const [box]=render({state:'REVIEW_REQUIRED',reasons:['CURRENT_LOAD_CONFIGURED_NOT_MEASURED','<img onerror=alert(1)>']});
  assert.equal(box.open,undefined);
  assert.match(JSON.stringify(box),/Фактическое изменение трафика/);
  assert.doesNotMatch(JSON.stringify(box),/onerror/);
});
