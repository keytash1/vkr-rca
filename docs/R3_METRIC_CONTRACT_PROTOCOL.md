# C1 — единый семантический контракт метрик

20.10.2026. Регистрация до нового преобразования captures. Роль: ENGINEERING
SUPPORT GATE / USED_DEVELOPMENT, не новая оценка точности. Fits=0, predictions=0,
provider calls=0, новых загрузок/развёртываний нет. Runtime/веса/V59 не менять.

## Цель

Реализовать новый исследовательский raw→features, общий для обучения и
применения, с отдельными healthy/incident. Не переименовывать cache56.
Контракт ограничен четырьмя семействами: consumed CPU cores, memory working
set bytes, HTTP5xx fraction completed business requests, histogram-estimated
HTTPp95 seconds. HTTP lookback30с и service-level aggregation объявлены явно.
Иные статистики/популяции/неподтверждённые единицы несовместимы, не нулевой сигнал.

## Преобразование

Стандартные единицы приводятся ДО расчёта: millicores→cores, KiB/MiB→bytes,
percent→ratio, ms/us→seconds. Единица не определяет смысл: p90 нельзя назватьp95,
ошибки/сек нельзя назвать долей5xx. Источник/статистика/lookback/агрегация
участвуют в semantic signature; имена сервисов/систем и разметка — нет.

Для каждой семьи: available, missing_fraction, unavailable_fraction,
no_activity_fraction, signed_median_shift, p90_absolute_shift, persistence.
Итого28столбцов, без межсервисных percentiles и rank hints. Нулевые placeholders
допустимы только с явными masks. Healthy должен иметь>=20полных наблюдений и
>=80%поддержки каждого канала; иначе baseline не строится. История healthy
может быть отдельной/старше600с, но должна предшествовать incident без перекрытия.

Scale=max(IQR здорового ряда,5%от|медианы|,канонический физический floor).
Floors заранее:CPU0,01core, memory1MiB, error0,01ratio, latency0,001s.
Это инженерные параметры нового представления, не подобранные пороги точности.
Значения shift ограничены±1e6 для конечной числовой матрицы, saturations учтены.
Persistence — доля ДОСТУПНЫХ измерений с |residual|>=3; missingness отдельно.

## Единственный ограниченный проход

1. Контрактные проверки: преобразования единиц, flat/zero baseline, отдельный
   healthy, изменённые имена, missing/idle/outage, дубликаты, несовместимые
   статистики, отсутствие разметки в матрице. Проверить неблагоприятные входы.
2. Сохранённые raw Go6/Petclinic12 (18открытых development-случаев): только
   преобразование, конечность/состав/полнота28столбцов, одинаковая сигнатура.
   Не загружать oracle/предыдущие rankings, не считать Accuracy, не fit.
3. RE1: три lexicographically-first файла, по одному OB/SS/TT, только schema
   metadata/названия колонок. Проверить наличие деклараций единиц/статистики,
   не угадывать их по масштабу значений или fault name. Не перечитывать375
   инцидентов ради ещё одного отрицательного gate.
4. Зафиксировать хеши исходников/входов/выходов, schema и квитанцию.
   Сырые captures локальны. Сравнить защищённые веса/ядро/V59 до/после.

## Условие завершения

Преобразователь реализован, реальные Go/Petclinic проходят один контракт,
unit/state/isolation проверки успешны. Если RE1 semantics не подтверждены,
вердикт C1=LIVE_CONTRACT_READY / TRAINING_SOURCE_NOT_SUPPORTED, C2=NO_FIT.
Реализацию не объявлять обученной моделью, а18случаев — независимым test.
Продуктовый репозиторий не получает исследовательский модуль/зависимости.

Следующая развилка при NO_FIT — подтвердить исходные queries/metadata
источника обучения либо отдельно согласовать небольшой источник данных
с тем же контрактом. Старые50AS для подбора исключены.

## Проверенные первоисточники

- https://prometheus.io/docs/practices/histograms/ — квантиль задаётся явно,
  агрегировать histogram buckets следует до оценки квантиля; среднее квантилей
  не восстанавливает квантиль общей популяции.
- https://github.com/phamquiluan/RCAEval — benchmark/состав источников; само
  наличие колонок metrics не устанавливает физические единицы/знаменатель.
- Локальные deploy/acceptance/red-queries.json и source-registration.json
  Petclinic фиксируют реальные business scope/30s/p95 и соответствие denominator.
