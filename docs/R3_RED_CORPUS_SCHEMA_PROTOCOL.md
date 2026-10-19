# R3-K: пригодность Eadro для независимых HTTP-метрик

20.10.2026, после выпуска R3-J. Это проверка структуры данных, не эксперимент
точности и не переобучение. До чтения raw архива известны README, Zenodo listing
и авторский preprocessing: `Info.metric_names` содержит семь ресурсных метрик,
а latency в `deal_traces` выводится из traces. Сырые CSV ещё не прочитаны.

## Вопрос

Не отбрасывал ли preprocessing независимые HTTP counters/errors/histogram
duration, как ранее случалось с нашими сокращениями? Новый корпус нужен именно
для расширенного core и переноса, не ради количества скачанных datasets.

## Единственная проверка

- Авторская Eadro публикация: Zenodo7615394, `TT Dataset.zip`, 48 923 113 bytes,
  опубликованная MD5 `2d77861e4a025781e598d51866fd6f4e`. Лимит64 MiB compressed,
  суммарно180 s download. Уже существующий файл не перезаписывать.
- Прочитать только ZIP inventory и заголовки всех CSV в каталогах `metrics`:
  до20 000 entries, до400 CSV, по4096 bytes заголовка, до2 MiB headers суммарно.
  Не распаковывать архив, не выполнять авторский код/не загружать pickle.
- Не читать labels, records, logs, spans, значения метрик или fault time.
  Не обучать модель, не считать ranking, не открывать старый закрытый тест.
- Сохранить checksum, размеры и уникальные схемы/число CSV. Если raw содержит
  только resource families, не скачивать SN и не строить RED из traces под видом
  независимого источника. Вывод ограничить фактически проверенной TT-частью.
- Если независимые HTTP-поля есть, остановиться на схеме: нужен отдельный
  protocol с единицами/группами/разделением данных до любого нового fit.

Веса, работающий продукт и DOCX не меняются. Эта проверка не запускает новый
grid или массовую загрузку. Primary sources: [авторский репозиторий](https://github.com/BEbillionaireUSD/Eadro),
[Zenodo](https://zenodo.org/records/7615394),
[schema](https://github.com/BEbillionaireUSD/Eadro/blob/main/codes/preprocess/util.py),
[trace preprocessing](https://github.com/BEbillionaireUSD/Eadro/blob/main/codes/preprocess/single_process.py).
