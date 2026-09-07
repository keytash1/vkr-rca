# M12 Results — Frozen Unseen-System Shadow Validation

System: DeathStarBench Hotel Reservation at `6ecb09706140f8730b5385c08f1386c654c3c526`.
All 50 incidents are newly generated M12 locked data; model training count is zero.

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.1800 | 0.2800 | 0.3800 | 0.6800 | 1.0000 | 0.3798 | 1.0000 |
| Metric heuristic | 0.6400 | 0.6800 | 0.6800 | 0.8000 | 1.0000 | 0.7202 | 1.0000 |
| M10C | 0.5400 | 0.6800 | 0.7600 | 0.8800 | 1.0000 | 0.6814 | 1.0000 |
| M10D Top-3 | 0.5400 | 0.6600 | 0.7600 | 0.8800 | 1.0000 | 0.6781 | 1.0000 |
| M11 Top-5 | 0.5400 | 0.6600 | 0.7800 | 0.8800 | 1.0000 | 0.6797 | 1.0000 |

M11 absolute Wilson 95% intervals: AC@1 `[0.40398871399157477, 0.6703034780777566]`, AC@2 `[0.521538260502326, 0.7756305077749992]`,
AC@3 `[0.6475845041874634, 0.8724608402978559]`, AC@5 `[0.7619518261679701, 0.9438239984906773]`, AC@10 `[0.9286524008666414, 1.0]`.
All incident and `(root_service, fault_family)` cluster paired intervals are in
`ml/models/m12/evaluation.json`; cluster intervals are the claim gate.

## Per fault family

### `cpu`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.3000 | 0.4000 | 0.4000 | 0.7000 | 1.0000 | 0.4726 | 1.0000 |
| Metric heuristic | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| M10C | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| M10D Top-3 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| M11 Top-5 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

### `memory`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.1000 | 0.3000 | 0.3000 | 0.6000 | 1.0000 | 0.3301 | 1.0000 |
| Metric heuristic | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| M10C | 0.9000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9500 | 1.0000 |
| M10D Top-3 | 0.9000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9500 | 1.0000 |
| M11 Top-5 | 0.9000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9500 | 1.0000 |

### `network_latency`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.1000 | 0.2000 | 0.5000 | 0.9000 | 1.0000 | 0.3543 | 1.0000 |
| Metric heuristic | 0.6000 | 0.7000 | 0.7000 | 0.7000 | 1.0000 | 0.6958 | 1.0000 |
| M10C | 0.4000 | 0.6000 | 0.8000 | 0.9000 | 1.0000 | 0.6042 | 1.0000 |
| M10D Top-3 | 0.4000 | 0.5000 | 0.8000 | 0.9000 | 1.0000 | 0.5875 | 1.0000 |
| M11 Top-5 | 0.4000 | 0.5000 | 0.8000 | 0.9000 | 1.0000 | 0.5825 | 1.0000 |

### `packet_loss`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.2000 | 0.2000 | 0.3000 | 0.5000 | 1.0000 | 0.3460 | 1.0000 |
| Metric heuristic | 0.4000 | 0.5000 | 0.5000 | 0.7000 | 1.0000 | 0.5450 | 1.0000 |
| M10C | 0.4000 | 0.6000 | 0.6000 | 0.9000 | 1.0000 | 0.5793 | 1.0000 |
| M10D Top-3 | 0.4000 | 0.6000 | 0.6000 | 0.9000 | 1.0000 | 0.5793 | 1.0000 |
| M11 Top-5 | 0.4000 | 0.6000 | 0.6000 | 0.9000 | 1.0000 | 0.5793 | 1.0000 |

### `service_unavailable`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.2000 | 0.3000 | 0.4000 | 0.7000 | 1.0000 | 0.3962 | 1.0000 |
| Metric heuristic | 0.2000 | 0.2000 | 0.2000 | 0.6000 | 1.0000 | 0.3601 | 1.0000 |
| M10C | 0.0000 | 0.2000 | 0.4000 | 0.6000 | 1.0000 | 0.2736 | 1.0000 |
| M10D Top-3 | 0.0000 | 0.2000 | 0.4000 | 0.6000 | 1.0000 | 0.2736 | 1.0000 |
| M11 Top-5 | 0.0000 | 0.2000 | 0.5000 | 0.6000 | 1.0000 | 0.2869 | 1.0000 |

## Per root service

### `frontend`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.0000 | 0.2000 | 0.3000 | 0.6000 | 1.0000 | 0.2650 | 1.0000 |
| Metric heuristic | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| M10C | 0.4000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.7000 | 1.0000 |
| M10D Top-3 | 0.4000 | 0.9000 | 1.0000 | 1.0000 | 1.0000 | 0.6833 | 1.0000 |
| M11 Top-5 | 0.4000 | 0.9000 | 1.0000 | 1.0000 | 1.0000 | 0.6833 | 1.0000 |

### `geo`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.4000 | 0.5000 | 0.6000 | 0.8000 | 1.0000 | 0.5551 | 1.0000 |
| Metric heuristic | 0.4000 | 0.6000 | 0.6000 | 0.9000 | 1.0000 | 0.5917 | 1.0000 |
| M10C | 0.5000 | 0.6000 | 1.0000 | 1.0000 | 1.0000 | 0.6833 | 1.0000 |
| M10D Top-3 | 0.5000 | 0.6000 | 1.0000 | 1.0000 | 1.0000 | 0.6833 | 1.0000 |
| M11 Top-5 | 0.5000 | 0.6000 | 1.0000 | 1.0000 | 1.0000 | 0.6833 | 1.0000 |

### `rate`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.2000 | 0.3000 | 0.4000 | 0.7000 | 1.0000 | 0.3986 | 1.0000 |
| Metric heuristic | 0.5000 | 0.5000 | 0.5000 | 0.7000 | 1.0000 | 0.6000 | 1.0000 |
| M10C | 0.5000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | 0.6150 | 1.0000 |
| M10D Top-3 | 0.5000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | 0.6150 | 1.0000 |
| M11 Top-5 | 0.5000 | 0.5000 | 0.6000 | 1.0000 | 1.0000 | 0.6233 | 1.0000 |

### `recommendation`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.3000 | 0.3000 | 0.4000 | 0.8000 | 1.0000 | 0.4601 | 1.0000 |
| Metric heuristic | 0.6000 | 0.6000 | 0.6000 | 0.7000 | 1.0000 | 0.6593 | 1.0000 |
| M10C | 0.6000 | 0.6000 | 0.6000 | 0.7000 | 1.0000 | 0.6611 | 1.0000 |
| M10D Top-3 | 0.6000 | 0.6000 | 0.6000 | 0.7000 | 1.0000 | 0.6611 | 1.0000 |
| M11 Top-5 | 0.6000 | 0.6000 | 0.6000 | 0.7000 | 1.0000 | 0.6611 | 1.0000 |

### `search`

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.0000 | 0.1000 | 0.2000 | 0.5000 | 1.0000 | 0.2204 | 1.0000 |
| Metric heuristic | 0.7000 | 0.7000 | 0.7000 | 0.7000 | 1.0000 | 0.7500 | 1.0000 |
| M10C | 0.7000 | 0.7000 | 0.7000 | 0.7000 | 1.0000 | 0.7476 | 1.0000 |
| M10D Top-3 | 0.7000 | 0.7000 | 0.7000 | 0.7000 | 1.0000 | 0.7476 | 1.0000 |
| M11 Top-5 | 0.7000 | 0.7000 | 0.7000 | 0.7000 | 1.0000 | 0.7476 | 1.0000 |

## Macro averages

### Fault-family macro

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.1800 | 0.2800 | 0.3800 | 0.6800 | 1.0000 | 0.3798 | 1.0000 |
| Metric heuristic | 0.6400 | 0.6800 | 0.6800 | 0.8000 | 1.0000 | 0.7202 | 1.0000 |
| M10C | 0.5400 | 0.6800 | 0.7600 | 0.8800 | 1.0000 | 0.6814 | 1.0000 |
| M10D Top-3 | 0.5400 | 0.6600 | 0.7600 | 0.8800 | 1.0000 | 0.6781 | 1.0000 |
| M11 Top-5 | 0.5400 | 0.6600 | 0.7800 | 0.8800 | 1.0000 | 0.6797 | 1.0000 |

### Root-service macro

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chance | 0.1800 | 0.2800 | 0.3800 | 0.6800 | 1.0000 | 0.3798 | 1.0000 |
| Metric heuristic | 0.6400 | 0.6800 | 0.6800 | 0.8000 | 1.0000 | 0.7202 | 1.0000 |
| M10C | 0.5400 | 0.6800 | 0.7600 | 0.8800 | 1.0000 | 0.6814 | 1.0000 |
| M10D Top-3 | 0.5400 | 0.6600 | 0.7600 | 0.8800 | 1.0000 | 0.6781 | 1.0000 |
| M11 Top-5 | 0.5400 | 0.6600 | 0.7800 | 0.8800 | 1.0000 | 0.6797 | 1.0000 |

## Operational profile

- Service count: `8`.
- Healthy + locked metric samples: `5792` + `21920`.
- Adapter completeness / errors: `1.0000` / `0`.
- Telemetry completeness: `1.0000`.
- Full inference median / p95: `25.897` / `92.608` ms.
- Canonical window-to-output median / p95: `38.994` / `117.748` ms.
- M11 evidence reranker median / p95: `9.561` / `41.800` ms.
- Frozen model artifacts: `209169` bytes.
- Peak RCA process RAM: `181.875` MiB.
- Cached-image cold Compose startup through successful application and telemetry readiness: `12.70` s.
- Post-Compose application / telemetry probe time: `0.04736` / `0.04736` s.
  This operational measurement was collected after locked evaluation, was never
  available to RCA inference, and is recorded in `ml/models/m12/system-manifest.json`.

The full error list and all paired intervals are preserved in the machine-readable
evaluation artifact. Raw telemetry and sealed truth remain ignored under
`external-data/m12/`.

## Decisions

- M12_SYSTEM_DEPLOYMENT: PASS
- M12_TELEMETRY_PIPELINE: PARTIAL
- M12_LOCKED_INCIDENT_SET: PASS
- NEW_SYSTEM_TRANSFER: WEAK
- TOP5_TRANSFER_GAIN: NOT_SUPPORTED
- M12_TRACE_MODALITY: PARTIAL
- M12_RESEARCH_CHAMPION: KEEP_M11_WITH_TRANSFER_QUALIFICATION

Telemetry is PARTIAL because metrics and Jaeger collection are deployed, but
the frozen inference path does not introduce a new M12 trace feature adapter.
Scores are association rankings, not causal verification or probabilities.

## Protocol deviations

- Healthy warm-up reduced from 300 to 60 seconds.
- Healthy baseline reduced from 900 to 180 seconds due the 2 CPU/8 GiB local environment and 50 live runs.
- cAdvisor was replaced before accepted healthy data because its Docker API was incompatible; the frozen replacement exporter uses Docker API v1.44 and one-second Prometheus scraping.
- Jaeger covers eight services, but trace-to-feature adaptation remains unavailable; frozen missing-modality semantics were used.
- The first evaluation attempt stopped before metric computation because its denominator assertion called `set()` on index dictionaries. The original freeze and first sealed-prediction hash are retained; the corrected attempt was allowed only because the assertion-only fix reproduced byte-identical predictions.
