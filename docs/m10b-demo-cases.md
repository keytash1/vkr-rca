# M10B deterministic RCAEval showcase set

The showcase set was frozen before UI presentation. It is deliberately not an accuracy sample: it contains four correct Top-1 results and four misses, including a severe Train Ticket miss. The purpose is to demonstrate the unchanged M9B inference path honestly, not to estimate a new metric or create a new research claim.

| Blind UI title | Case ID | Suite | Family after reveal | Frozen model route | Actual root | Predicted Top-1 | Actual rank | Outcome |
|---|---|---|---|---|---|---|---:|---|
| Внешний инцидент A | `re2ob_currencyservice_cpu_1` | RE2-OB | CPU | train RE2-TT, test OB | currencyservice | currencyservice | 1 | success |
| Внешний инцидент B | `re2ob_checkoutservice_cpu_1` | RE2-OB | CPU | train RE2-TT, test OB | checkoutservice | emailservice | 2 | miss |
| Внешний инцидент C | `re2ob_checkoutservice_disk_2` | RE2-OB | disk | train RE2-TT, test OB | checkoutservice | checkoutservice | 1 | success |
| Внешний инцидент D | `re2ob_currencyservice_delay_1` | RE2-OB | delay | train RE2-TT, test OB | currencyservice | currencyservice | 1 | success |
| Внешний инцидент E | `re2ob_checkoutservice_socket_2` | RE2-OB | socket | train RE2-TT, test OB | checkoutservice | paymentservice | 3 | miss |
| Внешний инцидент F | `re3ob_currencyservice_f1_1` | RE3-OB | f1 | train RE2-TT, test OB | currencyservice | currencyservice | 1 | success |
| Внешний инцидент G | `re3ob_currencyservice_f1_2` | RE3-OB | f1 | train RE2-TT, test OB | currencyservice | frontend | 3 | miss |
| Внешний инцидент H | `re2tt_ts-order-service_loss_1` | RE2-TT | loss | train RE2-OB, test TT | ts-order-service | ts-preserve-service | 22 | miss |

Before reveal, the interface presents only a neutral title, system, dataset, incident timestamp, telemetry availability, candidate count, and topology size. It does not display the root service, fault family, internal case ID, actual rank, or correctness. Technical model metadata is available only after analysis in an expandable section. Root service, fault family, actual rank, and correctness are stored separately under the ignored `demo-data/` cache and are returned only by the reveal endpoint; the internal case ID is displayed alongside them only after reveal.

The selection manifest is `demo/cases.json`. RCAEval is pinned to source commit `405c8fd24071af41ceb4b3aabb451e5e3e15d6c6`, Hugging Face revision `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`, and cases-index SHA256 `c49a288920dbba2e8e724679a14636d5c7eb2b45426bba14007ef79a6c0ab1bb`.
