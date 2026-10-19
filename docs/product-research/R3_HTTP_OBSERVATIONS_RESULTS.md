# R3-J — HTTP-факты в продукте

20.10.2026. **Продукт принят и опубликован:**
[PR #5](https://github.com/keytash1/rca-workbench/pull/5), main `a6845cf`.
CI contracts/image зелёный. Research mirror публикуется отдельно.
Это не новый ранжировщик и не обход отрицательного решения по резерву R3-I.
Продукт сохраняет прежний core и даёт инженеру дополнительные наблюдения.

## Что работает

Optional профильный блок `http_observations` задаёт RPS завершённых запросов,
долю 5xx и histogram-estimated p95 в секундах, source-presence и lookback.
Сбор ограничен четырьмя запросами и общим worker deadline; исходные labels,
секреты и тексты ошибок не попадают в evidence/числовую проекцию помощника.
Новый источник не нужен: тот же настроенный Prometheus и алиасы сервисов.

Факты сохраняются в snapshot, API, одной закрытой HTTP-группе выбранного сервиса
и разрешённых существующих read-only инструментах помощника. Без блока профиль
не делает дополнительных запросов. Core feature schema, baseline contract,
веса и алгоритм ранжирования не меняются. Неполнота optional источника не
ломает рейтинг и не сохраняется в кратком кэше как полный свежий ответ.

## Что проверено по смыслу

| Условие настоящего Go/Prometheus стенда | Наблюдение | Вывод |
|---|---|---|
| Идут запросы | OBSERVED у всех трёх сервисов | Есть определённые HTTP-измерения |
| Workload остановлен; очищен 30 s lookback | NO_ACTIVITY 3/3, p95/error ratio undefined | Нет трафика, а не доказан ноль ошибок/задержки |
| Payment остановлен; остальной стенд работает | Payment UNAVAILABLE, median RPS отсутствует | Сохранившиеся rate не маскируют отказ источника |
| Один и тот же живой интервал с блоком/без | Одинаковые input SHA, feature schema SHA и полный candidates | Дополнение не изменяет inference |
| Записанные healthy Go и Micrometer matrices | Полный контракт пройден для 3 и 4 сервисов | Проверена совместимость двух видов инструментирования |

Использован уже сохранённый historical baseline Go с честным `needs_review`:
это wiring-проверка, не новый опыт Accuracy или доказательство его применимости.
Корректность scope/unit/агрегации PromQL подтверждает интегратор; приложение
не способно само доказать смысл произвольного запроса по его строке.

Первый harness остановился после успешного active capture: продуктовый runtime
получил research root и попытался импортировать исключённый m14 replay.
Исходный runner/capture сохранены в `artifacts/r3-http-observations-v1`.
v2 работает на чистом source export, повторно использует active без новой
генерации и завершает API/idle/outage. Payment/workload восстановлены в finally.
Сводная [квитанция](r3-http-observations-summary.json),
[регистрация](../R3_HTTP_OBSERVATIONS_PROTOCOL.md), runner
`scripts/r3_http_observations_accept.py`. Сырые локальные captures не публикуются.

163 самодостаточных Python-теста прошли одним полным запуском; отдельно Node
проверяет default-collapsed группу, проценты/миллисекунды, idle/outage и масштаб
почти постоянного ряда p95. OpenAPI валиден. В подлинном браузере пройден путь
система + интервал → рейтинг → HTTP-факты → p95 график/ссылка источника.
Снимок локально: `artifacts/r3-http-observations-v2/http-card.jpg`.
Почти постоянный histogram p95 не растягивается до ложных крупных колебаний.

## Чего не заявляем

Новых ranking fits и provider-вызовов нет. Не установлены прирост точности
ранжировщика, эффект LLM или сокращение MTTR. Медиана временных оценок p95 не
является p95 всего интервала. Первые query points включают предшествующий
lookback; это явно записано в snapshot/UI/LLM-проекции. Числовой балл модели
не превращён в вероятность. Рабочие веса и DOCX V58 не изменены.

Чистый source export: 138 файлов; профильный bundle с workspace: 70 файлов,
проверка manifest/file hashes `ok`, import runtime из нового source и суммы
всех frozen assets совпали. ZIP SHA-256:
`bdf9c93190d021fb42d3cb3035fca747b6be1881200ff27ffd275f74d188fa9c`.
Квитанция локально `artifacts/r3-http-observations-delivery-v1/receipt.json`.
