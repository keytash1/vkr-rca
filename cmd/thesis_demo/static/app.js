const state = {examples: [], profiles: [], current: null, busy: false, catalog: null, catalogStatus: '', selectedService: null};
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
  window.RCAWorkspace?.onAnalysis(null);
  state.current = null;
  state.catalog = null; state.catalogStatus = ''; state.selectedService = null;
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
  state.selectedService = candidate.service;
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
  renderEvidence(candidate.service, detail);
}

function textElement(tag, text, className) {
  const element = document.createElement(tag); element.textContent = text;
  if (className) element.className = className;
  return element;
}

function sourceLinks(fact) {
  const container = document.createElement('p'); container.className = 'source-links';
  for (const [index, source] of fact.source_links.entries()) {
    let url;
    try { url = new URL(source.url); } catch { continue; }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) continue;
    const link = textElement('a', fact.kind === 'metric' ? 'Открыть ряд в источнике' : `Поиск трасс ${index + 1}`);
    link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    container.append(link);
  }
  return container;
}

function metricChart(fact, title) {
  const bins = fact.values.series;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 600 160'); svg.setAttribute('class', 'metric-chart');
  const expected = fact.values.baseline_comparison?.expected_at_observed_load;
  svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `${title}: среднее и диапазон временных групп.${expected != null ? ' Пунктир — прогноз базового состояния.' : ''}`);
  const values = bins.flatMap(bin => [bin.min, bin.max]);
  if (expected != null) values.push(expected);
  let minimum = Math.min(...values), maximum = Math.max(...values);
  if (fact.values.family?.startsWith('http_')) {
    // Floating-point histogram noise must not look like a large latency spike.
    const padding = Math.max((maximum - minimum) * .05, Math.max(Math.abs(minimum), Math.abs(maximum)) * .01, 1e-12);
    minimum = Math.max(0, minimum - padding); maximum += padding;
  }
  const y = value => 112 - (value - minimum) / (maximum - minimum || 1) * 96;
  const x = stamp => 52 + (stamp - fact.start_unix) / (fact.end_unix - fact.start_unix) * 532;
  const line = (points, style) => {
    const path = document.createElementNS(svg.namespaceURI, 'polyline');
    path.setAttribute('points', points); path.setAttribute('class', style); svg.append(path);
  };
  for (const key of ['min', 'max', 'mean']) line(bins.map(bin =>
    `${x((bin.start_unix + bin.end_unix) / 2)},${y(bin[key])}`).join(' '), `metric-line-${key}`);
  if (expected != null) line(`52,${y(expected)} 584,${y(expected)}`, 'metric-line-baseline');
  const label = (text, left, top, anchor) => {
    const element = document.createElementNS(svg.namespaceURI, 'text');
    element.textContent = text; element.setAttribute('x', left); element.setAttribute('y', top);
    element.setAttribute('text-anchor', anchor); element.setAttribute('class', 'metric-axis-label'); svg.append(element);
  };
  const divisor = fact.values.unit === 'bytes' ? 1024 ** 2 : fact.values.unit === 'bytes_per_second' ? 1024
    : fact.values.unit === 'seconds' ? .001 : fact.values.unit === 'ratio' ? .01 : 1;
  const number = value => Number(value / divisor).toLocaleString('ru-RU', {maximumSignificantDigits: 3});
  label(number(maximum), 46, 20, 'end'); label(number(minimum), 46, 116, 'end');
  const clock = stamp => new Date(stamp * 1000).toISOString().slice(11, 19);
  label(clock(fact.start_unix), 52, 144, 'start'); label('UTC', 318, 144, 'middle');
  label(clock(fact.end_unix), 584, 144, 'end');
  return svg;
}

function renderHttpEvidence(section, service) {
  const names = {
    http_request_rate: ['Завершённые запросы', 'запр./с', 1, 'requests_per_second'],
    http_error_ratio: ['Серверные ошибки 5xx', '%', .01, 'ratio'],
    http_latency_p95: ['Задержка p95', 'мс', .001, 'seconds'],
  };
  const facts = state.catalog.observations.filter(f => f.service === service && f.kind === 'metric' && names[f.values.family]);
  if (!facts.length) return;
  const group = document.createElement('details'); group.className = 'evidence-http';
  const status = state.catalog.source_quality?.http_observations?.services?.[service];
  const labels = {UNAVAILABLE: 'источник недоступен', INCOMPLETE: 'данные неполны', PARTIAL: 'частичные данные', NO_ACTIVITY: 'нет запросов'};
  group.append(textElement('summary', `HTTP-наблюдения${labels[status] ? ' · ' + labels[status] : ''}`));
  group.append(textElement('p', 'Дополнительные факты из HTTP-метрик. В расчёт рейтинга не входят и причину не доказывают.', 'detail-note'));
  const lookback = state.catalog.source_quality?.http_observations?.lookback_seconds;
  if (Number.isInteger(lookback)) group.append(textElement('p', `Каждая точка рассчитана по предыдущим ${lookback} с. Первые точки могут включать данные до начала выбранного интервала.`, 'detail-note'));
  for (const fact of facts) {
    const value = fact.values;
    const [name, unit, divisor, expectedUnit] = names[value.family];
    const item = document.createElement('details'); item.className = 'evidence-metric';
    const display = number => number == null ? 'не определено' : `${Number(number / divisor).toLocaleString('ru-RU', {maximumSignificantDigits: 4})} ${unit}`;
    item.append(textElement('summary', `${name} · ${value.unit === expectedUnit ? display(value.median) : 'неверные единицы'}`));
    if (value.unit !== expectedUnit) {
      item.append(textElement('p', 'Несовместимые единицы наблюдения. Проверьте профиль подключения.'));
    } else if (value.state === 'NOT_DEFINED_WITHOUT_TRAFFIC') {
      item.append(textElement('p', 'Без завершённых запросов доля ошибок и p95 не определены. Это не нулевые ошибки и не нулевая задержка.'));
    } else if (!value.samples) {
      item.append(textElement('p', 'Наблюдения недоступны. Старые или отсутствующие значения не показаны как нормальные нули.'));
    } else {
      item.append(textElement('p', `Диапазон: ${display(value.min)}–${display(value.max)}; определённых отсчётов: ${value.samples}.`));
      if (value.state === 'PARTIAL') item.append(textElement('p', 'Часть данных отсутствует; по этому ряду нельзя считать покрытие полным.'));
      item.append(metricChart(fact, `${name}, ${unit}`));
      item.append(textElement('p', value.family === 'http_latency_p95'
        ? 'Это временной ряд оценок p95 завершённых запросов, а не общий p95 всего интервала и не локальное время CPU. В заголовке — медиана оценок p95.'
        : 'В заголовке — медиана временных отсчётов; на графике — среднее и диапазон временных групп.', 'detail-note'));
    }
    item.append(sourceLinks(fact)); group.append(item);
  }
  section.append(group);
}

function renderEvidence(service, detail) {
  const section = document.createElement('section'); section.className = 'primary-evidence';
  section.append(textElement('h3', 'Проверка по первичным данным'));
  if (!state.catalog) {
    section.append(textElement('p', state.catalogStatus || 'Загрузка наблюдений…', 'secondary'));
    detail.append(section); return;
  }
  renderBaselineApplicability(section, state.catalog.source_quality?.baseline_applicability);
  renderIncidentContext(section, state.catalog.observations.find(item => item.service === service && item.kind === 'context'));
  renderHttpEvidence(section, service);
  const names = {cpu: 'CPU', memory: 'Память', network: 'Сетевой обмен', traffic_rate: 'Входящий трафик'};
  for (const fact of state.catalog.observations.filter(item => item.service === service && item.kind === 'metric' && !item.values.family.startsWith('http_'))) {
    const value = fact.values;
    const divisor = value.unit === 'bytes' ? 1024 ** 2 : value.unit === 'bytes_per_second' ? 1024 : 1;
    const unit = value.unit === 'bytes' ? 'МиБ' : value.unit === 'bytes_per_second' ? 'КиБ/с' : 'ядра';
    const display = number => number == null ? 'нет данных' : `${Number(number / divisor).toLocaleString('ru-RU', {maximumSignificantDigits: 6})} ${unit}`;
    const item = document.createElement('details'); item.className = 'evidence-metric';
    const name = names[value.family] || value.family;
    item.append(textElement('summary', `${name} · ${display(value.median)}`));
    if (!value.samples) item.append(textElement('p', 'Ряд отсутствует. Это не подтверждение нормальной работы.'));
    else {
      const comparison = value.baseline_comparison;
      item.append(textElement('p', `Наблюдается: ${display(value.min)}–${display(value.max)}; отсчётов: ${value.samples}.`));
      if (comparison) {
        item.append(textElement('p', `Прогноз здорового состояния при текущей интенсивности: ${display(comparison.expected_at_observed_load)}.`));
        if (comparison.healthy_start_unix != null && comparison.healthy_end_unix != null) {
          const date = stamp => new Date(stamp * 1000).toLocaleString('ru-RU');
          item.append(textElement('p', `Здоровый период: ${date(comparison.healthy_start_unix)} — ${date(comparison.healthy_end_unix)}.`, 'secondary'));
        }
      }
      item.append(metricChart(fact, name));
      item.append(textElement('p', 'Сплошная линия — среднее группы, светлые линии — её минимум и максимум; пунктир — прогноз baseline. Сопоставимость нагрузки требует проверки. Границы графика совпадают с интервалом анализа.', 'detail-note'));
      if (value.returned_point_coverage != null) item.append(textElement('p', `Покрытие ожидаемых отсчётов: ${Math.round(value.returned_point_coverage * 100)}%.`, 'secondary'));
    }
    item.append(sourceLinks(fact)); section.append(item);
  }
  const traces = state.catalog.observations.find(item => item.service === service && item.kind === 'traces');
  if (traces) {
    const timing = traces.values.timing;
    if (timing?.timed_spans) {
      section.append(textElement('h3', 'Время наблюдаемых операций'));
      const table = document.createElement('table'); table.className='observation-table';
      const format = value => value == null ? 'Не установлено' : (value/1000).toLocaleString('ru-RU',{maximumFractionDigits:3})+' мс';
      for (const [label,value] of [['Медиана длительности',timing.median_us],['P90 длительности',timing.p90_us],
        ['Наблюдаемое ожидание зависимостей, медиана',timing.observed_client_wait_median_us],
        ['Остальное время, медиана',timing.observed_exclusive_median_us]]) {
        const row=document.createElement('tr'); row.append(textElement('th',label),textElement('td',format(value))); table.append(row);
      }
      section.append(table);
      section.append(textElement('p',timing.selection==='SERVER_SPANS'
        ? 'По SERVER-спанам. Из длительности вычитается объединение наблюдаемых CLIENT-ожиданий. Остальное время — не CPU time и не доказательство локальной причины; неполнота трасс может занизить ожидание.'
        : 'SERVER-спаны не распознаны: длительности показаны по доступным видам спанов. Время обработки и ожидания не установлено.','detail-note'));
    }
    section.append(textElement('p', 'Sampling и срок хранения трасс неизвестны. Примеры выбраны сначала по ошибке, затем по длительности; это не случайная выборка.', 'detail-note'));
    const traceDetails = document.createElement('details');
    traceDetails.append(textElement('summary', `Примеры трасс: ${traces.values.examples.length}`));
    const examples = document.createElement('ul'); examples.className = 'trace-examples';
    for (const span of traces.values.examples) examples.append(textElement('li',
      `Трасса ${span.trace_id}, спан ${span.span_id}: ${(span.duration_us / 1000).toLocaleString('ru-RU')} мс${span.error ? ', отмечена ошибка' : ''}.`));
    traceDetails.append(examples, sourceLinks(traces)); section.append(traceDetails);
  }
  const dependencies = state.catalog.observations.find(item => item.service === service && item.kind === 'dependencies');
  if (dependencies?.values.edges.length) {
    section.append(textElement('h3', 'Наблюдаемые вызовы'));
    const list = document.createElement('ul');
    for (const edge of dependencies.values.edges) list.append(textElement('li', `${edge.source} → ${edge.target}: ${edge.observed_edges} наблюдений связи.`));
    section.append(list);
  }
  const checks = state.catalog.checks.filter(item => item.service === service);
  section.append(textElement('h3', 'Следующие проверки'));
  if (checks.length) {
    const list = document.createElement('ul');
    const deviations = checks.filter(check => check.code === 'CHECK_METRIC_DEVIATION');
    if (deviations.length) {
      const families = deviations.flatMap(check => check.evidence_ids).map(id =>
        state.catalog.observations.find(fact => fact.id === id)?.values.family).filter(Boolean);
      list.append(textElement('li', `Сопоставить с нагрузкой и здоровым периодом: ${families.map(family => names[family] || family).join(', ')}.`));
    }
    for (const check of checks.filter(check => check.code !== 'CHECK_METRIC_DEVIATION')) list.append(textElement('li', check.text));
    section.append(list);
  } else section.append(textElement('p', 'По этим правилам отдельный проверочный шаг не выделен. Отсутствие рекомендации не подтверждает здоровье сервиса.'));
  section.append(textElement('p', 'Предложенные шаги ещё не выполнены. Наблюдаемые связи и отклонения сами по себе не устанавливают причину.', 'detail-note'));
  detail.append(section);
}

function renderIncidentContext(parent, fact) {
  if (!fact) return;
  const v = fact.values;
  const box = document.createElement('details');
  const labels = {available: `в выборке ${v.record_count} записей`, truncated: 'выборка усечена',
    unavailable: 'источник недоступен', not_configured: 'сервис не подключён'};
  box.append(textElement('summary', `Журналы и события: ${labels[v.source_status] || 'нет сведений'}`));
  if (['unavailable', 'truncated'].includes(v.source_status)) box.open = true;
  box.append(textElement('p', 'Ограниченная выборка источника. Пустой ответ не доказывает отсутствие ошибки; совпадение события с инцидентом не устанавливает причину.', 'detail-note'));
  if (v.lookback_seconds) box.append(textElement('p', `Также просмотрены ${v.lookback_seconds / 60} мин до инцидента: ${v.preceding_record_count || 0} записей. Интервал расчёта рейтинга не расширен.`, 'detail-note'));
  const checks = {
    PERMISSION_RESPONSE: 'Есть ответ 401/403. Проверьте права и настройки доступа к зависимости.',
    CONNECTION_REFUSED: 'Есть отказ соединения. Проверьте адрес зависимости, слушающий порт и доступность процесса.',
    OPERATION_TIMEOUT: 'Есть таймаут операции. Сопоставьте бюджет ожидания с задержками зависимости и очередями.',
    DEPLOYMENT_EVENT: 'Есть событие развёртывания. Проверьте, влияет ли изменение на наблюдаемый сбой; одной близости по времени недостаточно.',
    CONFIGURATION_EVENT: 'Есть изменение конфигурации. Сверьте изменённые параметры и проверяемый механизм отказа.',
    RESTART_EVENT: 'Есть перезапуск. Проверьте причину остановки и изменение состояния до него.',
    OOM_EVENT: 'Источник сообщает об OOM. Проверьте лимит памяти и события среды исполнения.',
    EXIT_EVENT: 'Есть завершение контейнера. Код 137 означает SIGKILL, но сам по себе не подтверждает OOM.',
    START_EVENT: 'Есть запуск контейнера. Сопоставьте экземпляр и время с предшествующим завершением.',
    HEALTH_EVENT: 'Изменилась проверка здоровья контейнера. Это симптом; проверьте ответ приложения.',
  };
  for (const c of v.categories || []) if (checks[c]) box.append(textElement('p', checks[c]));
  if (v.unsupported_entries) box.append(textElement('p', `Пропущено неподдерживаемых строк: ${v.unsupported_entries}.`));
  box.append(textElement('p', v.assistant_categories_enabled
    ? 'Помощнику разрешены только категории и количества; исходные поля журналов остаются локально.'
    : 'Контекст журналов помощнику не передаётся. Разрешение категорий настраивает интегратор.', 'detail-note'));
  const records = document.createElement('details');
  records.append(textElement('summary', `Выбранные поля записей (${v.record_count || 0})`));
  for (const record of v.records || []) {
    const fields = Object.entries(record.fields).map(([key, value]) => `${key}: ${value}`).join(' · ');
    const stamp = new Date(Number(record.source_timestamp_ns) / 1e6).toISOString().replace('T', ' ').replace('Z', ' UTC');
    records.append(textElement('p', `${stamp}${record.period === 'BEFORE_INCIDENT' ? ' · до инцидента' : ''} · ${fields}`, 'detail-note'));
  }
  if (v.record_count) box.append(records);
  const provenance = document.createElement('details');
  provenance.append(textElement('summary', 'Сведения об источнике'));
  provenance.append(textElement('p', `Источник: ${v.source_id}. Время — отметка Loki; при наличии event.time_unix_ns источник заявляет время события. Синхронизация часов и полнота истории не установлены. ID факта: ${fact.id}.`, 'detail-note'));
  box.append(provenance);
  parent.append(box);
}

function renderBaselineApplicability(parent, assessment) {
  if (!assessment) return; // Earlier saved snapshots remain readable.
  const box = document.createElement('details'); box.className = 'baseline-applicability';
  box.append(textElement('summary', assessment.state === 'REVIEW_REQUIRED'
    ? 'Здоровое состояние: требуется проверка сопоставимости'
    : 'Здоровое состояние: сопоставлена опорная нагрузка'));
  const notes = {
    HEALTHY_PERIOD_UNKNOWN: 'Не указан здоровый период. Проверьте происхождение базового состояния.',
    HEALTHY_PERIOD_AFTER: 'Здоровый период находится после выбранного интервала. Он не является предшествующим эталоном этого инцидента.',
    HEALTHY_PERIOD_OVERLAPS: 'Здоровый период пересекается с выбранным интервалом. Проверьте, что в него не попало влияние инцидента.',
    REFERENCE_LOAD_UNKNOWN: 'Нагрузка здорового периода не записана в этой версии профиля.',
    REFERENCE_LOAD_CONFIGURED_NOT_MEASURED: 'Нагрузка здорового периода задана интегратором, а не измерена источником.',
    CURRENT_LOAD_SOURCE_UNKNOWN: 'Происхождение текущей интенсивности нагрузки не установлено.',
    CURRENT_LOAD_CONFIGURED_NOT_MEASURED: 'Текущая нагрузка задана константой профиля. Фактическое изменение трафика ею не измеряется.',
    LOAD_DIFFERS_FROM_SINGLE_REFERENCE: 'Текущая интенсивность отличается от опорной. Проверьте прогноз метрик при изменившемся режиме работы.',
    CURRENT_LOAD_UNKNOWN: 'Текущую интенсивность нагрузки не удалось сопоставить.',
  };
  const reasons = assessment.reasons || [];
  if (reasons.some(reason => ['HEALTHY_PERIOD_AFTER', 'HEALTHY_PERIOD_OVERLAPS', 'LOAD_DIFFERS_FROM_SINGLE_REFERENCE'].includes(reason))) box.open = true;
  const number = value => Number(value).toLocaleString('ru-RU', {maximumSignificantDigits: 6});
  if (assessment.reference_rps != null && assessment.current_rps != null)
    box.append(textElement('p', `Опорная интенсивность: ${number(assessment.reference_rps)} запросов/с; текущая: ${number(assessment.current_rps)} запросов/с.`));
  for (const reason of reasons) if (notes[reason]) box.append(textElement('p', notes[reason]));
  box.append(textElement('p', 'Сравнение с одной опорной нагрузкой не подтверждает качество модели на всех режимах. Рейтинг не изменён; это не вероятность причины.', 'detail-note'));
  parent.append(box);
}

async function loadEvidence(result) {
  try {
    const catalog = await request(`/api/v2/analyses/${encodeURIComponent(result.result_id)}/evidence`);
    if (state.current?.result_id !== result.result_id) return;
    state.catalog = catalog;
  } catch (error) {
    if (state.current?.result_id !== result.result_id) return;
    state.catalogStatus = 'Каталог наблюдений недоступен. Рейтинг сохранён; для повторного получения наблюдений выполните анализ заново.';
  }
  const candidate = state.current?.candidates.find(item => item.service === state.selectedService);
  if (candidate) renderCandidate(candidate);
}

function renderRanking(data) {
  state.current = data;
  state.catalog = null; state.catalogStatus = 'Загрузка наблюдений…';
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
  if (data.delivery?.cache_hit) {
    const term = document.createElement('dt'); term.textContent = 'Повторный ответ';
    const definition = document.createElement('dd'); definition.textContent = 'Из памяти; возраст наблюдений: ' + Math.ceil(data.delivery.source_age_seconds || 0) + ' с';
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
  if (data.source_status?.baseline_binding?.state === 'needs_review') messages.push(
    'Историческое базовое состояние не связано с семантической версией профиля. Интегратору необходимо проверить сопоставимость источников и запросов.');
  if (families.length && complete < families.length) messages.push(
    `Полные метрики доступны для ${complete} из ${families.length} сервисов.`);
  if (data.source_status?.traces === 'unavailable') messages.push('Источник трассировок недоступен. Рейтинг рассчитан с неполными наблюдениями.');
  else if (data.source_status?.span_count === 0) messages.push('В выбранном интервале нет наблюдаемых спанов.');
  else if (data.source_status?.services_without_spans?.length) messages.push(
    `Нет спанов для: ${data.source_status.services_without_spans.join(', ')}. Проверьте активность и инструментирование этих сервисов.`);
  for (const item of data.source_status?.annotations || []) messages.push(`${item.family}: ${item.message}`);
  const pointCoverage = Object.values(data.source_status?.metric_point_coverage || {});
  if (data.source_status?.incident_context?.status === 'projection_unavailable') messages.push('Дополнительный контекст не удалось сохранить. Рейтинг и основные наблюдения доступны.');
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
  loadEvidence(data);
  window.RCAWorkspace?.onAnalysis(data);
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
      body: JSON.stringify({profile_id: profileId, start_unix: startUnix, end_unix: endUnix,
        force_refresh: document.getElementById('force-refresh').checked})
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
    const exported = state.catalog ? {...state.current, observation_catalog: state.catalog} : state.current;
    const blob = new Blob([JSON.stringify(exported, null, 2)], {type: 'application/json'});
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
