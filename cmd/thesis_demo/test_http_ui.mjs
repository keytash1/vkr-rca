import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const source = readFileSync(new URL('./static/app.js', import.meta.url), 'utf8');
const left = source.indexOf('function renderHttpEvidence(');
const right = source.indexOf('function renderEvidence(', left);
function render(observations, status = 'OBSERVED') {
  const element = () => ({children: [], append(...children) {this.children.push(...children);}});
  const parent = element();
  const context = {document: {createElement: element},
    state: {catalog: {observations, source_quality: {http_observations: {services: {alpha: status}, lookback_seconds: 30}}}},
    textElement: (tag, text) => ({tag, text}), metricChart: () => ({tag: 'svg'}), sourceLinks: () => ({tag: 'links'})};
  vm.runInNewContext(source.slice(left, right) + '\nrenderHttpEvidence;', context)(parent, 'alpha');
  return parent.children;
}
const fact = (family, unit, median, state = 'OBSERVED') => ({service: 'alpha', kind: 'metric',
  values: {family, unit, median, min: median, max: median, state, samples: median == null ? 0 : 3}});
test('legacy view stays unchanged; one HTTP group is collapsed by default', () => {
  assert.deepEqual(render([]), []);
  const boxes = render([fact('http_request_rate', 'requests_per_second', 5)]);
  assert.equal(boxes.length, 1); assert.notEqual(boxes[0].open, true);
  assert.match(JSON.stringify(boxes), /В расчёт рейтинга не входят/);
  assert.match(JSON.stringify(boxes), /до начала выбранного интервала/);
});
test('ratios are percentages, seconds become milliseconds, not model confidence', () => {
  const text = JSON.stringify(render([fact('http_error_ratio', 'ratio', .25), fact('http_latency_p95', 'seconds', .1)]));
  assert.match(text, /25 %/); assert.match(text, /100 мс/);
  assert.match(text, /не общий p95 всего интервала/);
  assert.doesNotMatch(text, /уверенност/);
});
test('no activity is undefined for latency, source outages are never zero', () => {
  const idle = JSON.stringify(render([fact('http_latency_p95', 'seconds', null, 'NOT_DEFINED_WITHOUT_TRAFFIC')], 'NO_ACTIVITY'));
  assert.match(idle, /нет запросов/); assert.match(idle, /не определено/);
  assert.match(idle, /не нулевая задержка/);
  const down = JSON.stringify(render([fact('http_request_rate', 'requests_per_second', null, 'UNAVAILABLE')], 'UNAVAILABLE'));
  assert.match(down, /источник недоступен/); assert.doesNotMatch(down, /0 запр/);
});
test('roundoff-level p95 differences do not fill the chart height', () => {
  const element = () => ({children:[], attributes:{}, setAttribute(key,value) {this.attributes[key]=value;},
    append(child) {this.children.push(child);}});
  const context = {document:{createElementNS:element}};
  const chart = vm.runInNewContext(source.slice(source.indexOf('function metricChart('),left)+'\nmetricChart;',context);
  const point = (stamp,value) => ({start_unix:stamp,end_unix:stamp,min:value,max:value,mean:value});
  const svg = chart({start_unix:100,end_unix:102,values:{family:'http_latency_p95',unit:'seconds',
    series:[point(100,.00475),point(102,.004750000000000001)]}},'p95');
  const ys = svg.children[0].attributes.points.split(' ').map(point=>Number(point.split(',')[1]));
  assert.ok(Math.abs(ys[1]-ys[0]) < .01);
});
