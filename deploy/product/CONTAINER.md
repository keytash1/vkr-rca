# Контейнерная установка продукта

Образ содержит API, браузерный интерфейс и вычислительные зависимости. Он не запускает наблюдаемую систему, Prometheus, Jaeger или нагрузчик и не требует Docker socket. Нужны Docker Engine, Compose v2 и доступ контейнера к источникам организации. Команды выполняются из корня зафиксированного GitHub checkout.

## Образ и профиль

```bash
docker build -f deploy/product/Dockerfile -t vkr-rca/diagnostic-product:local .
```

Python 3.12 и базовый образ закреплены; Linux использует CPU-only дистрибутив XGBoost той же версии 3.2.0, без CUDA/NCCL. Модель и схема не меняются. CUDA/GPU для inference не нужны.

Создайте отдельный каталог, например `/absolute/path/rca-profiles`. Скопируйте `deploy/profiles/examples/new-system.template.json` в `/absolute/path/rca-profiles/company.json` и заполните по [руководству интегратора](../../docs/product-architecture/GETTING_STARTED.md). Путь артефактов внутри профиля — `deploy/profiles/artifacts/company-v1`; весь каталог монтируется в `/opt/rca/deploy/profiles`.

URL источника относится **к сети контейнера**: `127.0.0.1` означает сам контейнер, не хост. Используйте доступные DNS/IP организации. Для источников в другой Docker-сети явно подключите приложение к этой доверенной сети. Имя сети зависит от инфраструктуры, не зашито в продукт. Проверенный пример стенда — `deploy/acceptance/petclinic/container-profile.template.json`.

## Предварительная проверка и здоровое состояние

Подставьте существующую сеть, абсолютный каталог и фактический здоровый интервал. В Unix UID:GID соответствует владельцу каталога для записи baseline; на Docker Desktop доступ к bind mount зависит от ОС.

```bash
docker run --rm --user "$(id -u):$(id -g)" --network <source-network> \
  --read-only --tmpfs /tmp:rw,nosuid,size=64m \
  --mount type=bind,src=/absolute/path/rca-profiles,dst=/opt/rca/deploy/profiles \
  vkr-rca/diagnostic-product:local python cmd/thesis_demo/profile_check.py \
  --root /opt/rca --profile deploy/profiles/company.json --baseline \
  --start <healthy-start-ISO8601> --end <healthy-end-ISO8601>
```

После вердикта `ready` выполните ту же команду, заменив `profile_check.py` на `profile_setup.py` и убрав `--baseline`. Создаётся новый каталог артефактов, действующий не перезаписывается. Токены при необходимости передаются через `--env NAME`; значения не записываются в профиль, историю команд или Git.

## Рабочий запуск

```bash
RCA_PROFILES_DIR=/absolute/path/rca-profiles RCA_PORT=18100 \
  docker compose -f deploy/product/compose.yml up -d
```

Для источников в другой Docker-сети:

```bash
docker network connect <source-network> rca-diagnostic-product-diagnostic-1
```

После пересоздания контейнера подключение повторяют либо включают в локальный Compose override с `external`-сетью. Compose публикует **только** `127.0.0.1:18100`; внутри контейнера приложение слушает `0.0.0.0:18100`. Откройте `http://127.0.0.1:18100/`, выберите систему, прошедший интервал и рассчитайте рейтинг.

В рабочем режиме профили и baseline доступны только на чтение, UID 10001, capabilities удалены, корневая ФС read-only, память ограничена. Контейнер не добавляет TLS, SSO и права пользователей: сетевой доступ организации требует отдельно настроенного защищённого reverse proxy. `/api/health` подтверждает загрузку приложения, не доступность источников; источники проверяются при анализе и предварительной проверкой. Изменение профиля требует перезапуска. Удаление контейнера не удаляет каталог профилей на хосте.

## Выполненная проверка

Linux ARM64/Python 3.12.15: контейнер без сети и без корпуса внутри образа воспроизвёл 50 отдельно смонтированных входов с точным совпадением рангов и баллов. Отдельный запуск построил новое здоровое состояние Petclinic из реальных API и выполнил HTTP-запрос. Полный ответ совпал с нативным расчётом того же входа, включая наблюдения. Протокол — `docs/product-acceptance/container-petclinic/`. Это проверка установки, не новый эксперимент точности на отказах.
