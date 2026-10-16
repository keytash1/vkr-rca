const state = {examples: [], profiles: [], current: null, busy: false};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function request(path, options) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 150000);
  let response, data;
  try {
    response = await fetch(path, {...options, signal: controller.signal});
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Приложение вернуло ответ другого формата. Проверьте адрес и настройки доступа.');
    }
    data = await response.json();
  } catch (reason) {
    if (reason.name === 'AbortError') throw new Error('Время ожидания ответа истекло. Сервер может ещё завершать расчёт; проверьте его состояние перед повтором.');
    if (reason instanceof TypeError) throw new Error('Нет связи с приложением. Проверьте, запущен ли сервер, и повторите запрос.');
    throw reason;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    const error = new Error(data.error || `Ошибка HTTP ${response.status}`);
    error.code = data.code; error.fields = data.fields || []; error.requestId = data.request_id;
    throw error;
  }
  return data;
}

function setBusy(busy) {
  state.busy = busy;
  $$('.input-card input, .input-card select, .input-card button').forEach(control => {control.disabled = busy;});
  $('#analysis').setAttribute('aria-busy', String(busy));
  $('#request-status').textContent = busy ? 'Получаем телеметрию и рассчитываем рейтинг…' : '';
}

function showError(reason) {
  const error = $('#analysis-error'); error.replaceChildren();
  const message = document.createElement('p'); message.textContent = reason.message || String(reason);
  error.append(message);
  if (reason.requestId) {
    const reference = document.createElement('small'); reference.textContent = `Код: ${reason.code} · запрос ${reason.requestId}`;
    error.append(reference);
  }
  const fields = {profile_id: '#profile-select', start_unix: '#start-time', end_unix: '#end-time'};
  const messages = {profile_id: '#profile-field-error', start_unix: '#start-field-error', end_unix: '#end-field-error'};
  for (const name of reason.fields || []) if (fields[name]) {
    $(fields[name]).setAttribute('aria-invalid', 'true');
    $(fields[name]).setAttribute('aria-describedby', messages[name].slice(1));
    $(messages[name]).textContent = reason.message; $(messages[name]).hidden = false;
  }
  error.hidden = false; error.focus();
}

function resetError() {
  $('#analysis-error').hidden = true;
  $$('[aria-invalid]').forEach(control => {control.removeAttribute('aria-invalid'); control.removeAttribute('aria-describedby');});
  $$('.field-error').forEach(message => {message.hidden = true;});
}

function clearResult() {
  state.current = null;
  if (!state.busy) $('#request-status').textContent = '';
  $('#export-result').hidden = true;
  $('#incident-label').textContent = 'Выберите систему и интервал для анализа.';
  $('#candidate-count').textContent = '—';
  $('#candidate-count').hidden = true;
  $('#service-detail').hidden = true;
  $('#result-tools').hidden = true;
  $('#result-note').hidden = true;
  $('#coverage-warning').hidden = true;
  $('#ranking').innerHTML = '<div class="empty-state">После расчёта здесь появится полный рейтинг сервисов.</div>';
  $('#detail-title').textContent = 'Наблюдения по выбранному сервису';
  $('#detail').innerHTML = '<div class="empty-state">Основания появятся после анализа.</div>';
}

function renderCandidate(candidate) {
  $('#detail-title').textContent = `${candidate.service} · место ${candidate.rank}`;
  const values = candidate.evidence;
  const signals = [
    ['Отклонение метрик', values.metric_support],
    ['Локальные признаки трассировок', values.trace_local_support],
    ['Распространение симптомов', values.propagation_support],
    ['Ожидание зависимостей', values.dependency_wait_support],
    ['Исчезновение активности', values.disappearance_support],
  ];
  const detail = $('#detail');
  detail.replaceChildren();
  const coverage = document.createElement('p'); coverage.className = 'coverage-line';
  for (const text of [`Семейства метрик: ${Math.round(Number(values.coverage.metrics) * 4)} из 4`,
    `Спаны сервиса: ${Number(values.coverage.traces) > 0 ? 'наблюдаются' : 'не наблюдаются'}`,
    `Граф вызовов: ${Number(values.coverage.topology) > 0 ? 'есть наблюдаемые связи' : 'нет наблюдаемых связей'}`]) {
    const item = document.createElement('span');
    item.textContent = text;
    coverage.append(item);
  }
  detail.append(coverage);
  const summary = document.createElement('details');
  const toggle = document.createElement('summary'); toggle.textContent = 'Диагностические показатели'; summary.append(toggle);
  const signalsTable = document.createElement('table'); signalsTable.className = 'observation-table';
  for (const [label, value] of signals) {
    const row = document.createElement('tr');
    const title = document.createElement('th'); title.scope = 'row'; title.textContent = label;
    const number = document.createElement('td'); number.textContent = Number(value).toFixed(3);
    row.append(title, number); signalsTable.append(row);
  }
  const note = document.createElement('p');
  note.className = 'detail-note';
  note.textContent = 'Это наблюдения, доступные для проверки инженером, а не причинное объяснение и не доли вклада модели.';
  summary.append(signalsTable, note); detail.append(summary);
  const observations = candidate.observations;
  if (observations) {
    const heading = document.createElement('h3');
    heading.textContent = 'Сводка исходных наблюдений';
    detail.append(heading);
    const traceLine = document.createElement('p');
    const traceStatus = state.current?.source_status?.traces;
    traceLine.textContent = traceStatus === 'unavailable'
      ? 'Трассировки: источник недоступен; ноль наблюдений не означает отсутствие вызовов.'
      : `Трассировки: ${observations.traces.count} спанов, из них с ошибкой — ${observations.traces.errors}.`;
    detail.append(traceLine);
    const table = document.createElement('table');
    table.className = 'observation-table';
    const header = document.createElement('tr');
    for (const label of ['Метрика', 'Отсчётов', 'Медиана', 'Диапазон']) {
      const cell = document.createElement('th'); cell.textContent = label; header.append(cell);
    }
    table.append(header);
    const names = {cpu: 'CPU, ядра', memory: 'Память, МиБ', network: 'Сетевой обмен, КиБ/с', traffic_rate: 'Входящий трафик, КиБ/с'};
    for (const [family, values] of Object.entries(observations.metrics)) {
      const divisor = values.unit === 'bytes' ? 1024 ** 2 : values.unit === 'bytes_per_second' ? 1024 : 1;
      const display = value => Number(value / divisor).toLocaleString('ru-RU', {maximumFractionDigits: family === 'cpu' ? 5 : 3});
      const row = document.createElement('tr');
      for (const value of [names[family] || family, String(values.samples),
        display(values.median), `${display(values.min)}–${display(values.max)}`]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      table.append(row);
    }
    if (Object.keys(observations.metrics).length) {
      const scroll = document.createElement('div'); scroll.className = 'table-scroll';
      scroll.append(table); detail.append(scroll);
    }
    else {
      const missing = document.createElement('p');
      missing.textContent = 'По этому сервису метрики в выбранном интервале отсутствуют.';
      detail.append(missing);
    }
  }
}

function renderRanking(data) {
  state.current = data;
  $('#export-result').hidden = false;
  $('#result-tools').hidden = false;
  $('#result-note').hidden = false;
  $('#service-detail').hidden = false;
  $('#candidate-count').hidden = false;
  const provenance = $('#result-provenance'); provenance.replaceChildren();
  for (const [label, value] of [['Профиль', data.profile_id || 'Контрольное воспроизведение'],
    ['Экземпляров ранжировщика', data.model_count], ['SHA-256 входа', data.input_sha256 || data.source_status?.input_sha256 || 'Не указан']]) {
    const term = document.createElement('dt'); term.textContent = label;
    const definition = document.createElement('dd'); definition.textContent = String(value);
    provenance.append(term, definition);
  }
  const selected = state.examples.find(item => item.id === data.incident_id);
  const profile = state.profiles.find(item => item.id === data.profile_id);
  const start = new Date(data.start_unix * 1000).toISOString().replace('T', ' ').slice(0, 19);
  const end = new Date(data.end_unix * 1000).toISOString().replace('T', ' ').slice(0, 19);
  const source = profile?.title || selected?.title || 'Контрольное окно';
  const traces = data.source_status?.traces === 'unavailable' ? ' · трассировки недоступны' : '';
  const incomplete = data.source_status?.metric_families_by_service &&
    Object.values(data.source_status.metric_families_by_service).some(families => families.length < 4)
    ? ' · метрики неполны' : '';
  $('#incident-label').textContent = `${source} · ${start}–${end} UTC${traces}${incomplete}`;
  const serviceWord = {one: 'сервис', few: 'сервиса', many: 'сервисов', other: 'сервиса'}[new Intl.PluralRules('ru').select(data.candidate_count)];
  $('#candidate-count').textContent = `${data.candidate_count} ${serviceWord}`;
  const warning = $('#coverage-warning');
  const families = Object.values(data.source_status?.metric_families_by_service || {});
  const complete = families.filter(item => item.length === 4).length;
  const messages = [];
  if (families.length && complete < families.length) messages.push(
    `Полные метрики доступны для ${complete} из ${families.length} сервисов.`);
  if (data.source_status?.traces === 'unavailable') messages.push('Источник трассировок недоступен. Рейтинг рассчитан с неполными наблюдениями.');
  else if (data.source_status?.span_count === 0) messages.push('В выбранном интервале нет наблюдаемых спанов.');
  else if (data.source_status?.services_without_spans?.length) messages.push(
    `Нет спанов для: ${data.source_status.services_without_spans.join(', ')}. Проверьте активность и инструментирование этих сервисов.`);
  for (const item of data.source_status?.annotations || []) messages.push(`${item.family}: ${item.message}`);
  const pointCoverage = Object.values(data.source_status?.metric_point_coverage || {});
  if (pointCoverage.some(item => Object.values(item).some(value => value < 0.8))) {
    messages.push('В части метрических рядов получено менее 80% ожидаемых отсчётов. Проверьте временное покрытие источника.');
  }
  warning.hidden = !messages.length;
  warning.textContent = messages.join(' ');
  const list = $('#ranking'); list.replaceChildren();
  for (const candidate of data.candidates) {
    const row = document.createElement('button');
    row.type = 'button'; row.className = 'rank-row';
    const rank = document.createElement('span'); rank.className = 'rank-number'; rank.textContent = `#${candidate.rank}`;
    const name = document.createElement('span'); name.className = 'rank-name'; name.textContent = candidate.service;
    const score = document.createElement('span'); score.className = 'rank-score'; score.textContent = `балл ${Number(candidate.model_score).toFixed(3)}`;
    row.append(rank, name, score);
    row.addEventListener('click', () => {
      $$('.rank-row').forEach(item => {item.classList.remove('selected'); item.setAttribute('aria-pressed', 'false');});
      row.classList.add('selected'); row.setAttribute('aria-pressed', 'true'); renderCandidate(candidate);
    });
    list.append(row);
  }
  list.firstElementChild?.click();
}

function bindTabs() {
  $$('.tab').forEach(button => button.addEventListener('click', () => {
    $$('.tab').forEach(item => {item.classList.remove('active'); item.removeAttribute('aria-current');});
    $$('.view').forEach(item => item.classList.remove('active'));
    button.classList.add('active'); button.setAttribute('aria-current', 'page');
    $(`#${button.dataset.tab}`).classList.add('active');
  }));
}

async function analyzeLive() {
  if (state.busy) return;
  const error = $('#analysis-error'); resetError();
  setBusy(true);
  const button = $('#analyze'); button.textContent = 'Выполняется анализ…';
  try {
    const profileId = $('#profile-select').value;
    const start = $('#start-time').value;
    const end = $('#end-time').value;
    if (!profileId || !start || !end) {
      const reason = new Error('Выберите систему и обе границы интервала.');
      reason.fields = [!profileId && 'profile_id', !start && 'start_unix', !end && 'end_unix'].filter(Boolean);
      throw reason;
    }
    const startUnix = new Date(start).getTime() / 1000;
    const endUnix = new Date(end).getTime() / 1000;
    if (!Number.isFinite(startUnix) || !Number.isFinite(endUnix) || endUnix <= startUnix) {
      const reason = new Error('Конец интервала должен быть позже начала.');
      reason.fields = ['start_unix', 'end_unix']; throw reason;
    }
    clearResult();
    const result = await request('/api/analyze', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({profile_id: profileId, start_unix: startUnix, end_unix: endUnix})
    });
    renderRanking(result);
    $('#request-status').textContent = 'Расчёт завершён. Рейтинг и наблюдения доступны ниже.';
  } catch (reason) {
    showError(reason); clearResult();
  } finally {
    const status = $('#request-status').textContent;
    setBusy(false); $('#request-status').textContent = error.hidden ? status : '';
    button.textContent = 'Рассчитать рейтинг';
  }
}

async function analyzeReplay() {
  if (state.busy) return;
  const error = $('#analysis-error'); resetError();
  setBusy(true);
  const button = $('#replay-analyze'); button.textContent = 'Воспроизведение…';
  try {
    const file = $('#incident-file').files[0];
    const payload = file ? {incident: JSON.parse(await file.text())} : {example_id: $('#example-select').value};
    if (!file && !payload.example_id) throw new Error('Выберите сохранённый случай или канонический файл.');
    clearResult();
    const result = await request('/api/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    renderRanking(result);
  } catch (reason) {
    showError(reason); clearResult();
  } finally {
    setBusy(false); button.textContent = 'Воспроизвести рейтинг';
  }
}

function setInitialTime() {
  const now = new Date();
  const local = date => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  $('#end-time').value = local(now);
  $('#start-time').value = local(new Date(now.getTime() - 60000));
}

async function initialize() {
  bindTabs();
  $('#diagnosis-form').addEventListener('submit', event => {event.preventDefault(); analyzeLive();});
  $$('[data-minutes]').forEach(button => button.addEventListener('click', () => {
    const end = new Date(Date.now() - 20000);
    const local = date => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    $('#end-time').value = local(end);
    $('#start-time').value = local(new Date(end.getTime() - Number(button.dataset.minutes) * 60000));
    clearResult();
  }));
  $('#time-hint').textContent = `Часовой пояс: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Быстрый выбор заканчивает интервал 20 секунд назад; учитывайте задержку ваших источников.`;
  $('#replay-analyze').addEventListener('click', analyzeReplay);
  $('#export-result').addEventListener('click', () => {
    if (!state.current) return;
    const blob = new Blob([JSON.stringify(state.current, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = `diagnosis-${state.current.result_id || state.current.incident_id}.json`; link.click();
    URL.revokeObjectURL(url);
  });
  setInitialTime();
  for (const selector of ['#profile-select', '#start-time', '#end-time']) {
    $(selector).addEventListener('change', clearResult);
  }
  $('#example-select').addEventListener('change', () => {$('#incident-file').value = ''; clearResult();});
  $('#incident-file').addEventListener('change', () => {$('#example-select').value = ''; clearResult();});
  try {
    const [health, profiles] = await Promise.all([request('/api/health'), request('/api/profiles')]);
    $('#readiness').textContent = health.model_count
      ? `Модель загружена · источники проверяются при запросе`
      : 'Требуется настройка системы';
    const failed = Object.keys(health.profile_errors || {});
    if (failed.length) {
      const error = $('#analysis-error'); error.hidden = false;
      error.textContent = `Требуется исправить профили: ${failed.join(', ')}. Интегратору: проверьте конфигурацию и базовое состояние.`;
    }
    state.profiles = profiles;
    const profileSelect = $('#profile-select'); profileSelect.replaceChildren();
    const profilePlaceholder = document.createElement('option'); profilePlaceholder.value = '';
    profilePlaceholder.textContent = profiles.length ? 'Выберите систему' : 'Нет настроенных систем';
    profileSelect.append(profilePlaceholder);
    for (const profile of profiles) {
      const option = document.createElement('option'); option.value = profile.id; option.textContent = profile.title;
      profileSelect.append(option);
    }
    const examples = health.examples ? await request('/api/examples') : [];
    state.examples = examples;
    if (!examples.length) $('.replay-panel').hidden = true;
    const select = $('#example-select'); select.replaceChildren();
    const placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = 'Выберите инцидент'; select.append(placeholder);
    for (const example of examples) {
      const option = document.createElement('option'); option.value = example.id; option.textContent = example.title; select.append(option);
    }
    if (health.experiment_available) {
      const results = await request('/api/results');
      const checks = [
        ['Accuracy@1', results.method.ac_at_1, results.metric_comparator.ac_at_1],
        ['Accuracy@3', results.method.ac_at_3, results.metric_comparator.ac_at_3],
        ['Accuracy@5', results.method.ac_at_5, results.metric_comparator.ac_at_5],
        ['MRR', results.method.mrr, results.metric_comparator.mrr],
      ];
      for (const [label, current, baseline] of checks) {
        const card = document.createElement('div'); card.className = 'metric';
        const name = document.createElement('span'); name.textContent = label;
        const value = document.createElement('strong'); value.textContent = Number(current).toFixed(2);
        const note = document.createElement('small'); note.textContent = `Метрическая эвристика: ${Number(baseline).toFixed(2)}`;
        card.append(name, value, note); $('#metrics').append(card);
      }
      for (const line of results.limitations) {
        const item = document.createElement('li'); item.textContent = line; $('#limitations').append(item);
      }
    } else {
      document.querySelector('[data-tab="evaluation"]').hidden = true;
    }
  } catch (reason) {
    $('#readiness').textContent = 'Ошибка запуска';
    const error = $('#analysis-error'); error.textContent = reason.message || String(reason); error.hidden = false;
  }
}

document.addEventListener('DOMContentLoaded', initialize);
