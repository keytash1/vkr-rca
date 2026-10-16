# Повторение инженерной приёмки подключения

Эти окружения проверяют работу переносимого приложения с фактическими источниками. Они не являются обязательной инфраструктурой продукта и не оценивают точность RCA на новых размеченных отказах. Обычная установка в компании использует её собственные источники по [руководству интегратора](../../docs/product-architecture/GETTING_STARTED.md).

Команды выполняются из корня зафиксированного GitHub checkout. Нужны Docker Compose v2, доступ к Docker Engine и достаточно ресурсов для Java-сервисов (в пройденной установке Docker VM: 8 ГиБ и 2 CPU). Экспортёр читает Docker API только внутри приёмочного стенда; обычному диагностическому приложению Docker socket не нужен. Такой socket следует считать привилегированным даже при read-only bind mount: стенд допустим лишь на доверенной локальной машине.

## A — собственные три сервиса

```bash
docker compose -f deploy/acceptance/compose.yml up -d --build
docker compose -f deploy/acceptance/compose.yml ps
```

Окружение `rca-product-acceptance`: gateway 18680, Prometheus 19990, Jaeger 19686; порты опубликованы только на loopback. Нагрузчик выполняет HTTP-запросы и выдаёт фактические started/succeeded/failed/dropped. Дождитесь устойчивой работы и не менее 210 секунд наблюдений. Время ожидания не гарантирует здоровье: следующая команда проверяет реальный счётчик ошибок.

```bash
.venv/bin/python scripts/accept_live_profile.py \
  --profile deploy/acceptance/profiles/local-three.json \
  --output /tmp/rca-acceptance-A-unique --verify-workload
```

Каталог output должен отсутствовать. Прогон сохраняет фактические ответы, проверяет здоровый период, готовит baseline только если его каталог отсутствует, затем сверяет все семейства, SpanID, полный рейтинг и воспроизведение. Существующее baseline помечается reused и не переопределяется новым интервалом. Для независимого повторения подготовки используйте чистый clone либо новую версию профиля и новый каталог артефактов.

## B — внешний Spring Petclinic

Перед запуском нужна зафиксированная штатная конфигурация внешнего проекта. Не подменяйте её текущей плавающей веткой:

```bash
git clone https://github.com/spring-petclinic/spring-petclinic-microservices-config.git \
  external-data/product-acceptance/spring-petclinic-microservices-config
git -C external-data/product-acceptance/spring-petclinic-microservices-config \
  checkout --detach 323993ce2519c6d02df63e08bf4458d123d3b611
docker compose -f deploy/acceptance/compose.yml build metrics-exporter
docker compose -f deploy/acceptance/petclinic/compose.yml up -d
docker compose -f deploy/acceptance/petclinic/compose.yml ps
```

Прикладные образы выбраны из официального проекта и закреплены digest в Compose. Исходные checkout служили изучению; соответствие бинарной сборки исходному commit без provenance не заявляется. См. [выбор проекта](../../docs/product-acceptance/EXTERNAL_SELECTION.md). Скопированные исходники Petclinic и его конфигурация не входят в наш runtime-пакет; лицензия upstream сохраняется в его checkout.

Порты: gateway 18880, Prometheus 19991, Jaeger 19687. Нужно дождаться регистрации сервисов и устойчивых HTTP 200 на трёх путях `/api/gateway/owners/1`, `/api/vet/vets`, `/api/customer/owners`; стартовый прогрев не является здоровым периодом. Встроенная HSQLDB содержит учебные записи, не данные пациентов реальной клиники. GenAI и платные API не запускаются.

```bash
.venv/bin/python scripts/accept_live_profile.py \
  --profile deploy/acceptance/profiles/petclinic.json \
  --output /tmp/rca-acceptance-B-unique --verify-workload
PYTHONPATH=ml:cmd/thesis_demo .venv/bin/python cmd/thesis_demo/server.py \
  --root . --profiles-dir deploy/acceptance/profiles --port 18218
```

Откройте `http://127.0.0.1:18218/`, выберите систему и прошедший интервал, рассчитайте рейтинг, выберите кандидата и проверьте исходные наблюдения. Название выбранного сервиса не является эталонной причиной: без размеченного отказа этот прогон оценивает только инженерное подключение.

## Безопасные границы повторения

`accept_source_failures.py` намеренно останавливает только Prometheus/Jaeger выбранного приёмочного проекта и восстанавливает их в finally. Не запускайте его на рабочем источнике компании. Перезапуск in-memory Jaeger удаляет прежние спаны; это ожидаемая особенность стенда, а не пустая активность сервисов. Другие Compose-проекты, в том числе ReBAC, команды не меняют.

Выполненные команды и выводы хранятся в [итоговом протоколе](../../docs/product-acceptance/ACCEPTANCE_FINAL.md). Файлы профилей версионируются; модель и её схема при повторении не обучаются и не подбираются по полученным рейтингам.
