# R3-B2 — обучение устойчивости к отсутствию трасс

19.10.2026. Зарегистрировано после диагностического результата на 20 известных
development-случаях и до fit нового challenger. Это отдельный опыт, не изменение
отрицательного temporal-протокола и его критериев.

Основание: полное удаление спанов изменило первого кандидата в 14/20 известных
случаев; missing_trace_modality/trace_collected_mask численно различают статусы,
но frozen деревья дали одинаковые scores для empty и unavailable в 20/20.
Это мотивирует обучение missing-modality, не доказывает улучшение заранее.

Данные: те же 120 M13 USED_DEVELOPMENT, та же отдельная healthy калибровка и
pretrained RE1 context. Новых внешних данных нет. Каждый train-инцидент получает
две views: исходную и с traces=[], traces_collected=False. Validation views
никогда не добавляются в train. Повторы/исходная и masked views одной группы
всегда находятся в одном fold. Root/fault не участвуют в feature extractor.

Признаки — ровно прежние 63, без временного блока. Параметры и split/seed
совпадают с R3_ML_PROTOCOL. Контроль — уже сохранённые шесть refit_control
моделей предыдущего опыта; они не дообучаются. Для challenger шесть ranking
fits (3 folds x 2 seeds), по 24 rounds. До 5 минут, артефакты <=20 MiB.
Общий бюджет двух ranking-опытов теперь 18 fits, не прежние 12, это явно
зарегистрированное добавление. Перебора и выбора лучшего seed нет.

Primary: MRR на masked validation. Дополнительные обязательные критерии:
delta masked MRR >=.05 и нижняя граница 95% cluster CI >0; delta полного MRR
>=-.01; полные AC@1/3/5 не хуже более чем .02; masked AC@1 ни одного fault
не хуже более чем .10; полный denominator/candidate coverage сохранён.
Masked и original не суммируются как независимые инциденты. Для интервалов
те же 60 групп, 2000 resamples и seed 20261019.

Сохранить исходные/маскированные predictions, per-seed и срезы. Отрицательный
результат — REJECTED_FOR_PROMOTION. Положительный — NEEDS_FRESH_TEST, не готовое
улучшение: OOF всё ещё известный development и искусственное полное удаление
трасс не представляет все реальные сбои/режимы sampling. Не менять продукт,
исторические веса, baseline/seals или M14; не исправлять исходные результаты.

Методологическое основание: [scikit-learn leakage](https://scikit-learn.org/stable/common_pitfalls.html).
Аугментация train не оправдывает передачу masked validation в fit.
