# M11 Error Analysis

## RE1 system-OOF development

- Incidents: 375
- Candidate-universe coverage: 1.0000
- AC@1/2/3/5/10: 0.7813 / 0.9040 / 0.9307 / 0.9840 / 0.9920
- MRR: 0.8655
- Truth-rank histogram: `{"not_in_candidate_universe": 0, "rank_1": 293, "rank_2": 46, "rank_3": 10, "rank_4_5": 20, "rank_6_10": 3, "rank_gt_10": 3}`
- Oracle AC@1 by recoverable K: `{"1": 0.72, "10": 0.992, "2": 0.8906666666666667, "3": 0.9306666666666666, "5": 0.984}`
- Top-3 error stages: `{"ROOT_BELOW_K": {"count": 26, "fraction": 0.06933333333333333}, "ROOT_UNOBSERVABLE": {"count": 0, "fraction": 0.0}, "SUCCESS_AT_1": {"count": 293, "fraction": 0.7813333333333333}, "WITHIN_K_ORDERING_FAILURE": {"count": 56, "fraction": 0.14933333333333335}}`
- Final-error taxonomy: `{"errors": 82, "examples": {"BELOW_TOP3": ["re1ob_checkoutservice_loss_2", "re1ob_checkoutservice_loss_5", "re1ob_currencyservice_cpu_1", "re1ob_currencyservice_loss_1", "re1ob_productcatalogservice_cpu_3", "re1ob_productcatalogservice_loss_3", "re1ob_productcatalogservice_loss_4", "re1tt_ts-order-service_delay_3", "re1tt_ts-order-service_loss_1", "re1tt_ts-route-service_delay_3"], "IN_TOP3_RERANK_ERROR": ["re1ob_adservice_delay_4", "re1ob_cartservice_delay_5", "re1ob_cartservice_loss_3", "re1ob_cartservice_loss_4", "re1ob_cartservice_loss_5", "re1ob_checkoutservice_loss_1", "re1ob_checkoutservice_loss_3", "re1ob_checkoutservice_loss_4", "re1ob_currencyservice_cpu_4", "re1ob_currencyservice_delay_1"]}, "heuristic_limit": "Diagnostic overlap flags are descriptive thresholds, not causal labels.", "overlapping_diagnostics": {"AMBIGUOUS_METRIC_EVIDENCE": 31, "MISSING_DOMINANT_MODALITY": 56, "OOD_DOMAIN_SHIFT": 5, "OTHER": 14}, "primary_mutually_exclusive": {"BELOW_TOP3": 26, "CANDIDATE_UNIVERSE_MISS": 0, "IN_TOP3_RERANK_ERROR": 56, "OTHER": 0}}`

The oracle curve measures only whether the root is already present within the
initial K; it is not model performance. It separates candidate recovery from
within-head ordering.

## Historical RE2/RE3 regression (opened after freeze)

- Frozen M10D AC@1 / MRR: 0.8361 / 0.8977
- Selected M11 architecture: Top-5
- Incidents: 360
- Candidate-universe coverage: 1.0000
- AC@1/2/3/5/10: 0.8417 / 0.9389 / 0.9611 / 0.9750 / 0.9917
- MRR: 0.9039
- Truth-rank histogram: `{"not_in_candidate_universe": 0, "rank_1": 303, "rank_2": 35, "rank_3": 8, "rank_4_5": 5, "rank_6_10": 6, "rank_gt_10": 3}`
- Top-3 error stages: `{"ROOT_BELOW_K": {"count": 14, "fraction": 0.03888888888888889}, "ROOT_UNOBSERVABLE": {"count": 0, "fraction": 0.0}, "SUCCESS_AT_1": {"count": 303, "fraction": 0.8416666666666667}, "WITHIN_K_ORDERING_FAILURE": {"count": 43, "fraction": 0.11944444444444445}}`
- Final-error taxonomy: `{"errors": 57, "examples": {"BELOW_TOP3": ["re2ob_checkoutservice_delay_1", "re2ob_checkoutservice_delay_2", "re2tt_ts-auth-service_delay_2", "re2tt_ts-auth-service_loss_1", "re2tt_ts-auth-service_loss_2", "re2tt_ts-auth-service_loss_3", "re2tt_ts-order-service_delay_1", "re2tt_ts-order-service_loss_1", "re2tt_ts-travel-service_delay_1", "re2tt_ts-travel-service_loss_2"], "IN_TOP3_RERANK_ERROR": ["re2ob_checkoutservice_delay_3", "re2ob_currencyservice_loss_2", "re2ob_currencyservice_loss_3", "re2ob_currencyservice_socket_1", "re2ob_productcatalogservice_delay_1", "re2ob_productcatalogservice_loss_3", "re2ob_recommendationservice_loss_3", "re2ss_carts_delay_3", "re2ss_carts_loss_1", "re2ss_orders_delay_1"]}, "heuristic_limit": "Diagnostic overlap flags are descriptive thresholds, not causal labels.", "overlapping_diagnostics": {"AMBIGUOUS_METRIC_EVIDENCE": 34, "MISSING_DOMINANT_MODALITY": 13, "OOD_DOMAIN_SHIFT": 48, "OTHER": 3}, "primary_mutually_exclusive": {"BELOW_TOP3": 20, "CANDIDATE_UNIVERSE_MISS": 0, "IN_TOP3_RERANK_ERROR": 37, "OTHER": 0}}`

This second section is descriptive regression evidence only. RE2/RE3 did not
select K, features, seeds, hyperparameters or the architecture verdict.
