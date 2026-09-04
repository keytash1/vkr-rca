# M8B case studies

Six deterministic examples (lexicographically first matching case) were selected after evaluation.

## re2ob_checkoutservice_delay_1

Truth `checkoutservice`; fault `delay`; detector/status `ready`; observed anomalies `['checkoutservice']`.

Topology has 9 edges; coverage `{'client_spans': 143939, 'error_evidence_coverage': 0.9041104183061929, 'exclusive_trace_coverage': 1, 'input_spans': 339324, 'internal_spans': 28702, 'kind_inferred': True, 'parent_match_rate': 0.9998681645682861, 'server_spans': 166683, 'window_spans': 339324}`.

M6 ranks: max_severity=1; topology_consistency=1; local_evidence=1; hybrid_v1=1. Frozen M7 rank=1.

The root was available to the ranker; the rank reflects external feature transfer.

## re2ob_checkoutservice_cpu_1

Truth `checkoutservice`; fault `cpu`; detector/status `detection_miss`; observed anomalies `[]`.

Topology has 9 edges; coverage `{'client_spans': 138969, 'error_evidence_coverage': 0.90435420135696, 'exclusive_trace_coverage': 1, 'input_spans': 327527, 'internal_spans': 27623, 'kind_inferred': True, 'parent_match_rate': 0.9999772349579985, 'server_spans': 160935, 'window_spans': 327527}`.

M6 ranks: max_severity=0; topology_consistency=0; local_evidence=0; hybrid_v1=0. Frozen M7 rank=1.

Localization was gated before ranking by detector state or root readiness/observability.

## re2tt_ts-auth-service_cpu_1

Truth `ts-auth-service`; fault `cpu`; detector/status `ready`; observed anomalies `['ts-auth-service']`.

Topology has 55 edges; coverage `{'client_spans': 138306, 'error_evidence_coverage': 0, 'exclusive_trace_coverage': 1, 'input_spans': 957209, 'internal_spans': 675030, 'kind_inferred': True, 'parent_match_rate': 0.9995775722382997, 'server_spans': 143873, 'window_spans': 957209}`.

M6 ranks: max_severity=1; topology_consistency=1; local_evidence=1; hybrid_v1=1. Frozen M7 rank=1.

The root was available to the ranker; the rank reflects external feature transfer.

## re2tt_ts-auth-service_cpu_2

Truth `ts-auth-service`; fault `cpu`; detector/status `ready`; observed anomalies `['ts-order-service']`.

Topology has 55 edges; coverage `{'client_spans': 133609, 'error_evidence_coverage': 0, 'exclusive_trace_coverage': 1, 'input_spans': 691595, 'internal_spans': 419005, 'kind_inferred': True, 'parent_match_rate': 1, 'server_spans': 138981, 'window_spans': 691595}`.

M6 ranks: max_severity=0; topology_consistency=0; local_evidence=0; hybrid_v1=0. Frozen M7 rank=4.

The root was available to the ranker; the rank reflects external feature transfer.

## re3ob_adservice_f3_1

Truth `adservice`; fault `f3`; detector/status `root_not_observable`; observed anomalies `[]`.

Topology has 9 edges; coverage `{'client_spans': 58743, 'error_evidence_coverage': 0.9052070971663434, 'exclusive_trace_coverage': 1, 'input_spans': 138041, 'internal_spans': 11765, 'kind_inferred': True, 'parent_match_rate': 1, 'server_spans': 67533, 'window_spans': 138041}`.

M6 ranks: max_severity=0; topology_consistency=0; local_evidence=0; hybrid_v1=0. Frozen M7 rank=0.

Localization was gated before ranking by detector state or root readiness/observability.

## re3tt_ts-auth-service_f1_1

Truth `ts-auth-service`; fault `f1`; detector/status `detection_miss`; observed anomalies `[]`.

Topology has 41 edges; coverage `{'client_spans': 14783, 'error_evidence_coverage': 0, 'exclusive_trace_coverage': 1, 'input_spans': 60721, 'internal_spans': 29741, 'kind_inferred': True, 'parent_match_rate': 1, 'server_spans': 16197, 'window_spans': 60721}`.

M6 ranks: max_severity=0; topology_consistency=0; local_evidence=0; hybrid_v1=0. Frozen M7 rank=3.

Localization was gated before ranking by detector state or root readiness/observability.
