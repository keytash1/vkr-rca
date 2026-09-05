const state = { tab: "live", scenario: "healthy", cases: [], models: [], prediction: null, live: null };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const TOOLTIP_TEXT = Object.freeze({
  "RCA": "Анализ первопричин: поиск компонента, с которого наиболее вероятно начался наблюдаемый сбой.",
  "Latency": "Задержка — время от начала запроса до получения ответа.",
  "Error rate": "Доля запросов, завершившихся ошибкой за выбранный интервал.",
  "Trace": "Трассировка — полный путь одного запроса через несколько сервисов.",
  "Span": "Span — отдельный участок трассировки: работа одного сервиса или вызов зависимости.",
  "Topology": "Топология — наблюдаемый граф вызовов и зависимостей между сервисами.",
  "Exclusive duration": "Показывает, какая доля наблюдаемого времени не была потрачена на ожидание downstream-вызовов. Технический термин: exclusive observed duration ratio. Это не CPU time.",
  "Ranking score": "Число используется только для сравнения кандидатов внутри одного инцидента. Это не вероятность и не процент уверенности.",
  "LambdaMART": "Модель Learning-to-Rank, которая учится ставить истинную причину выше других кандидатов.",
  "AC@1": "Доля инцидентов, где истинная причина находится на первом месте рейтинга.",
  "AC@3": "Доля инцидентов, где истинная причина входит в первые три позиции рейтинга.",
  "MRR": "Среднее обратной позиции истинной причины: чем она выше в рейтинге, тем больше значение.",
  "SHAP": "Метод оценки вклада признаков в предсказание модели; не доказательство причинности.",
  "Ground truth": "Независимая разметка с фактической причиной инцидента, скрытая от модели во время анализа.",
});

const CLAIM_TEXT_RU = Object.freeze({
  1: "Метрики существенно улучшают локализацию по сравнению с одними трассировками.",
  2: "Объединение метрик, трассировок и топологии улучшает модель только по метрикам при одинаковом межсистемном протоколе.",
  3: "Независимое от имён сервисов представление переносится между системами.",
  4: "Learning-to-Rank превосходит простую эвристику по метрикам.",
  5: "Добавление метрик улучшает локализацию наблюдаемых ошибок уровня кода.",
  6: "Жёсткая фильтрация аномалий ограничивает автономный сквозной RCA.",
  7: "Временной CUSUM только по трассировкам переносится между доменами.",
});

const ARCHITECTURE_LABELS = Object.freeze({
  "Go microservices": "Микросервисы на Go",
  "OpenTelemetry": "OpenTelemetry",
  "RCA graph + anomaly evidence": "Граф RCA и признаки аномалий",
  "M6 explainable online ranking": "Объяснимый онлайн-рейтинг M6",
  "Pinned RCAEval case": "Зафиксированный инцидент RCAEval",
  "M9B truth-free features": "Признаки M9B без фактической разметки",
  "Frozen cross-system LambdaMART fold": "Зафиксированная межсистемная модель LambdaMART",
  "Top-K + predictive contribution evidence": "Top-K и объяснение вклада признаков",
  "Incident trigger": "Сигнал об инциденте",
  "metrics + traces": "метрики и трассировки",
  "metrics+traces": "метрики и трассировки",
  "topology": "топология",
  "feature extraction": "извлечение признаков",
  "LambdaMART": "LambdaMART",
  "Top-K": "Top-K рейтинг",
  "evidence": "объяснение результата",
});

const TAB_LABELS = Object.freeze({
  live: ["Живая демонстрация", "Топология A", "Объяснимый онлайн-метод M6"],
  replay: ["Внешний набор данных", "RCAEval", "Зафиксированная модель M9B"],
  research: ["Результаты исследования", "RCAEval + синтетика", "заморозка M10A"],
  architecture: ["Архитектура", "Два разделённых пути", "замороженное ядро"],
  guide: ["Как пользоваться", "Справка", "без изменений исследования"],
});

const STATE_LABELS = Object.freeze({ idle: "ожидание", running: "выполняется", analyzing: "анализ", complete: "готово", error: "ошибка" });
const SCENARIO_LABELS = Object.freeze({
  healthy: "Нормальная работа", gateway_latency: "Задержка Gateway", orders_latency: "Задержка Orders",
  payment_latency: "Задержка Payment", gateway_error: "Ошибка Gateway", orders_error: "Ошибка Orders", payment_error: "Ошибка Payment",
});

document.addEventListener("DOMContentLoaded", async () => {
  bindTabs();
  bindTooltips();
  bindWelcome();
  bindLive();
  bindReplay();
  drawGraph({ nodes: [{ service: "gateway" }, { service: "orders" }, { service: "payment" }], edges: [
    { source: "gateway", target: "orders" }, { source: "orders", target: "payment" }
  ]}, []);
  const results = await Promise.allSettled([loadHealth(), loadReplayCases(), loadResearch(), loadArchitecture()]);
  const failed = results.find(value => value.status === "rejected");
  if (failed) showError("global", failed.reason);
});

function bindTabs() {
  $$(".tab").forEach(button => button.addEventListener("click", () => activateTab(button.dataset.tab)));
  $$('[data-open-tab]').forEach(button => button.addEventListener("click", () => activateTab(button.dataset.openTab)));
}

function activateTab(tab) {
  if (!TAB_LABELS[tab]) return;
  state.tab = tab;
  $$(".tab").forEach(value => value.classList.toggle("active", value.dataset.tab === tab));
  $$(".panel").forEach(value => value.classList.toggle("active", value.id === `tab-${tab}`));
  const labels = [...TAB_LABELS[tab]];
  if (tab === "replay") {
    labels[1] = selectedCase()?.system || labels[1];
  }
  $("#header-mode").textContent = labels[0];
  $("#header-system").textContent = labels[1];
  $("#header-model").textContent = labels[2];
  if (tab === "replay" && state.prediction) $("#header-model").title = `Техническая версия: ${state.prediction.model.version}`;
  else $("#header-model").removeAttribute("title");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindTooltips() {
  $$(".term-help").forEach(button => {
    const description = TOOLTIP_TEXT[button.dataset.term];
    if (!description) return;
    button.dataset.description = description;
    button.title = description;
    button.setAttribute("aria-label", `${button.dataset.term}: ${description}`);
    button.addEventListener("click", event => {
      event.stopPropagation();
      const pinned = button.classList.contains("pinned");
      $$(".term-help.pinned").forEach(value => value.classList.remove("pinned"));
      button.classList.toggle("pinned", !pinned);
    });
  });
  document.addEventListener("click", () => $$(".term-help.pinned").forEach(value => value.classList.remove("pinned")));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") $$(".term-help.pinned").forEach(value => value.classList.remove("pinned"));
  });
}

function bindWelcome() {
  const key = "m10b-welcome-seen";
  const modal = $("#welcome");
  const close = tab => {
    sessionStorage.setItem(key, "true");
    modal.classList.add("hidden");
    activateTab(tab);
  };
  $("#welcome-guide").addEventListener("click", () => close("guide"));
  $("#welcome-demo").addEventListener("click", () => close("live"));
  if (!sessionStorage.getItem(key)) modal.classList.remove("hidden");
}

function bindLive() {
  $("#live-reset").addEventListener("click", async () => {
    setBusy("live", true, "running");
    clearError("live");
    startProgress("live", [[0, "Сбрасываем стенд"], [1200, "Ждём телеметрию"]]);
    try {
      const result = await api("/api/demo/live/reset", { method: "POST" }, 65000);
      state.live = null; state.scenario = "healthy"; selectScenario("healthy");
      clearLive(); setHeaderState(result.state); toast("Стенд сброшен, профиль нормальной работы откалиброван.");
    } catch (error) { fail(error, "live"); } finally { stopProgress("live"); setBusy("live", false); }
  });
  $$(".scenario").forEach(button => button.addEventListener("click", async () => {
    setBusy("live", true, "running");
    clearError("live");
    startProgress("live", [[0, "Применяем сценарий"]]);
    try {
      await api("/api/demo/live/scenario", jsonPost({ scenario: button.dataset.scenario }));
      state.scenario = button.dataset.scenario; selectScenario(state.scenario); clearLive();
      setHeaderState("idle");
      toast(`Выбран сценарий: ${humanScenario(state.scenario)}.`);
    } catch (error) { fail(error, "live"); } finally { stopProgress("live"); setBusy("live", false); }
  }));
  $("#live-traffic").addEventListener("click", async () => {
    setBusy("live", true, "running");
    clearError("live");
    startProgress("live", [[0, "Генерируем запросы"], [1800, "Ждём телеметрию"], [4800, "Строим диагностические признаки"], [7000, "Выполняем ранжирование"]]);
    try {
      const response = await api("/api/demo/live/traffic", jsonPost({ requests: 20 }), 65000);
      state.live = response.result; renderLive(response.result); setHeaderState("complete");
      toast(`Проанализировано запросов с трассировкой: ${response.traffic.requests}.`);
    } catch (error) { fail(error, "live"); } finally { stopProgress("live"); setBusy("live", false); }
  });
}

function bindReplay() {
  $("#case-select").addEventListener("change", () => { state.prediction = null; renderCaseMetadata(); clearReplay(); });
  $("#replay-analyze").addEventListener("click", async () => {
    const selected = selectedCase(); if (!selected) return;
    setBusy("replay", true, "analyzing");
    clearError("replay");
    startProgress("replay", [[0, "Строим диагностические признаки"], [350, "Выполняем ранжирование"]]);
    try {
      const response = await api("/api/demo/replay/analyze", jsonPost({ case_id: selected.id }));
      state.prediction = response.prediction; renderReplay(response.prediction);
      $("#replay-reveal").disabled = false; setHeaderState("complete");
      $("#header-model").textContent = "Зафиксированная модель M9B";
      $("#header-model").title = `Техническая версия: ${response.prediction.model.version}`;
      setBlindComplete();
      toast("Анализ замороженной моделью без фактической разметки завершён.");
    } catch (error) { fail(error, "replay"); } finally { stopProgress("replay"); setBusy("replay", false); }
  });
  $("#replay-reveal").addEventListener("click", async () => {
    const selected = selectedCase(); if (!selected || !state.prediction) return;
    setBusy("replay", true, "analyzing");
    try {
      const response = await api("/api/demo/replay/reveal", jsonPost({ case_id: selected.id }));
      renderReveal(response.ground_truth, response.case_id); setHeaderState("complete");
    } catch (error) { fail(error, "replay"); } finally { setBusy("replay", false); }
  });
}

async function loadHealth() {
  const health = await api("/api/demo/health");
  if (health.freeze.status !== "identical") throw new Error("Нарушена целостность замороженных результатов исследования");
}

async function loadReplayCases() {
  try {
    const result = await api("/api/demo/replay/cases");
    state.cases = result.cases;
    $("#case-select").innerHTML = state.cases.map((value, index) => `<option value="incident-${String(index+1).padStart(2,"0")}">${escapeHTML(value.title)}</option>`).join("");
    renderCaseMetadata();
  } catch (error) {
    $("#case-select").innerHTML = "<option>Сначала выполните make demo-prepare</option>";
    $("#replay-analyze").disabled = true;
    showError("replay", error);
  }
}

function renderCaseMetadata() {
  const value = selectedCase(); if (!value) return;
  const telemetry = value.telemetry || {};
  $("#case-metadata").innerHTML = rows({
    "Набор данных": value.dataset, "Система": value.system, "Время инцидента": value.incident_timestamp,
    "Кандидаты": value.candidate_count, "Семейства метрик": telemetry.metric_family_count,
    "Покрытие трассировок": percent(telemetry.trace_coverage), "Рёбра графа": telemetry.topology_edges,
  });
  if (state.tab === "replay") $("#header-system").textContent = value.system;
}

function renderLive(result) {
  const observed = result.features?.observed_anomalies || [];
  const features = result.features?.services || [];
  drawGraph(result.graph || { nodes: [], edges: [] }, observed, features);
  const source = result.features?.topology_source || "RCA API";
  $("#graph-source").textContent = topologySourceLabel(source);
  $("#graph-source").title = `Техническое имя: ${source}`;
  const ranking = result.rca?.rankings?.hybrid_v1 || [];
  $("#live-ranking").classList.remove("empty");
  $("#live-ranking").innerHTML = ranking.length ? ranking.map(candidate => `
    <div class="rank-item"><div class="rank-head"><span class="rank-number">#${candidate.rank}</span>
      <span class="rank-service">${escapeHTML(candidate.service)}</span><span class="rank-score" title="Оценка ранжирования">оценка ${number(candidate.score)}</span></div>
      <div class="rank-groups"><span class="chip">${escapeHTML(signalLabel(candidate.evidence.signal.type))}</span><span class="chip">локальный признак ${number(candidate.evidence.local_evidence)}</span></div></div>`).join("") : "Рейтинг пуст: сначала выполните сброс и калибровку.";
  $("#live-evidence").classList.remove("empty");
  $("#live-evidence").innerHTML = features.map(feature => evidenceItem(feature.service, [
    ["Статус", !feature.ready ? "нет данных" : feature.candidate ? "аномалия" : "норма"],
    ["z-оценка задержки", number(feature.latency_z)], ["z-оценка ошибок", number(feature.error_z)],
    ["Доля локального времени", percent(feature.median_exclusive_ratio)], ["Локальное время", `${number(feature.median_exclusive_duration_ms)} мс`],
    ["Согласованность с графом (F1)", number(feature.topology_f1)], ["Диагностическая оценка", number(feature.local_evidence)]
  ])).join("");
  const traceID = result.trace_ids?.at(-1);
  $("#trace-id").textContent = traceID || "сохранена в RCA";
}

function clearLive() {
  $("#live-ranking").className = "ranking empty"; $("#live-ranking").textContent = "Сгенерируйте трафик, чтобы получить рейтинг и доказательства.";
  $("#live-evidence").className = "evidence-grid empty"; $("#live-evidence").textContent = "Для текущего инцидента ещё нет данных.";
  $("#trace-id").textContent = "нет";
  drawGraph({ nodes: [{ service: "gateway" }, { service: "orders" }, { service: "payment" }], edges: [
    { source: "gateway", target: "orders" }, { source: "orders", target: "payment" }
  ]}, []);
}

function renderReplay(prediction) {
  $("#replay-model").textContent = prediction.model.route;
  renderModelDetails(prediction.model);
  const ranking = prediction.ranking || [];
  $("#replay-ranking").classList.remove("empty");
  $("#replay-ranking").innerHTML = ranking.map((candidate, index) => `
    <div class="rank-item ${index === 0 ? "active" : ""}" data-rank-index="${index}">
      <div class="rank-head"><span class="rank-number">#${candidate.rank}</span><span class="rank-service">${escapeHTML(candidate.service)}</span><span class="rank-score" title="Оценка ранжирования">оценка ${number(candidate.score)}</span></div>
      <div class="rank-groups">${candidate.top_predictive_groups.slice(0,3).map(group => `<span class="chip">${escapeHTML(evidenceGroup(group.group))} ${percent(group.share)}</span>`).join("")}</div>
    </div>`).join("");
  $$("[data-rank-index]").forEach(item => item.addEventListener("click", () => {
    $$("[data-rank-index]").forEach(value => value.classList.toggle("active", value === item));
    renderReplayEvidence(ranking[Number(item.dataset.rankIndex)]);
  }));
  renderReplayEvidence(ranking[0]);
}

function renderReplayEvidence(candidate) {
  if (!candidate) return;
  $("#replay-evidence").classList.remove("empty");
  $("#replay-evidence").innerHTML = candidate.evidence.map(value => `
    <div class="evidence-item"><small>${escapeHTML(evidenceGroup(value.group))} · ${escapeHTML(evidenceDirection(value.direction))}</small>
      <b>${escapeHTML(value.display_name)}</b><code>${escapeHTML(value.technical_name)}</code>
      <div class="rank-score">вклад ${signed(value.contribution)}</div></div>`).join("");
}

function renderReveal(truth, caseID) {
  const outcome = truth.top1_correct ? "TOP-1 ВЕРНО" : "TOP-1 ОШИБКА";
  $("#reveal-result").className = "reveal-result";
  $("#reveal-result").innerHTML = `<div class="reveal-result"><small>ЗАМОРОЖЕННЫЙ РЕЗУЛЬТАТ</small>
    <div class="outcome ${truth.top1_correct ? "success" : "miss"}">${outcome}</div>
    <div class="metadata">${rows({ "Предсказание №1": truth.predicted_top1, "Фактическая причина": truth.root_service,
      "Место в рейтинге": truth.actual_rank, "Тип неисправности": truth.fault_family, "Фактический Case ID": caseID })}</div></div>`;
  $("#reveal-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearReplay() {
  $("#replay-ranking").className = "ranking empty"; $("#replay-ranking").textContent = "Предсказание не содержит фактическую причину или тип неисправности.";
  $("#replay-evidence").className = "evidence-grid empty"; $("#replay-evidence").textContent = "Проанализируйте инцидент, чтобы увидеть вклад признаков.";
  $("#reveal-result").className = "reveal-placeholder"; $("#reveal-result").textContent = "Фактическая причина изолирована до завершения анализа.";
  $("#replay-reveal").disabled = true;
  $("#model-details").open = false;
  $("#model-details-content").textContent = "Сначала проанализируйте внешний инцидент.";
  resetBlindNotice();
  clearError("replay");
}

function renderModelDetails(model) {
  const registry = state.models.find(value => value.version === model.version && value.fold === model.route) || {};
  $("#model-details-content").innerHTML = `<div class="metadata">${rows({
    "Модель": "LambdaMART",
    "Задача": "Learning-to-Rank",
    "Схема": model.schema,
    "Число признаков": registry.feature_count,
    "Версия": model.version,
    "SHA модели": model.sha256,
    "Обучающие наборы": (registry.training_systems || []).join(", "),
    "Зафиксированный артефакт": model.artifact,
  })}</div>`;
}

function resetBlindNotice() {
  const notice = $("#blind-notice");
  notice.classList.remove("complete");
  notice.innerHTML = "<b>Слепой анализ</b><p>Модель получает только телеметрию. Фактическая первопричина и тип неисправности не передаются модели и остаются скрытыми до завершения анализа.</p>";
}

function setBlindComplete() {
  const notice = $("#blind-notice");
  notice.classList.add("complete");
  notice.innerHTML = "<b>Прогноз зафиксирован</b><p>Теперь можно открыть независимую разметку. Исходный рейтинг после раскрытия не изменится.</p>";
}

async function loadResearch() {
  const research = await api("/api/demo/research");
  state.models = research.models || [];
  const m = research.metrics;
  const cards = [
    ["LambdaMART по метрикам", percent(m.metric_full_360.ac_at_1), `AC@1 · полный набор ${m.metric_full_360.cases} случаев`],
    ["Автономный режим M5 → RCA", percent(m.autonomous_m5.end_to_end_ac_at_1), `End-to-End AC@1 · ${m.autonomous_m5.cases} случаев`],
    ["BARO", percent(m.baro.ac_at_1), `AC@1 · те же ${m.baro.cases} внешних случаев`],
    ["Метрики + трассировки + топология", percent(m.fusion_all_modalities.ac_at_1), `AC@1 · сопоставимый межсистемный протокол · ${m.fusion_all_modalities.cases} случаев`],
    ["Прирост MRR от объединения", signed(m.fusion_paired.mrr.difference), `95% CI [${signed(m.fusion_paired.mrr.ci_low)}; ${signed(m.fusion_paired.mrr.ci_high)}]`],
  ];
  $("#research-metrics").innerHTML = cards.map(value => `<div class="card metric-card"><small>${value[0]}</small><strong>${value[1]}</strong><p>${value[2]}</p></div>`).join("");
  $("#claim-list").innerHTML = research.claims.map(claim => `<div class="claim"><span class="claim-no">${String(claim.number).padStart(2,"0")}</span>
    <p>${escapeHTML(CLAIM_TEXT_RU[claim.number] || claim.claim)}${claim.number === 2 ? `<small class="claim-detail">AC@1: ${signedPoints(m.fusion_paired.ac_at_1.difference)} п.п., 95% CI ${pointsInterval(m.fusion_paired.ac_at_1)} касается нуля. MRR: ${signedPoints(m.fusion_paired.mrr.difference)} п.п., 95% CI ${pointsInterval(m.fusion_paired.mrr)} полностью выше нуля.</small>` : ""}</p><span class="claim-status ${statusClass(claim.status)}">${escapeHTML(statusLabel(claim.status))}</span></div>`).join("");
  const synthetic = m.m9a_synthetic, external = m.m9a_external;
  $("#negative-result").innerHTML = `<p>Временной CUSUM только по трассировкам</p><div class="negative-sequence">
    <div><span>Синтетический стенд</span><strong>${percent(synthetic.recall)}</strong><small>Recall · ${percent(synthetic.healthy_fpr)} FPR</small></div><b>→</b>
    <div><span>Внешние данные</span><strong>${percent(external.v2_recall)}</strong><small>Recall · ${percent(external.v2_healthy_fpr)} FPR</small></div></div>
    <div class="verdict">МЕТОД ОТВЕРГНУТ</div><p class="negative-explanation">В другом домене он почти всегда объявлял состояние аномальным.</p><small class="technical-verdict">Технический статус: ${escapeHTML(m.m9a_verdict.gate)}</small>`;

  setText("#guide-metric-ac1", percent(m.metric_full_360.ac_at_1));
  setText("#guide-baro-ac1", percent(m.baro.ac_at_1));
  setText("#guide-fusion-ac1", percent(m.fusion_all_modalities.ac_at_1));
  setText("#guide-metrics-ac1", percent(m.fusion_metrics_only.ac_at_1));
  setText("#guide-fusion-delta", signedPoints(m.fusion_paired.ac_at_1.difference));
  setText("#guide-fusion-ci", pointsInterval(m.fusion_paired.ac_at_1));
  setText("#guide-mrr-delta", signed(m.fusion_paired.mrr.difference));
  setText("#guide-mrr-ci", scalarInterval(m.fusion_paired.mrr));
  setText("#guide-m9a-synthetic-recall", percent(synthetic.recall));
  setText("#guide-m9a-synthetic-fpr", percent(synthetic.healthy_fpr));
  setText("#guide-m9a-external-recall", percent(external.v2_recall));
  setText("#guide-m9a-external-fpr", percent(external.v2_healthy_fpr));
  if (state.prediction) renderModelDetails(state.prediction.model);
}

async function loadArchitecture() {
  const architecture = await api("/api/demo/architecture");
  renderPipeline("#live-path", architecture.live);
  renderPipeline("#benchmark-path", architecture.benchmark);
  renderPipeline("#research-path", architecture.research.filter(value => value !== "↓"));
}

function renderPipeline(selector, steps) { $(selector).innerHTML = steps.map(value => `<div class="pipeline-step">${escapeHTML(architectureLabel(value))}</div>`).join(""); }

function drawGraph(graph, anomalies, features=[]) {
  const svg = $("#live-graph"); svg.innerHTML = "";
  const nodes = [...(graph.nodes || [])].sort((a,b) => a.service.localeCompare(b.service));
  const edges = [...(graph.edges || [])].sort((a,b) => `${a.source}:${a.target}`.localeCompare(`${b.source}:${b.target}`));
  const evidence = Object.fromEntries(features.map(value => [value.service, value]));
  if (!nodes.length) return;
  const positions = dagPositions(nodes.map(value => value.service), edges);
  const ns = "http://www.w3.org/2000/svg";
  edges.forEach(edge => {
    const a = positions[edge.source], b = positions[edge.target]; if (!a || !b) return;
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", a.x + 75); line.setAttribute("y1", a.y); line.setAttribute("x2", b.x - 75); line.setAttribute("y2", b.y);
    line.setAttribute("stroke", "#3c5c61"); line.setAttribute("stroke-width", "2"); svg.appendChild(line);
    const marker = document.createElementNS(ns, "circle"); marker.setAttribute("cx", b.x - 78); marker.setAttribute("cy", b.y); marker.setAttribute("r", "4"); marker.setAttribute("fill", "#47d7b0"); svg.appendChild(marker);
  });
  nodes.forEach(node => {
    const p = positions[node.service], group = document.createElementNS(ns, "g");
    const feature = evidence[node.service];
    const status = !feature?.ready ? "Недостаточно данных" : anomalies.includes(node.service) ? "Обнаружена аномалия" : "Норма";
    const anomalous = status === "Обнаружена аномалия", insufficient = status === "Недостаточно данных";
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("x", p.x - 75); rect.setAttribute("y", p.y - 30); rect.setAttribute("width", "150"); rect.setAttribute("height", "60"); rect.setAttribute("rx", "12");
    rect.setAttribute("fill", anomalous ? "#351f20" : insufficient ? "#172226" : "#102b29");
    rect.setAttribute("stroke", anomalous ? "#ef6d67" : insufficient ? "#596d72" : "#3f756b"); group.appendChild(rect);
    const text = document.createElementNS(ns, "text"); text.setAttribute("x", p.x); text.setAttribute("y", p.y + 4); text.setAttribute("text-anchor", "middle"); text.setAttribute("fill", "#e9f2ef"); text.setAttribute("font-size", "13"); text.setAttribute("font-weight", "650"); text.textContent = node.service; group.appendChild(text); svg.appendChild(group);
    const title = document.createElementNS(ns, "title");
    title.textContent = `${node.service}\nСтатус: ${status}\nLatency Z: ${number(feature?.latency_z)}\nError Z: ${number(feature?.error_z)}\nДоля локального времени: ${percent(feature?.median_exclusive_ratio)}`;
    group.prepend(title);
    group.setAttribute("role", "img");
    group.setAttribute("tabindex", "0");
    group.setAttribute("aria-label", title.textContent.replaceAll("\n", ". "));
  });
}

function dagPositions(names, edges) {
  const incoming = Object.fromEntries(names.map(name => [name, 0])), outgoing = Object.fromEntries(names.map(name => [name, []]));
  edges.forEach(edge => { if (edge.source in outgoing && edge.target in incoming) { outgoing[edge.source].push(edge.target); incoming[edge.target]++; } });
  let queue = names.filter(name => incoming[name] === 0).sort(), level = 0, assigned = {}, visited = 0;
  while (queue.length) { const next = []; queue.forEach(name => { assigned[name] = level; visited++; outgoing[name].sort().forEach(target => { incoming[target]--; if (incoming[target] === 0) next.push(target); }); }); queue = [...new Set(next)].sort(); level++; }
  if (visited !== names.length) return circlePositions(names);
  const max = Math.max(...Object.values(assigned), 0), positions = {};
  for (let column = 0; column <= max; column++) { const group = names.filter(name => assigned[name] === column).sort(); group.forEach((name,index) => { positions[name] = { x: 105 + column * (510 / Math.max(1,max)), y: 165 + (index - (group.length-1)/2) * 95 }; }); }
  return positions;
}
function circlePositions(names) { const result = {}; names.forEach((name,index) => { const angle = 2*Math.PI*index/names.length; result[name] = { x: 360+220*Math.cos(angle), y:165+120*Math.sin(angle) }; }); return result; }

function setBusy(scope, busy, phase="idle") {
  const targets = scope === "live" ? ["#live-reset", "#live-traffic", ".scenario"] : ["#replay-analyze", "#replay-reveal", "#case-select"];
  targets.flatMap(value => $$(value)).forEach(value => value.disabled = busy || (value.id === "replay-reveal" && !state.prediction));
  const dot = $(`#${scope}-state-dot`);
  if (busy) {
    dot.className = `dot ${phase}`;
    dot.setAttribute("aria-label", STATE_LABELS[phase]);
  } else if (!dot.classList.contains("error")) {
    dot.className = "dot idle";
    dot.setAttribute("aria-label", "ожидание");
  }
  if (busy) setHeaderState(phase);
}
function setHeaderState(value) { const element = $("#header-state"); element.textContent = STATE_LABELS[value] || value; element.className = `state-${value}`; }
function fail(error, scope="global") { setHeaderState("error"); const dot = $(`#${scope}-state-dot`); if (dot) { dot.className = "dot error"; dot.setAttribute("aria-label", "ошибка"); } showError(scope, error); toast(friendlyError(error.message || String(error)), true); }
function selectScenario(value) { $$(".scenario").forEach(button => button.classList.toggle("active", button.dataset.scenario === value)); }
function selectedCase() { const index = $("#case-select")?.selectedIndex ?? 0; return state.cases[index] || state.cases[0]; }
function humanScenario(value) { return SCENARIO_LABELS[value] || value; }
function jsonPost(value) { return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) }; }
async function api(path, options={}, timeout=12000) { const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout); try { const response = await fetch(path, { ...options, signal: controller.signal }); const body = await response.json(); if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`); return body; } catch (error) { if (error.name === "AbortError") throw new Error("Операция заняла слишком много времени; проверьте состояние Collector и RCA."); throw error; } finally { clearTimeout(timer); } }
function rows(values) { return Object.entries(values).map(([key,value]) => `<span${metadataTooltip(key)}>${escapeHTML(key)}</span><b>${escapeHTML(String(value ?? "нет данных"))}</b>`).join(""); }
function evidenceItem(service, values) { return `<div class="evidence-item"><small>СЕРВИС</small><b>${escapeHTML(service)}</b><div class="metadata">${rows(Object.fromEntries(values))}</div></div>`; }
function percent(value) { return Number.isFinite(Number(value)) ? `${(Number(value)*100).toFixed(1)}%` : "нет данных"; }
function number(value) { return Number.isFinite(Number(value)) ? Number(value).toFixed(3) : "нет данных"; }
function signed(value) { return Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(3)}` : "нет данных"; }
function signedPoints(value) { return Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? "+" : ""}${(Number(value)*100).toFixed(1)}` : "нет данных"; }
function pointsInterval(value) { return `[${signedPoints(value.ci_low)}, ${signedPoints(value.ci_high)}]`; }
function scalarInterval(value) { return `[${signed(value.ci_low)}, ${signed(value.ci_high)}]`; }
function statusClass(value) { const normalized = value.toLowerCase(); if (normalized.includes("reject")) return "rejected"; if (normalized.includes("partial")) return "partially"; if (normalized.includes("qualification")) return "qualified"; return "supported"; }
function statusLabel(value) { const normalized = value.toLowerCase(); if (normalized.includes("reject")) return "ОТВЕРГНУТО"; if (normalized.includes("partial")) return "ЧАСТИЧНО ПОДТВЕРЖДЕНО"; if (normalized.includes("qualification")) return "ПОДТВЕРЖДЕНО С ОГОВОРКОЙ"; if (normalized.includes("descriptive")) return "ОПИСАТЕЛЬНЫЙ РЕЗУЛЬТАТ"; return "ПОДТВЕРЖДЕНО"; }
function signalLabel(value) { return ({ latency: "задержка", error: "ошибки", mixed: "смешанный сигнал" })[value] || value; }
function evidenceGroup(value) { return ({ Metrics: "Метрики", Traces: "Трассировки", Topology: "Топология", metrics: "Метрики", traces: "Трассировки", topology: "Топология" })[value] || value; }
function evidenceDirection(value) { return ({ raise: "повышает позицию", lower: "понижает позицию", increases: "повышает позицию", decreases: "понижает позицию", "raises ranking": "повышает позицию", "lowers ranking": "понижает позицию" })[value] || value; }
function architectureLabel(value) { return ARCHITECTURE_LABELS[value] || ({
  "Metrics + distributed traces": "Метрики и распределённые трассировки",
  "Automatically reconstructed topology": "Автоматически восстановленная топология",
  "Robust statistical and fixed-time temporal feature extraction": "Статистические и временные признаки",
  "Service-invariant diagnostic representation": "Независимое от имён сервисов представление",
  "LambdaMART Learning-to-Rank": "LambdaMART Learning-to-Rank",
  "Top-K root-cause services": "Top-K возможных первопричин",
  "Machine-readable evidence and predictive explanation": "Объяснение вклада признаков",
})[value] || value; }
function topologySourceLabel(value) { return value === "active_traces" ? "Граф текущего инцидента" : value; }
function metadataTooltip(key) {
  const descriptions = {
    "Доля локального времени": "Технический термин: exclusive observed duration ratio. Доля времени без ожидания downstream-вызовов; это не CPU time.",
    "Согласованность с графом (F1)": "Показывает, насколько наблюдаемое распространение симптомов соответствует гипотезе о данном сервисе как источнике сбоя.",
  };
  return descriptions[key] ? ` class="metadata-help" tabindex="0" title="${escapeHTML(descriptions[key])}" aria-label="${escapeHTML(`${key}: ${descriptions[key]}`)}"` : "";
}
function startProgress(scope, steps) {
  stopProgress(scope);
  const element = $(`#${scope}-progress`);
  element.classList.remove("hidden");
  state.progress ||= {};
  state.progress[scope] = steps.map(([delay, label]) => setTimeout(() => {
    element.innerHTML = `<span class="progress-marker" aria-hidden="true"></span><b>${escapeHTML(label)}</b>`;
  }, delay));
}
function stopProgress(scope) {
  (state.progress?.[scope] || []).forEach(clearTimeout);
  if (state.progress) state.progress[scope] = [];
  const element = $(`#${scope}-progress`);
  if (element) { element.classList.add("hidden"); element.textContent = ""; }
}
function clearError(scope) { const element = $(`#${scope}-error`); if (element) { element.classList.add("hidden"); element.textContent = ""; } }
function showError(scope, error) {
  const technical = error?.message || String(error);
  const message = friendlyError(technical);
  const element = $(`#${scope}-error`);
  if (!element) return;
  element.innerHTML = `<b>${escapeHTML(message)}</b><details><summary>Подробности</summary><code>${escapeHTML(technical)}</code></details>`;
  element.classList.remove("hidden");
}
function friendlyError(value) {
  const message = value.toLowerCase();
  if (message.includes("timeout") || message.includes("слишком много времени")) return "Операция превысила допустимое время.";
  if (message.includes("prepared") || message.includes("demo-prepare") || message.includes("case missing")) return "Подготовленный benchmark-case отсутствует.";
  if (message.includes("python") || message.includes("inference") || message.includes("prediction")) return "Не удалось выполнить Python inference.";
  if (message.includes("collector")) return "OpenTelemetry Collector недоступен.";
  if (message.includes("rca") || message.includes("connection refused") || message.includes("failed to fetch")) return "Сервис RCA или телеметрия недоступны.";
  if (message.includes("address already in use") || message.includes("port conflict")) return "Не удалось запустить сервис: порт уже занят.";
  return "Не удалось выполнить операцию.";
}
function setText(selector, value) { const element = $(selector); if (element) element.textContent = value; }
function escapeHTML(value) { return String(value).replace(/[&<>'"]/g, character => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" })[character]); }
function toast(message, error=false) { const element = $("#toast"); element.textContent = message; element.className = `toast show${error ? " error" : ""}`; clearTimeout(toast.timer); toast.timer = setTimeout(() => element.className = "toast", 5000); }
