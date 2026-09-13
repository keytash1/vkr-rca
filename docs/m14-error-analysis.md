# M14 Error Analysis

No model changes follow this analysis. Error stages follow the preregistered truth rank; diagnostic flags are not causal truth.

```json
{
  "ROOT_BELOW_TOP10": 6,
  "ROOT_BELOW_TOP5": 5,
  "SUCCESS_AT_1": 25,
  "WITHIN_TOP3_ORDERING_ERROR": 10,
  "WITHIN_TOP5_ORDERING_ERROR": 4
}
```

| Incident | Root | Fault | Rank | Stage | Descriptive flags |
|---|---|---|---:|---|---|
| m14-002-e09ee7ed | ad | packet_loss | 10 | ROOT_BELOW_TOP5 | OOD_DOMAIN_SHIFT |
| m14-008-d8f3752e | cart | service_unavailable | 3 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-010-c0a1a38c | frontend | service_unavailable | 12 | ROOT_BELOW_TOP10 | OOD_DOMAIN_SHIFT, LOW_WORKLOAD_SIGNAL |
| m14-012-232bb485 | recommendation | packet_loss | 2 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-013-eaca6fcc | payment | packet_loss | 4 | WITHIN_TOP5_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-018-0ce346bc | payment | memory | 3 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-019-b1fc6ebc | frontend | packet_loss | 2 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-020-99071a00 | cart | service_unavailable | 3 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-024-c0f10eb2 | ad | memory | 2 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-025-f569f851 | payment | network_latency | 8 | ROOT_BELOW_TOP5 | OOD_DOMAIN_SHIFT |
| m14-027-311c8367 | payment | network_latency | 10 | ROOT_BELOW_TOP5 | OOD_DOMAIN_SHIFT |
| m14-031-91c6842a | frontend | network_latency | 2 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-034-af6091d9 | ad | network_latency | 11 | ROOT_BELOW_TOP10 | OOD_DOMAIN_SHIFT |
| m14-036-fa12c05d | frontend | service_unavailable | 12 | ROOT_BELOW_TOP10 | OOD_DOMAIN_SHIFT, LOW_WORKLOAD_SIGNAL |
| m14-037-c0ab5460 | payment | cpu | 5 | WITHIN_TOP5_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-039-53f4f28f | cart | memory | 4 | WITHIN_TOP5_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-040-b1a849dd | ad | network_latency | 11 | ROOT_BELOW_TOP10 | OOD_DOMAIN_SHIFT |
| m14-041-b64f7d25 | payment | cpu | 10 | ROOT_BELOW_TOP5 | OOD_DOMAIN_SHIFT |
| m14-042-6fb9b6a0 | payment | service_unavailable | 2 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-043-09e7d1e0 | payment | packet_loss | 4 | WITHIN_TOP5_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-044-38777133 | payment | service_unavailable | 2 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-046-e07704ce | ad | packet_loss | 12 | ROOT_BELOW_TOP10 | OOD_DOMAIN_SHIFT |
| m14-047-e4dd64c0 | cart | memory | 2 | WITHIN_TOP3_ORDERING_ERROR | OOD_DOMAIN_SHIFT |
| m14-048-0b99f314 | frontend | packet_loss | 11 | ROOT_BELOW_TOP10 | OOD_DOMAIN_SHIFT |
| m14-050-6419126b | ad | memory | 10 | ROOT_BELOW_TOP5 | OOD_DOMAIN_SHIFT |

`OOD_DOMAIN_SHIFT` marks the held-out domain context; it does not prove why a particular ranking failed. `LOW_WORKLOAD_SIGNAL` means most workload operations timed out or returned 5xx, not that the injection is invalid. Other possible mechanisms are not assigned without evidence.

## Repeated failure patterns

Both frontend service-unavailable incidents rank the root 12th; each retained only eight canonical spans while all 48 metric pairs were present. Both ad latency incidents rank the root 11th. Payment latency ranks are 8 and 10. These repeated cluster failures must not be hidden by the pooled improvement.

There are zero candidate-universe misses: 25 Top-1 successes, 10 ranks 2–3, four ranks 4–5, five ranks 6–10 and six ranks 11–12. Thus the observed residual is ranking/order failure, not omission of the known root from the candidate set. This classification does not identify its causal mechanism.

The two frontend outages receive the low-workload flag; no incident has a wholly missing metric or trace modality. Sparse or uneven service-level traces can still be inadequate evidence. No new features, disappearance thresholds, reliability model or challenger are developed from these errors.
