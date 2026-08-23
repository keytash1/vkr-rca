# CODEX_HANDOFF.md

## 0. Назначение этого файла

Этот файл переносит рабочий контекст из длинного ChatGPT-диалога в Codex.

Главная задача на текущий момент: **начать разработку MVP ВКР по теме RCA (Root Cause Analysis) для распределённых микросервисных систем**.

Важно: не нужно заново выбирать тему, не нужно начинать с архитектурного ресёрча на десятки страниц и не нужно раздувать scope. Сначала должен появиться работающий MVP v0.1, который можно показать преподавателю.

---

# 1. Контекст ВКР

Направление обучения: **09.03.04 «Программная инженерия»**.  
Профиль: **«Интеллектуальные системы поддержки принятия решений»**.

Критерии преподавателя для выбора темы, в порядке приоритета:

1. **Актуальность**.
2. **Интересность**.
3. **Реализуемость**.

Тема должна быть прикладной, достаточно серьёзной для ВКР, желательно иметь исследовательскую/интеллектуальную часть и нормальный эксперимент.

В ходе большого отбора было сформировано 30 тем. Они не забыты и не отменены. После жёсткой фильтрации главными кандидатами стали:

1. №18 — интеллектуальная СППР по приоритизации устранения программных уязвимостей при ограниченных ресурсах.
2. №11 — интеллектуальная СППР по выбору регрессионных тестов при ограниченном времени тестирования.
3. №1 — интеллектуальная система диагностики и локализации первопричин сбоев в распределённых программных системах.
4. №6 — интеллектуальная СППР при поэтапном развертывании версий ПО.
5. №4 — интеллектуальная СППР при изменении API в микросервисной архитектуре.
6. №8 — интеллектуальная СППР по выбору генеративной модели для запроса.

Текущий практический выбор для MVP: **№1 RCA microservices**.

№4 API change decision остаётся быстрым резервным MVP, но прямо сейчас кодим RCA.

---

# 2. Почему выбран RCA MVP

Рабочая тема:

**«Интеллектуальная система диагностики и локализации первопричин сбоев в распределённых программных системах»**

Проблема:

В распределённой системе один дефектный компонент часто вызывает симптомы сразу во многих сервисах.

Пример:

```text
Client → Gateway → Orders → Payment
```

Если `Payment` начинает отвечать на 700 мс медленнее, то:

- Payment деградирует;
- Orders ждёт Payment и тоже становится медленным;
- Gateway ждёт Orders и тоже становится медленным.

Обычный мониторинг показывает три аномальных сервиса.

RCA должен ответить:

> первопричина — Payment, а деградация Orders и Gateway является следствием.

Именно автоматическая локализация первопричины, а не сбор телеметрии, является ядром диплома.

---

# 3. Цель MVP v0.1

Собрать минимальную распределённую систему из трёх Go-сервисов:

```text
Client → Gateway → Orders → Payment
```

Система должна:

1. генерировать distributed traces;
2. автоматически восстанавливать граф зависимостей сервисов из telemetry;
3. иметь healthy baseline;
4. позволять искусственно внедрять fault в Orders или Payment;
5. обнаруживать аномальные компоненты;
6. ранжировать вероятные root-cause candidates;
7. правильно выбирать Payment, когда fault внедрён в Payment;
8. правильно выбирать Orders, когда fault внедрён в Orders;
9. показывать результат в простой web-странице;
10. запускаться одной командой через Docker Compose.

---

# 4. Definition of Done v0.1

MVP НЕ считается законченным, пока не выполнены все пункты:

- [ ] `docker compose up --build` поднимает весь проект.
- [ ] Gateway → Orders → Payment реально выполняют цепочку запросов.
- [ ] Один distributed trace проходит через все три сервиса.
- [ ] Trace можно увидеть в Jaeger или совместимом trace UI.
- [ ] Service graph строится из telemetry, а не захардкожен.
- [ ] Есть healthy baseline.
- [ ] Есть fault injection для Orders.
- [ ] Есть fault injection для Payment.
- [ ] Есть latency fault.
- [ ] Есть error-rate fault.
- [ ] RCA выдаёт ranking всех сервисов.
- [ ] Fault в Payment → Payment занимает Top-1.
- [ ] Fault в Orders → Orders занимает Top-1.
- [ ] Есть минимум три воспроизводимых demo scenario.
- [ ] Есть unit tests для RCA scoring.
- [ ] Есть простая HTML web-страница.
- [ ] README содержит запуск и сценарий демонстрации.

---

# 5. Жёсткие non-goals для v0.1

Не делать сейчас:

- Kubernetes;
- Kafka;
- PostgreSQL;
- отдельный React frontend;
- LLM;
- нейросеть;
- полноценный AIOps;
- 10–20 микросервисов;
- сложную causal inference;
- production-grade ML anomaly detector;
- enterprise auth;
- fancy UI;
- отдельные репозитории на каждый сервис.

Если что-то из этого не требуется напрямую для Definition of Done — отложить.

---

# 6. Предлагаемая структура репозитория

Один Go module:

```text
vkr-rca/
├── cmd/
│   ├── gateway/
│   ├── orders/
│   ├── payment/
│   └── rca/
│
├── internal/
│   ├── telemetry/
│   ├── fault/
│   ├── graph/
│   ├── anomaly/
│   └── rca/
│
├── web/
│
├── deploy/
│   └── otel-collector.yaml
│
├── docker-compose.yml
├── Makefile
├── go.mod
├── go.sum
└── README.md
```

Допустимо немного скорректировать структуру, если это упростит Go-код, но не разводить unnecessary microservice repos.

---

# 7. Стек MVP

Основной стек:

- Go;
- Docker Compose;
- OpenTelemetry Go SDK;
- OpenTelemetry Collector;
- Jaeger для визуализации traces;
- встроенный `net/http` или лёгкий HTTP router;
- HTML/template для простого интерфейса.

Prometheus можно добавить, если он реально упрощает сбор текущих latency/error metrics. Но для первой версии допустимо считать агрегаты непосредственно из spans/telemetry, если это быстрее и чище.

---

# 8. Сервисы

## Gateway

Внешняя точка входа.

Пример endpoint:

```http
GET /api/order
```

Внутри вызывает Orders.

## Orders

Получает запрос от Gateway и вызывает Payment.

## Payment

Конечный downstream сервис.

Возвращает простой ответ.

Все сервисы должны:

- иметь `service.name`;
- создавать/продолжать OpenTelemetry trace context;
- логировать минимум request/trace identifiers при необходимости;
- иметь `/health`.

---

# 9. Fault Injection

Для Orders и Payment нужен debug API.

Минимально:

```http
POST /debug/fault
Content-Type: application/json
```

Пример:

```json
{
  "latency_ms": 700,
  "error_rate": 0.0
}
```

Сброс:

```http
POST /debug/reset
```

Также желательно:

```http
GET /debug/state
```

Fault config должен быть thread-safe.

Поддержать как минимум:

- `latency_ms`;
- `error_rate`.

Примеры:

```json
{"latency_ms":700,"error_rate":0}
```

```json
{"latency_ms":0,"error_rate":0.5}
```

---

# 10. Telemetry / Trace model

Нужно иметь доступ минимум к:

- trace_id;
- span_id;
- parent_span_id;
- service.name;
- operation/span name;
- start_time;
- end_time;
- duration;
- status/error.

Критично:

**не хардкодить Gateway → Orders → Payment в RCA engine.**

Граф должен восстанавливаться из parent-child relationships / service-to-service spans.

Ожидаемый результат:

```text
Gateway → Orders
Orders → Payment
```

---

# 11. Healthy baseline

До fault система должна выполнить серию нормальных запросов.

Например:

```text
30–50 requests
```

Для каждого сервиса сохранить baseline:

- latency mean/median;
- p95;
- error rate;
- желательно variance/MAD.

Для v0.1 не нужен сложный statistical model.

Главное — уметь сравнить текущее окно с baseline.

---

# 12. Anomaly score v0.1

Для каждого сервиса вычисляется:

```text
A(v) ∈ [0,1]
```

Начать с простого, объяснимого метода.

Например на базе:

- относительного роста p95 latency;
- роста error rate.

Пример логики:

```text
latency_ratio = current_p95 / max(baseline_p95, epsilon)
latency_score = normalized(latency_ratio)

error_delta = current_error_rate - baseline_error_rate
error_score = normalized(error_delta)

anomaly = w_latency * latency_score + w_error * error_score
```

Не нужно пытаться сразу сделать идеальную статистику.

---

# 13. RCA scoring v0.1

RCA не должен быть просто:

```text
root cause = max(anomaly)
```

Для каждого узла использовать несколько факторов.

Рабочая модель:

```text
R(v) =
    w1 * A(v)
  + w2 * G(v)
  + w3 * P(v)
  + w4 * T(v)
```

Где:

## A(v) — anomaly score

Насколько сам сервис аномален.

## G(v) — graph/dependency evidence

Насколько положение узла в dependency graph согласуется с тем, что он может быть источником деградации.

## P(v) — propagation explanation

Сколько наблюдаемых аномальных callers/upstream-сервисов может быть объяснено деградацией данного downstream-компонента.

Для:

```text
Gateway → Orders → Payment
```

если все три аномальны:

Payment способен объяснить Payment + Orders + Gateway.

Orders способен объяснить Orders + Gateway.

Gateway — в основном только Gateway.

## T(v) — temporal evidence

Насколько рано возникла собственная аномалия сервиса относительно других.

В v0.1 это может иметь небольшой вес.

Начальные веса могут быть эвристическими.

Они должны храниться централизованно и быть легко изменяемыми для будущего экспериментального исследования.

---

# 14. Важная логическая проверка RCA

Алгоритм НЕ должен просто всегда выбирать самый глубокий downstream node.

Пример:

```text
Gateway → Orders → Payment
```

Если fault внедрён непосредственно в Orders до/вокруг его собственного processing, а Payment остаётся нормальным:

```text
Gateway anomalous
Orders anomalous
Payment healthy
```

Root cause должен быть Orders.

Следовательно, downstream preference должна учитываться только при наличии фактической аномалии кандидата и согласованной propagation pattern.

---

# 15. Demo scenarios

Минимум три.

## Scenario A — Payment latency

Fault:

```json
{"latency_ms":700,"error_rate":0}
```

Ожидание:

```text
Top-1 root cause = Payment
```

## Scenario B — Orders latency

Fault:

```json
{"latency_ms":700,"error_rate":0}
```

на Orders.

Ожидание:

```text
Top-1 root cause = Orders
```

Payment должен оставаться здоровым.

## Scenario C — Payment errors

Fault:

```json
{"latency_ms":0,"error_rate":0.5}
```

Ожидание:

```text
Top-1 root cause = Payment
```

---

# 16. UI v0.1

Не делать React.

RCA service отдаёт одну простую HTML-страницу.

Пример:

```text
RCA DEMO

[ Warm up baseline ]

Fault injection:
[ Payment +700ms ]
[ Orders +700ms ]
[ Payment 50% errors ]
[ Reset ]

[ Generate requests ]

SERVICE GRAPH
Gateway → Orders → Payment

CURRENT INCIDENT

Service    p95     Error   Anomaly   RCA
Payment    714ms   0%      0.97      0.92
Orders     729ms   0%      0.86      0.48
Gateway    744ms   0%      0.78      0.23

ROOT CAUSE: PAYMENT
Confidence: 0.92

Evidence:
- Payment has a strong latency anomaly
- Orders depends on Payment
- Gateway depends on Orders
- observed degradation is consistent with propagation from Payment
```

UI должен быть функциональным, а не дизайнерским.

---

# 17. Milestones

Работать последовательно.

## Milestone 1 — сервисная цепочка

Сделать Gateway, Orders, Payment.

Проверка:

```text
curl Gateway
```

успешно проходит через все три сервиса.

Не двигаться дальше, пока это не работает.

## Milestone 2 — OpenTelemetry tracing

Добавить trace propagation.

Проверка:

в Jaeger виден один trace с тремя сервисами.

## Milestone 3 — Fault Injection

Orders и Payment можно ломать latency/error-rate настройками.

Проверка:

ручной запрос реально замедляется/ошибается.

## Milestone 4 — Telemetry ingestion + graph

RCA получает необходимые span data.

Строится service graph автоматически.

## Milestone 5 — Baseline + anomaly

Warm-up создаёт baseline.

После fault сервисы получают anomaly score.

## Milestone 6 — RCA ranking

Реализовать scoring и explanations.

Проверить scenario A/B/C.

## Milestone 7 — Web UI

Добавить одну demo page.

## Milestone 8 — Tests + README

Unit tests для graph/anomaly/RCA.

README с запуском и демонстрацией.

---

# 18. Правило разработки

Не пытаться написать весь проект одним большим коммитом.

После каждого milestone:

1. build;
2. tests;
3. run;
4. smoke-check;
5. только затем следующий milestone.

Если появляется выбор между «архитектурно идеально» и «надёжно работает для MVP», выбирать второе, если это не создаёт тупик для будущего диплома.

---

# 19. Что будет после v0.1

Не реализовывать это до завершения MVP, но учитывать при архитектуре.

Будущие направления:

- rolling baseline;
- robust statistics;
- Prometheus metrics;
- CPU/memory saturation faults;
- packet loss;
- DB fault;
- Kafka/broker lag;
- connection pool exhaustion;
- больше сервисов;
- автоматический experiment runner;
- ground-truth fault labels;
- Top-1 RCA accuracy;
- Top-3 RCA accuracy;
- Mean Time to Localization;
- сравнение baselines:
  - max anomaly;
  - earliest anomaly;
  - correlation;
  - graph-only;
  - hybrid RCA;
- ablation study;
- OpenTelemetry Demo как большой внешний benchmark.

Будущая исследовательская идея:

```text
Graph + anomaly + timing + propagation
```

против более простых RCA baselines.

---

# 20. Академическая формулировка будущей ВКР

Рабочее название:

**«Интеллектуальная система диагностики и локализации первопричин сбоев в распределённых программных системах»**

Объект:

**процесс функционирования и диагностики распределённых программных систем.**

Предмет:

**методы анализа телеметрии и графов зависимостей для локализации первопричин сбоев распределённых сервисов.**

Цель:

**сократить время локализации первопричины инцидента путём автоматического анализа взаимосвязей между аномалиями компонентов системы.**

---

# 21. Почему это не «просто observability»

OpenTelemetry / Jaeger / Prometheus являются источниками данных и инфраструктурой.

Собственный результат:

- построение диагностического представления;
- anomaly model;
- dependency-aware RCA;
- ranking root-cause candidates;
- explanations;
- экспериментальная оценка качества локализации.

Если итог проекта будет только «мы подключили OpenTelemetry и нарисовали traces», задача считается проваленной.

---

# 22. Резервная тема №4 — API Change Decision

Не реализовывать сейчас без отдельного решения пользователя.

Контекст:

У пользователя на работе уже есть робот, который обнаруживает потенциальные breaking changes YAML/OpenAPI-схем, например:

```text
required_added:
field ID_FLOW_INST became required
```

и просит человека Resolve/Drop.

Идея №4 идёт дальше:

```text
breaking change
+
consumer dependency graph
+
consumer readiness
+
criticality
+
runtime traffic
=
SAFE / VERIFY / MIGRATE / BLOCK
```

Эта тема сохраняется как очень быстрый альтернативный MVP, но текущая работа — RCA.

---

# 23. Остальные сильные темы не забыты

Особенно:

## №11 Regression Test Selection

Очень сильный кандидат окончательной ВКР.

Идея:

```text
git diff
+ dependency graph
+ test history
+ coverage
+ duration
→ test ranking
→ subset under time budget
```

Будущий эксперимент — mutation testing.

## №18 CVE prioritization

СППР выбора множества CVE для remediation при ограниченных developer-hours.

## №6 Intelligent Rollout

Метрики canary-релиза → `PROMOTE / HOLD / ROLLBACK`.

Эти темы остаются в shortlist. Разработка RCA MVP не означает, что окончательная тема уже зафиксирована навсегда.

---

# 24. Первая задача для Codex

Начать с **Milestone 1**.

Создать минимальный Go-проект с Docker Compose и тремя сервисами:

```text
Gateway → Orders → Payment
```

Требования Milestone 1:

- один Go module;
- каждый сервис имеет `/health`;
- Gateway имеет пользовательский endpoint;
- Gateway вызывает Orders;
- Orders вызывает Payment;
- корректные HTTP timeouts;
- graceful shutdown;
- структурированные логи;
- Dockerfiles или единый multi-stage Dockerfile;
- `docker compose up --build` работает;
- basic unit/smoke tests;
- Makefile с удобными командами;
- README с запуском.

После завершения Milestone 1:

1. запустить тесты;
2. поднять compose;
3. выполнить smoke request;
4. показать изменённые файлы и результаты;
5. НЕ переходить к Milestone 2, если Milestone 1 не подтверждён.

---

# 25. Стиль взаимодействия с пользователем

Пользователь — backend Go-разработчик и будет просматривать решения технически.

Поэтому:

- не объяснять базовый Go как новичку;
- писать production-adjacent код, но не overengineer;
- показывать конкретные trade-offs;
- не скрывать технические проблемы;
- при ошибках сначала диагностировать и исправлять;
- тестировать изменения;
- не менять scope без причины;
- не переписывать всё без необходимости;
- сохранять решения, уже согласованные в этом handoff.

---

# 26. Ключевой принцип

Сначала:

> **работающий, воспроизводимый RCA MVP.**

Потом:

> усложнение алгоритма и полноценная исследовательская ВКР.

Не наоборот.
