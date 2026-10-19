# Дополнительные HTTP-наблюдения

Необязательный блок профиля добавляет частоту завершённых бизнес-запросов,
долю ответов 5xx и временной ряд оценок p95 длительности серверных запросов.
Это первичные факты для проверки гипотез, не новые входы модели, не вероятность
причины и не автоматический резервный ранжировщик. Старые профили работают без
дополнительных запросов. Подготовка здорового состояния повторно не требуется.

Интегратор добавляет `http_observations` в корень JSON-профиля. URL, Bearer token
из переменной окружения, метка сервиса и алиасы берутся из существующего
`metrics`. Другой источник или произвольный URL помощнику не предоставляется.

Пример для инструментирования учебных Go-сервисов:

```json
{
  "http_observations": {
    "version": "service-http-observations-v1",
    "lookback_seconds": 30,
    "source_presence_query": "min by(service) (up{job=\"business-http-red\"})",
    "queries": {
      "request_rate": {
        "query": "sum by(service) (rate(rca_http_server_requests_total[30s]))",
        "unit": "requests_per_second",
        "statistic": "per_second_completed_request_rate"
      },
      "error_ratio": {
        "query": "sum by(service) (rate(rca_http_server_requests_total{status_class=\"5xx\"}[30s])) / sum by(service) (rate(rca_http_server_requests_total[30s]))",
        "unit": "ratio",
        "statistic": "5xx_response_fraction_of_completed_requests"
      },
      "latency_p95": {
        "query": "histogram_quantile(0.95, sum by(service,le) (rate(rca_http_server_request_duration_seconds_bucket[30s])))",
        "unit": "seconds",
        "statistic": "histogram_estimated_p95_of_completed_server_requests"
      }
    }
  }
}
```

Это фрагмент, не самостоятельный профиль. Инструментирование должно исключать
scrape/health/debug запросы и инициализировать нулевые error counters; отсутствие
ряда ошибок не является доказанным нулём. Каждый запрос возвращает один ряд на
канонический сервис. Для реплик сначала вычисляется rate отдельных counters,
затем сумма. Для p95 сначала суммируются histogram buckets, а не готовые квантили.
`min by(service)(up{...})` консервативно требует доступности всех выбранных
экземпляров. Метка `service` в примере должна совпадать с `metrics.service_label`.

Для Spring Boot/Micrometer нужны опубликованные histogram buckets. На стенде
Petclinic используются следующие замены запросов при тех же unit/statistic:

```promql
# request_rate
sum by(service) (rate(http_server_requests_seconds_count{job="business-http-red",uri!~"/actuator.*"}[30s]))

# error_ratio: нулевое дополнение допустимо только при известном контракте
# Micrometer, создающем отдельный ряд для каждого наблюдавшегося status
(sum by(service) (rate(http_server_requests_seconds_count{job="business-http-red",uri!~"/actuator.*",status=~"5.."}[30s])) or on(service) (0 * sum by(service) (rate(http_server_requests_seconds_count{job="business-http-red",uri!~"/actuator.*"}[30s])))) / sum by(service) (rate(http_server_requests_seconds_count{job="business-http-red",uri!~"/actuator.*"}[30s]))

# latency_p95
histogram_quantile(0.95, sum by(service,le) (rate(http_server_requests_seconds_bucket{job="business-http-red",uri!~"/actuator.*"}[30s])))
```

`UNKNOWN` URI не отбрасывается: на gateway это могут быть бизнес-запросы.
Перечень исключений и семантику завершённых запросов интегратор проверяет на
своём приложении. PromQL проверяет источник; приложение проверяет формат,
агрегацию и диапазоны значений, но не может доказать смысл произвольного запроса.

## Поведение и ограничения

После изменения профиля перезапустите приложение. `profile_check` и onboarding
`inspect` показывают готовность HTTP отдельно; отсутствие optional данных не
аннулирует основной рейтинг. Инженер выбирает прежние систему и интервал.
В карточке сервиса появляется одна закрытая группа «HTTP-наблюдения».

- `OBSERVED`: определённые отсчёты на всём запрошенном шаге.
- `NO_ACTIVITY`: источник доступен, rate равен нулю. p95 и доля ошибок без
  завершённых запросов не определены, а не равны нулю.
- `PARTIAL` / `INCOMPLETE`: часть каналов или отсчётов отсутствует.
- `UNAVAILABLE`: источник не подтверждён или запрос завершился ошибкой.
  Сохранившиеся старые rate значения не показываются как актуальная норма.

Каждая точка использует предшествующие `lookback_seconds`; первые точки могут
включать данные до выбранного интервала. Это задаваемое интегратором свойство
запроса, его нужно менять вместе с PromQL. Показанная медиана ряда оценок p95
не является p95 всего интервала. Существующие baseline/баллы с HTTP не сравниваются.

Четыре запроса ограничены общим worker deadline около 5 секунд плюс ограниченная
остановка процесса, 4 MiB ответов, 64 сервисами и 128 точками на ряд. Внешние
redirect и повторы запрещены. Подробности ошибки источника в UI не выводятся.
Неполный optional ответ не кэшируется как полный; изменение блока меняет ключ
кэша. Снимок хранит исходные факты и не перечитывает источник при открытии истории.

API сохраняет прежний `AnalysisResult` с optional `source_status.http_observations`.
Каталог с HTTP имеет `catalog_version=evidence-v4-service-http`, новые факты
остаются `kind=metric`, имеют unit/statistic/lookback и `model_input=false`.
Помощник при разрешённом вызове получает только числовую разрешённую проекцию,
не исходные labels, URL, PromQL, текст исключений или дополнительные полномочия.

Контракты источников: [Spring Boot metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html),
[Micrometer histograms](https://docs.micrometer.io/micrometer/reference/concepts/histogram-quantiles.html).
