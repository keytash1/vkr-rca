const state = {examples: [], profiles: [], current: null};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Ошибка HTTP ${response.status}`);
  return data;
}

function clearResult() {
  state.current = null;
  $('#incident-label').textContent = 'Выберите систему и интервал для анализа.';
  $('#candidate-count').textContent = '—';
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
    ['Доступность метрик', values.coverage.metrics],
    ['Доступность трассировок', values.coverage.traces],
    ['Доступность связей', values.coverage.topology],
  ];
  const detail = $('#detail');
  detail.replaceChildren();
  for (const [label, value] of signals) {
    const card = document.createElement('div');
    card.className = 'signal';
    const title = document.createElement('span'); title.textContent = label;
    const number = document.createElement('strong'); number.textContent = Number(value).toFixed(3);
    card.append(title, number); detail.append(card);
  }
  const note = document.createElement('p');
  note.className = 'detail-note';
  note.textContent = 'Это наблюдения, доступные для проверки инженером, а не причинное объяснение и не доли вклада модели.';
  detail.append(note);
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
    const names = {cpu: 'CPU', memory: 'Память', network: 'Сеть', traffic_rate: 'Трафик'};
    const display = value => Number(value).toLocaleString('ru-RU', {maximumFractionDigits: 3});
    for (const [family, values] of Object.entries(observations.metrics)) {
      const row = document.createElement('tr');
      for (const value of [names[family] || family, String(values.samples),
        `${display(values.median)} ${values.unit}`, `${display(values.min)}–${display(values.max)} ${values.unit}`]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      table.append(row);
    }
    if (Object.keys(observations.metrics).length) detail.append(table);
    else {
      const missing = document.createElement('p');
      missing.textContent = 'По этому сервису метрики в выбранном интервале отсутствуют.';
      detail.append(missing);
    }
  }
}

function renderRanking(data) {
  state.current = data;
  const selected = state.examples.find(item => item.id === data.incident_id);
  const profile = state.profiles.find(item => item.id === data.profile_id);
  const start = new Date(data.start_unix * 1000).toISOString().replace('T', ' ').slice(0, 19);
  const end = new Date(data.end_unix * 1000).toISOString().replace('T', ' ').slice(0, 19);
  const source = profile?.title || selected?.title || 'Контрольное окно';
  const traces = data.source_status?.traces === 'unavailable' ? ' · трассировки недоступны' : '';
  const incomplete = data.source_status?.metric_families_by_service &&
    Object.values(data.source_status.metric_families_by_service).some(families => families.length < 4)
    ? ' · метрики неполны' : '';
  $('#incident-label').textContent = `${source} · ${start}–${end} UTC · ансамбль из ${data.model_count} экземпляров${traces}${incomplete}`;
  $('#candidate-count').textContent = `${data.candidate_count} сервисов`;
  const warning = $('#coverage-warning');
  const families = Object.values(data.source_status?.metric_families_by_service || {});
  const complete = families.filter(item => item.length === 4).length;
  warning.hidden = !families.length || complete === families.length;
  if (!warning.hidden) warning.textContent =
    `Полные метрики доступны для ${complete} из ${families.length} сервисов. Проверьте покрытие источника до вывода о причине; отсутствие ряда не равно нулевой нагрузке.`;
  const list = $('#ranking'); list.replaceChildren();
  for (const candidate of data.candidates) {
    const row = document.createElement('button');
    row.type = 'button'; row.className = 'rank-row';
    const rank = document.createElement('span'); rank.className = 'rank-number'; rank.textContent = `#${candidate.rank}`;
    const name = document.createElement('span'); name.className = 'rank-name'; name.textContent = candidate.service;
    const score = document.createElement('span'); score.className = 'rank-score'; score.textContent = `балл ${Number(candidate.model_score).toFixed(3)}`;
    row.append(rank, name, score);
    row.addEventListener('click', () => {
      $$('.rank-row').forEach(item => item.classList.remove('selected'));
      row.classList.add('selected'); renderCandidate(candidate);
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
  const error = $('#analysis-error'); error.hidden = true;
  const button = $('#analyze'); button.disabled = true; button.textContent = 'Выполняется анализ…';
  try {
    const profileId = $('#profile-select').value;
    const start = $('#start-time').value;
    const end = $('#end-time').value;
    if (!profileId || !start || !end) throw new Error('Выберите систему и обе границы интервала.');
    const startUnix = new Date(start).getTime() / 1000;
    const endUnix = new Date(end).getTime() / 1000;
    if (!Number.isFinite(startUnix) || !Number.isFinite(endUnix) || endUnix <= startUnix) {
      throw new Error('Проверьте границы интервала.');
    }
    const result = await request('/api/analyze', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({profile_id: profileId, start_unix: startUnix, end_unix: endUnix})
    });
    renderRanking(result);
  } catch (reason) {
    error.textContent = reason.message || String(reason); error.hidden = false; clearResult();
  } finally {
    button.disabled = false; button.innerHTML = 'Рассчитать рейтинг <span aria-hidden="true">›</span>';
  }
}

async function analyzeReplay() {
  const error = $('#analysis-error'); error.hidden = true;
  const button = $('#replay-analyze'); button.disabled = true; button.textContent = 'Воспроизведение…';
  try {
    const file = $('#incident-file').files[0];
    const payload = file ? {incident: JSON.parse(await file.text())} : {example_id: $('#example-select').value};
    if (!file && !payload.example_id) throw new Error('Выберите сохранённый случай или канонический файл.');
    const result = await request('/api/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    renderRanking(result);
  } catch (reason) {
    error.textContent = reason.message || String(reason); error.hidden = false; clearResult();
  } finally {
    button.disabled = false; button.textContent = 'Воспроизвести рейтинг';
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
  $('#analyze').addEventListener('click', analyzeLive);
  $('#replay-analyze').addEventListener('click', analyzeReplay);
  setInitialTime();
  $('#example-select').addEventListener('change', () => {$('#incident-file').value = ''; clearResult();});
  $('#incident-file').addEventListener('change', () => {$('#example-select').value = ''; clearResult();});
  try {
    const [health, profiles] = await Promise.all([request('/api/health'), request('/api/profiles')]);
    $('#readiness').textContent = `Ансамбль загружен · ${health.model_count} экземпляров`;
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
