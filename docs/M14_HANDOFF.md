# VKR RCA — полный handoff после M14

Актуально на 13 сентября 2026 года. Это продолжение master handoff после M13.1,
а не новое задание на улучшение модели. M14 выполнен; следующий этап —
продуктовая интеграция, демонстрация и написание ВКР.

## 1. Главный итог

**M14 = SUPPORTED_TRANSFER. Исследование = FINAL_RESEARCH_FREEZE.**

Однократный финальный тест замороженного M13 на OpenTelemetry Astronomy Shop
завершён на всех 50 запланированных инцидентах / 25 кластерах. M13 статистически
обошёл chance, generic metric heuristic и frozen M11 по AC@1 и MRR. Однако
порог STRONG_TRANSFER не достигнут: AC@3=.70 < .80, AC@5=.78 < .90.

После вскрытия Astronomy Shop имеет роль **USED_TEST**. Нельзя дообучать модель,
подбирать признаки, пороги, reliability, архитектуру или новый challenger по
этим данным. Отрицательные частные результаты не дают разрешения на «ещё одну
сильную итерацию». Новые тестовые системы, GNN, LLM scorer, логи, события и
incident memory не входят в следующий этап.

## 2. Репозиторий и точка передачи

- Репозиторий: https://github.com/keytash1/vkr-rca
- Локальная папка: `/Users/maxryabets/Desktop/vkr-rca`.
- Рабочая ветка: `research/m14-final-locked-transfer`.
- База M13.1: `cd912c0ea561c68c6b254d73cdd88c86ecc68b95`.
- Seal до scoring: `669d49a82c719ebc27921b45895c59a8a21107fd`.
- Prediction marker до открытия truth: коммит `053f5ea`.
- Полные результаты и final freeze: **`f1c47483c369a961badaa7c47295c9759452f549`**.
- Сам этот handoff добавлен отдельным последующим коммитом.
- `main` не меняли и не сливали с исследовательской веткой. Локальный `main`
  при передаче: `5e8bd3523c1e192296a58e69fdcc10f328b5f233`.

Проверять реальную ветку/коммит, а не старый GitHub main или один этот текст.
Пользователь требует commit + push после milestones; изменение main требует
отдельного разрешения. Не создавать PR и не делать merge автоматически.

Пользовательские `VKR_RCA_MASTER_ROADMAP_FINAL.md` и `diplomboost.md` остались
нетронутыми/untracked. Не добавлять их в Git и не очищать без запроса.

## 3. Контекст ВКР и предыдущие результаты

Пользователь делает ВКР РТУ МИРЭА: интеллектуальная поддержка диагностики причин
сбоев распределённых сервисов. Направление и контролируемые Docker-эксперименты
одобрены преподавателем. Основное отличие работы — supervised Learning-to-Rank
на identity-free мультимодальном диагностическом представлении, а не просто
наличие графа вызовов. Нужны доказательные, ограниченные выводы и рабочая система;
не нужен бесконечный ML research.

Есть Go-цепочка Gateway → Orders → Payment, OTLP/Jaeger, граф, baseline/anomaly/RCA,
fault controls и offline defense demo. Позднейший исследовательский M13 не
становится автоматически текущим live-движком этого демо. Финальная интеграция
замороженного inference ещё относится к следующему продуктовому этапу.

Исторический контекст сохранён без переписывания:

- M12 Hotel Reservation: слабый перенос M11; AC@1=.54, MRR=.6797 против
  эвристики .64/.7202; trace-to-feature адаптация была частичной. Не стирать
  этот отрицательный результат после удачного M14.
- M13 Social Network: 120 development-инцидентов / 60 кластеров; выбран
  full-candidate LambdaMART. Grouped OOF AC@1=.8917, MRR=.9367. Trace incremental
  value и propagation поддержаны; disappearance — только PARTIALLY_SUPPORTED;
  GNN — NOT_JUSTIFIED.
- M13.1: строгая nested grouped оценка процедуры выбора, AC@1=.8833,
  AC@3=.9917, AC@5=1.00, MRR=.9354. FINAL_TEST_READY=YES. Это development-оценка,
  не финальный cross-system test и не повод заменить frozen M13 новыми весами.
- M14: именно одно финальное испытание на новом стенде; результаты ниже.

Разные системы/протоколы нельзя выдавать за одну pooled-выборку или обещать
сохранение development accuracy в произвольной новой системе.

## 4. Что именно было заморожено

Модель: M13 `full_candidate_challenger`, ансамбль пяти XGBoost LambdaMART:
63 признака, `max_depth=3`, `eta=0.08`, 24 boosting rounds.

SHA-256 пяти файлов `ml/models/m13/diagnostic-ranker-seed-*.json`:

| Seed | SHA-256 |
|---|---|
| 20260906 | `e9fd8952daf1ae4a1839019d696e2a8152bb180cce93ff7bf7c9dc3382cba510` |
| 20260907 | `1849a2b01794f11e50f5f7cb8c13583148da6fa7f019d6c221a06a4756a2d4c2` |
| 20260908 | `2cd7b29743d2698f9f02c9f66ad48eaa0516072495c2ec98ec77f240aaf64ca8` |
| 20260909 | `1e3d7e8de8d9803a7a78715564c04b50d27e0e62ac19fe4d12b8ce288f332363` |
| 20260910 | `c10660f0f7b85d6e28e879e405c19cfadbfd0497c5a1ec4a9f0b89d20fbe6673` |

Канонические resource metrics + native spans → healthy-only expectations /
expected edges → metric, trace, propagation и disappearance features → frozen
M11 ranking context → M13 full-candidate ranking. Service names — join keys,
не learned features. Score не является вероятностью или causal proof.

M14 добавил deployment/collection adapter и wrapper для неизменённых M13
функций/моделей. Файлы M13 runtime/features/trace, модели M11/M13, результаты и
integrity M13.1, Makefile побайтово совпадают с базой. Новых training runs нет.
Для новой системы до инъекций fitted только healthy baselines — это не tuning
по fault labels.

## 5. Locked-протокол и данные

Upstream: OpenTelemetry Astronomy Shop,
`8c47d47c9ac27710d2b2a153bcd53e483bffe66d`, Apache-2.0.

12 кандидатов: ad, cart, checkout, currency, email, frontend, frontend-proxy,
payment, product-catalog, quote, recommendation, shipping.

5 roots: ad, cart, frontend, payment, recommendation. Пять семейств:
CPU (один busy worker), memory (32 MiB resident allocation), network latency
(netem 200 ms), packet loss (15%), service unavailable (Docker pause).
Каждая root/fault пара повторена дважды: 50 инцидентов, 25 кластеров.
Порядок один раз перемешан с seed `20260912`.

Нагрузка: 6 операций/сек, равные доли product / recommendation / ad / cart /
checkout. Операция checkout делает несколько HTTP-запросов: ops/s не следует
называть точным HTTP RPS. Warm-up 300 секунд, healthy baseline 900 секунд,
инцидент 30 секунд, cooldown 5 секунд. Опоздавшие HTTP-запросы дренируются после
reset, но окно не расширяется.

Четыре семейства метрик: CPU cores, working-set bytes, network RX+TX bytes/s,
traffic_rate=RX bytes/s. Последнее — не request rate. Docker exporter/Prometheus
с шагом 1 сек; native OTLP → Jaeger → неизменённый canonical trace adapter M13.

Healthy:

- warm-up: 1,800/1,800 HTTP 200;
- baseline: 5,400/5,400 HTTP 200, по 1,080 операций каждого типа;
- 43,248 samples, все 48 service/family пар, 123,218 native spans;
- обе target baseline-модели fitted до первой injection.

Canary: пять механизмов прошли, rankings не генерировались. Первый canary
прервался на несовместимом формате `docker top`; после исправления на
`-eo pid,args` вся пятёрка пройдена. Это не инцидент финального корпуса.

Корпус:

- 50/50 инцидентов, ровно 25 кластеров с двумя повторениями;
- во всех окнах ровно 30 секунд и все 48 пар метрик;
- 190,039 spans, диапазон 8–4,110 на окно;
- 9,000 операций: 8,366 HTTP 200, 633 transport errors/timeouts с кодом 0,
  один HTTP 503; ошибки под fault не исключались из знаменателя;
- 51 измеренная попытка: одна отклонена механически, затем разрешённый retry;
- единственный retry — `m14-018-0ce346bc`, Payment/memory. Agent присутствовал,
  но первый observed max 192,450,560 B был ниже healthy p90 180,199,424 B +
  16 MiB. Второй прошёл при тех же 32 MiB и том же пороге. Обе попытки сохранены;
- никаких exclusions по качеству RCA, выдуманных данных или downsizing до 30.

SHA-256:

- healthy raw: `9b96041ada41a356cf6ac5e3b8bae13765530449212954946c62636cbdff631e`;
- truth: `ea9d629df71adfcd292b6e650d57d2c724ee3e6c2bc5c46b98fbcb110128f195`;
- telemetry index: `a8786c0fb20267fec9efec15fe27e33f56b55848d73af32a86afe9505a9d80ba`;
- sealed predictions: `c1e8476820796308803bdd97f59591dfcd7b8d48bfdde3a58458cba27de53e49`.

Seal опубликован до scoring. Scorer прочитал telemetry, но не truth. После
единственного scoring prediction hash закоммичен до открытия truth. Opening
запускался один раз; повторных model runs после просмотра результата нет.

## 6. Полные основные результаты

| Метод | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | .06 | .16 | .22 | .34 | .72 | .226346 | 1.00 |
| Metric heuristic | .30 | .44 | .46 | .64 | .82 | .455503 | 1.00 |
| Frozen M11 | .16 | .40 | .48 | .56 | .88 | .382322 | 1.00 |
| Frozen M13 | .50 | .64 | .70 | .78 | .88 | .629955 | 1.00 |

Wilson 95% CI для M13: AC@1 [.366445, .633555], AC@2 [.501410, .758613],
AC@3 [.562496, .808964], AC@5 [.647585, .872461], AC@10 [.761952, .943824].

10,000 paired incident и 10,000 paired cluster bootstrap; primary gate —
cluster CI на 25 root/fault кластерах. Delta означает M13 минус comparator.

| Comparator | Δ AC@1 | Cluster CI 95% | Δ MRR | Cluster CI 95% |
|---|---:|---|---:|---|
| Chance | .44 | [.26, .62] | .403608 | [.240950, .556892] |
| Metric heuristic | .20 | [.04, .36] | .174452 | [.058594, .302740] |
| Frozen M11 | .34 | [.18, .52] | .247633 | [.094974, .407842] |

Все шесть интервалов положительны. Но STRONG_TRANSFER требует ещё AC@3≥.80 и
AC@5≥.90, а их point-estimate gates провалены. Поэтому строго
**SUPPORTED_TRANSFER**, а не «почти STRONG». Catastrophic fault families по
зарегистрированному определению — 0/5.

### M13 по fault family, n=10 в каждой группе

| Fault | AC@1 | AC@3 | AC@5 | MRR |
|---|---:|---:|---:|---:|
| CPU | .80 | .80 | .90 | .830000 |
| Memory | .50 | .80 | .90 | .668333 |
| Network latency | .50 | .60 | .60 | .590682 |
| Packet loss | .30 | .50 | .70 | .477424 |
| Service unavailable | .40 | .80 | .80 | .583333 |

### M13 по root, n=10 в каждой группе

| Root | AC@1 | AC@3 | AC@5 | MRR |
|---|---:|---:|---:|---:|
| Ad | .40 | .50 | .50 | .496515 |
| Cart | .60 | .90 | 1.00 | .741667 |
| Frontend | .50 | .70 | .70 | .625758 |
| Payment | .10 | .40 | .70 | .335833 |
| Recommendation | .90 | 1.00 | 1.00 | .950000 |

Macro-fault и macro-root совпадают с pooled из-за сбалансированного дизайна.
Полные AC@1/2/3/5/10, coverage, MRR всех четырёх методов во всех группах, worst
metric-wise minima и все интервалы сохранены в отчёте/JSON, а не только в этом
сокращённом представлении.

## 7. Ошибки и границы вывода

25 SUCCESS_AT_1; 10 ошибок рангов 2–3; четыре ранга 4–5; пять рангов 6–10;
шесть рангов 11–12. Candidate-universe misses — 0. Это ошибки порядка, а не
отсутствие root среди кандидатов.

Особенно важны повторяющиеся провалы: frontend/unavailable → rank 12 в обоих
повторах (в каждом лишь восемь spans); ad/latency → rank 11 в обоих повторах;
payment/latency → ranks 8 и 10. Payment Top-1 всего 1/10. Не скрывать это за
положительной общей статистикой. Descriptive flags — гипотезы/контекст, не
истинные causal labels. Одинаковый флаг OOD сам по себе не объясняет ошибку.

Допустимый вывод: frozen identity-free learned ranking показал перенос на один
новый контролируемый стенд для пяти представленных при разработке семейств и
улучшил AC@1/MRR относительно указанных baseline-методов.

Недопустимые выводы: universal RCA, arbitrary unseen fault-family transfer,
доказанная причинность, calibrated confidence/probability, production readiness,
измеренное сокращение MTTR, одинаковая надёжность для всех сервисов.

Один host/run, одна нагрузка, два повтора на кластер, короткие окна, возможный
carryover и сторонняя нагрузка. Bootstrap не устраняет эти ограничения.
Механический критерий CPU/memory выбирает наблюдаемые resource injections;
это не оценка всех слабосигнальных реальных сбоев. 32 MiB allocation не доказывает
OOM или реальное истощение памяти. Native traces собираются через frontend
traces, а не гарантируют полную фоновую observability.

## 8. Инженерные отклонения и восстановление после очистки ноутбука

После освобождения диска завершены source builds и прогон. Host ARM64 macOS
26.3.1 / Python 3.14.5; Docker 29.2.1 / Colima 2 CPU / 8,308,269,056 bytes RAM
(около 7.74 GiB). Параллельно работали 10 контейнеров соседнего проекта; их не
останавливали и не чистили. Co-load раскрыт как ограничение.

До принятого healthy baseline потребовались воспроизводимо описанные изменения:

1. Quote: build-only `composer audit.block-insecure=false` для исторического
   dependency constraint. Не обновляли бизнес-код; не считать это безопасной
   production-конфигурацией.
2. Ad: увеличенные Gradle transport timeout/retries и wget retry для той же
   Java-agent версии. Это сборочная совместимость, не новая instrumentation.
3. Noncandidate image-provider: официальный pinned 3.0.0 digest. Неиспользуемые
   load-generator/flagd-ui/telemetry-docs заменены inert support containers.
   У inert load-generator inherited healthcheck был unhealthy; в качестве
   генератора нагрузки он не использовался.
4. Collector: восстановлены upstream profiles feature gate и span_metrics
   connector, добавлен Jaeger; исправлены зависимости pipeline.
5. Закрыты случайные host-порты upstream, наружу только четыре loopback bindings.
6. После документированного PostgreSQL cgroup OOM на 80 MiB его лимит стал
   512 MiB. После дальнейших неуспешных smoke gates ДО baseline всем 12
   кандидатам задан одинаковый лимит 512 MiB; Go soft limit Checkout/Catalog —
   384 MiB. Ни одного изменения ресурсов после принятого baseline.
7. Exporter отбрасывает stale/неуспешные samples вместо имитации свежих данных.
   Окна injection привязаны к start+30s, а compile/copy агента вынесены до окна.
8. Исправлен формат Docker top; включён audit всех измеренных попыток и запрет
   перезаписи сборки после seal. Научный метод/интенсивности не менялись.

Все исходные неудачные smoke-результаты, механизм исправлений и пределы
интерпретации описаны в `docs/m14-engineering-log.md`. Финальный healthy gate
прошёл полностью. После корпуса все 12 image IDs совпали с readiness;
у кандидатов и БД ноль restart, current OOMKilled=false, pause сняты.

Image IDs и среды опубликованы в `ml/models/m14/environment-summary.json`.
Это идентификаторы реально использованных образов, а не обещание byte-identical
будущей пересборки: часть upstream transitive dependencies не имеет lock.
Образы локальные, в registry не публиковались.

## 9. Артефакты, которые нужно читать

От корня репозитория:

- `docs/m14-protocol.md` — неизменённая preregistration и gates.
- `docs/m14-results.md` — полный отчёт, все методы/срезы/интервалы/лимиты.
- `docs/m14-error-analysis.md` — все 25 ошибок и повторяющиеся провалы.
- `docs/m14-claim-registry.md` — окончательные разрешённые/запрещённые claims.
- `docs/final-research-freeze.md` — границы дальнейшей работы.
- `docs/m14-engineering-log.md`, `docs/m14-runbook.md` — операции и отклонения.
- `ml/models/m14/evaluation.json` — полная машиночитаемая статистика.
- `ml/models/m14/evaluation-inputs.json` — compact truth + четыре ranking sets
  для независимого пересчёта метрик; USED_TEST, никогда не training data.
- `ml/models/m14/collection-audit.json` — 51 attempt hash, 50 принятых окон,
  counts, signals и отклонённая попытка.
- `ml/models/m14/data-ledger.json` — актуальные роли данных.
- `ml/models/m14/freeze-manifest.json`, `frozen-inputs.json` — seal до scoring.
- `ml/models/m14/scoring-completed.marker`, `evaluation-opened.marker` —
  последовательность однократного scoring/opening.
- `ml/models/m14/final-research-freeze.json` — проверенный SHA-256 inventory
  330 файлов, включая исторические исследования, code, models и deployment.
- `scripts/m14/report.py` — только оформление уже открытых данных, без model
  inference/обучения. Его повторный запуск не является новым экспериментом.

Исторический `freeze-manifest.json` намеренно остаётся SEALED_UNSCORED:
это зафиксированный snapshot ДО scoring. Текущий USED_TEST/FINAL_FREEZE
устанавливается отдельными opening marker, evaluation, ledger и final manifest.
Не «чинить» старый snapshot, меняя его хеши.

## 10. Проверки и состояние ноутбука

В этом завершении:

- `go test ./...` — PASS, включая M14 exporter; часть результатов из Go cache.
- `PYTHONPATH=ml .venv/bin/python -m unittest discover -s ml/tests` —
  **138 tests, PASS** (78.336 s).
- M14 subset после формирования отчёта — **12 tests, PASS**.
- Пересчёт pooled metrics из опубликованных truth/rankings совпадает с evaluation.
- Все 330 хешей final inventory проверены; `git diff --check` — PASS.
- Старые M11/M13/M13.1 артефакты и ключевой код не изменены.
- PyArrow вывел sandbox sysctl warnings; тесты завершились успешно. Это не
  исключённые тесты и не ошибка эксперимента.
- Новый product UI/M13-live E2E в этом milestone не реализовывался и не заявлен.

После оценки выполнен scoped Compose down: контейнеры и сеть **только M14**
удалены, исходники/образы/raw files/volumes не удалялись. M14-контейнеров больше
нет. Ephemeral in-memory Jaeger state прекратился вместе со стендом; собранная
каноническая телеметрия сохранена. Соседний проект не затронут. Временный
`caffeinate` выключен; постоянные настройки сна не менялись.

Raw run directory: `/Users/maxryabets/Desktop/vkr-rca/external-data/m14/runs/locked-v1`
— около 154 MiB. Это исследовательские данные, не мусор для очистки. Не удалять
их, `.git`, model artifacts, source-built images или Colima/Lima VM без отдельного
согласования и проверенной резервной копии. Никаких Docker prune здесь не было.

## 11. Точная следующая задача другой ИИ

Сначала прочитать реальные M14 results/claims/freeze и проверить опубликованный
commit. Принять итог SUPPORTED_TRANSFER с указанными ограничениями. Не продолжать
M11/M13 tuning по инерции старого диалога.

Затем сформировать ограниченный продуктовый этап: интеграция уже frozen M13
inference в существующее приложение с тем же mathematical contract, понятным
model version/evidence/missingness, воспроизводимое demo и отдельные unit,
integration, regression, E2E software tests. Уточнить желаемый формат API/демо
перед значимой сменой runtime architecture. Research core не менять.

Далее экспериментальная глава (M12 negative → M13 development → M13.1 nested →
M14 held-out), архитектурная глава, литература/введение с реальными источниками
и полный текст ВКР. Преподаватель отдельно требует не смешивать тестирование
ПО с оценкой RCA-качества, обосновывать вводные утверждения источниками и избегать
повторяющегося шаблонного текста.

**Главный стоп-сигнал: финальный экзамен уже состоялся. Следующая работа —
доставка замороженного метода пользователю и написание ВКР, не ещё один цикл ML.**
