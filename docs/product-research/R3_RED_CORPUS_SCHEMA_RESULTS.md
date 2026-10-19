# R3-K — Eadro TT не решает задачу независимых HTTP-метрик

20.10.2026. **NOT_ELIGIBLE_FOR_INDEPENDENT_HTTP_RED_TRAINING.**
Проверены именно исходные CSV заголовки, а не только выбранные автором признаки.

Из [авторской публикации Zenodo](https://zenodo.org/records/7615394) скачан один
`TT Dataset.zip`: 48 923 113 bytes. Опубликованная MD5
`2d77861e4a025781e598d51866fd6f4e` совпала; SHA-256 архива:
`e199aefeb48f7fa1534c37d77415dba9c84bffcb59167373c35cb88f4f4e9f7c`.
Локально `artifacts/r3-red-corpus-schema-v1/TT-Dataset.zip`, receipt рядом.

Во всех243 настоящих telemetry CSV одна схема: timestamp, три CPU-канала,
memory_usage, memory_working_set, rx_bytes, tx_bytes. Прочитаны только26 244 bytes
заголовков. Независимых counters завершённых HTTP-запросов/5xx или duration
histogram в этих CSV нет. В данном архиве preprocessing не потерял такие поля:
его семь ресурсных входов соответствуют raw CSV schema. Это не утверждение
обо всех возможных данных авторов или непрочитанной SN-части.

Авторский [preprocessor](https://github.com/BEbillionaireUSD/Eadro/blob/main/codes/preprocess/single_process.py)
формирует latency из traces. В нашей задаче это не замена независимым HTTP-
метрикам при пропущенных трассировках. Кроме того, готовые авторские chunks
нормализуются и перемешиваются; нельзя автоматически считать их готовым
независимым групповым переносом для нашего метода.

Первый guard остановился до заголовков: ZIP также содержит243 macOS resource
forks с расширением .csv. Исходный runner сохранён, metadata forks исключены,
настоящих CSV243 — прежний лимит400 не менялся. Архив не скачивался повторно.
Labels/fault records/logs/spans/числовые строки не прочитаны, pickle не открыт,
архив не распакован. Новых fits/predictions/LLM calls нет. Продукт/веса/DOCX
не менялись. [Регистрация](../R3_RED_CORPUS_SCHEMA_PROTOCOL.md),
runner `scripts/r3_red_corpus_schema.py`.

## Решение для следующего ядра

Не тратить новый прогон на этот архив ради той же гипотезы. Текущий продукт
уже умеет собирать независимый HTTP-контекст через профиль; отсутствие готового
совместимого training corpus не устраняется выдуманными каналами или повтором
прежних seeds. Новый обучаемый вариант требует отдельного входного контракта
и данных с совместно наблюдаемыми resource/HTTP/traces, подтверждённым healthy
периодом и группами воздействий. Старые RE1/Go6/Petclinic12 остаются development,
старые50 случаев не превращаются в скрытый тест заново. До такого набора текущие
веса сохраняются; product HTTP evidence-only не выдаётся за ML-улучшение.
