# M14 Final Locked Transfer Results

Verdict: **SUPPORTED_TRANSFER**. Data role: **USED_TEST**. Research status: **FINAL_RESEARCH_FREEZE**.

One sealed 50-incident test on OpenTelemetry Astronomy Shop; 25 root/fault clusters, two repetitions each. No post-test model changes.

## Pooled results

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0600 | 0.1600 | 0.2200 | 0.3400 | 0.7200 | 0.2263 | 1.0000 |
| frozen_m11 | 0.1600 | 0.4000 | 0.4800 | 0.5600 | 0.8800 | 0.3823 | 1.0000 |
| frozen_m13 | 0.5000 | 0.6400 | 0.7000 | 0.7800 | 0.8800 | 0.6300 | 1.0000 |
| metric_heuristic | 0.3000 | 0.4400 | 0.4600 | 0.6400 | 0.8200 | 0.4555 | 1.0000 |

## Absolute Wilson 95% intervals

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 |
|---|---|---|---|---|---|
| chance | [0.0206, 0.1622] | [0.0834, 0.2851] | [0.1275, 0.3524] | [0.2244, 0.4785] | [0.5833, 0.8253] |
| frozen_m11 | [0.0834, 0.2851] | [0.2761, 0.5382] | [0.3480, 0.6149] | [0.4231, 0.6884] | [0.7620, 0.9438] |
| frozen_m13 | [0.3664, 0.6336] | [0.5014, 0.7586] | [0.5625, 0.8090] | [0.6476, 0.8725] | [0.7620, 0.9438] |
| metric_heuristic | [0.1910, 0.4375] | [0.3116, 0.5769] | [0.3297, 0.5960] | [0.5014, 0.7586] | [0.6920, 0.9023] |

## Paired M13 differences

10,000 resamples per interval. Cluster CI is the preregistered significance gate; 25 root/fault clusters. Positive means M13 is better.

| Comparator | Metric | Delta | Incident 95% CI | Cluster 95% CI | Positive cluster CI |
|---|---|---:|---|---|---|
| chance | ac_at_1 | 0.4400 | [0.3000, 0.5800] | [0.2600, 0.6200] | True |
| chance | mrr | 0.4036 | [0.2778, 0.5237] | [0.2409, 0.5569] | True |
| frozen_m11 | ac_at_1 | 0.3400 | [0.2200, 0.4800] | [0.1800, 0.5200] | True |
| frozen_m11 | mrr | 0.2476 | [0.1307, 0.3645] | [0.0950, 0.4078] | True |
| metric_heuristic | ac_at_1 | 0.2000 | [0.0800, 0.3200] | [0.0400, 0.3600] | True |
| metric_heuristic | mrr | 0.1745 | [0.0854, 0.2704] | [0.0586, 0.3027] | True |

## Per fault

### cpu (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.1000 | 0.2000 | 0.4000 | 0.6000 | 1.0000 | 0.2989 | 1.0000 |
| frozen_m11 | 0.8000 | 0.9000 | 0.9000 | 0.9000 | 1.0000 | 0.8625 | 1.0000 |
| frozen_m13 | 0.8000 | 0.8000 | 0.8000 | 0.9000 | 1.0000 | 0.8300 | 1.0000 |
| metric_heuristic | 0.6000 | 0.8000 | 0.8000 | 0.9000 | 0.9000 | 0.7333 | 1.0000 |

### memory (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.1000 | 0.1000 | 0.2000 | 0.6000 | 0.1644 | 1.0000 |
| frozen_m11 | 0.0000 | 0.4000 | 0.4000 | 0.4000 | 0.8000 | 0.2765 | 1.0000 |
| frozen_m13 | 0.5000 | 0.7000 | 0.8000 | 0.9000 | 1.0000 | 0.6683 | 1.0000 |
| metric_heuristic | 0.4000 | 0.8000 | 0.8000 | 0.9000 | 1.0000 | 0.6393 | 1.0000 |

### network_latency (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.2000 | 0.4000 | 0.4000 | 0.4000 | 0.7000 | 0.3651 | 1.0000 |
| frozen_m11 | 0.0000 | 0.2000 | 0.4000 | 0.4000 | 0.8000 | 0.2418 | 1.0000 |
| frozen_m13 | 0.5000 | 0.6000 | 0.6000 | 0.6000 | 0.8000 | 0.5907 | 1.0000 |
| metric_heuristic | 0.2000 | 0.2000 | 0.2000 | 0.3000 | 0.8000 | 0.2964 | 1.0000 |

### packet_loss (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.1000 | 0.2000 | 0.4000 | 0.6000 | 0.1860 | 1.0000 |
| frozen_m11 | 0.0000 | 0.3000 | 0.4000 | 0.4000 | 0.8000 | 0.2598 | 1.0000 |
| frozen_m13 | 0.3000 | 0.5000 | 0.5000 | 0.7000 | 0.8000 | 0.4774 | 1.0000 |
| metric_heuristic | 0.2000 | 0.2000 | 0.3000 | 0.7000 | 0.8000 | 0.3558 | 1.0000 |

### service_unavailable (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.0000 | 0.0000 | 0.1000 | 0.7000 | 0.1173 | 1.0000 |
| frozen_m11 | 0.0000 | 0.2000 | 0.3000 | 0.7000 | 1.0000 | 0.2710 | 1.0000 |
| frozen_m13 | 0.4000 | 0.6000 | 0.8000 | 0.8000 | 0.8000 | 0.5833 | 1.0000 |
| metric_heuristic | 0.1000 | 0.2000 | 0.2000 | 0.4000 | 0.6000 | 0.2527 | 1.0000 |

### Macro fault

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0600 | 0.1600 | 0.2200 | 0.3400 | 0.7200 | 0.2263 | 1.0000 |
| frozen_m11 | 0.1600 | 0.4000 | 0.4800 | 0.5600 | 0.8800 | 0.3823 | 1.0000 |
| frozen_m13 | 0.5000 | 0.6400 | 0.7000 | 0.7800 | 0.8800 | 0.6300 | 1.0000 |
| metric_heuristic | 0.3000 | 0.4400 | 0.4600 | 0.6400 | 0.8200 | 0.4555 | 1.0000 |

### Worst fault, metric-wise minimum

Different columns may attain their minimum in different groups; this is not a synthetic incident group.

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.0000 | 0.0000 | 0.1000 | 0.6000 | 0.1173 | 1.0000 |
| frozen_m11 | 0.0000 | 0.2000 | 0.3000 | 0.4000 | 0.8000 | 0.2418 | 1.0000 |
| frozen_m13 | 0.3000 | 0.5000 | 0.5000 | 0.6000 | 0.8000 | 0.4774 | 1.0000 |
| metric_heuristic | 0.1000 | 0.2000 | 0.2000 | 0.3000 | 0.6000 | 0.2527 | 1.0000 |


## Per root

### ad (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.1000 | 0.1000 | 0.1000 | 0.2000 | 0.7000 | 0.2125 | 1.0000 |
| frozen_m11 | 0.2000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.6000 | 1.0000 |
| frozen_m13 | 0.4000 | 0.5000 | 0.5000 | 0.5000 | 0.7000 | 0.4965 | 1.0000 |
| metric_heuristic | 0.2000 | 0.3000 | 0.3000 | 0.3000 | 0.4000 | 0.3173 | 1.0000 |

### cart (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.1000 | 0.3000 | 0.3000 | 0.7000 | 0.1938 | 1.0000 |
| frozen_m11 | 0.2000 | 0.5000 | 0.8000 | 0.9000 | 1.0000 | 0.4917 | 1.0000 |
| frozen_m13 | 0.6000 | 0.7000 | 0.9000 | 1.0000 | 1.0000 | 0.7417 | 1.0000 |
| metric_heuristic | 0.2000 | 0.3000 | 0.3000 | 0.8000 | 1.0000 | 0.3868 | 1.0000 |

### frontend (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.0000 | 0.1000 | 0.2000 | 0.5000 | 0.1384 | 1.0000 |
| frozen_m11 | 0.2000 | 0.2000 | 0.2000 | 0.2000 | 1.0000 | 0.3310 | 1.0000 |
| frozen_m13 | 0.5000 | 0.7000 | 0.7000 | 0.7000 | 0.7000 | 0.6258 | 1.0000 |
| metric_heuristic | 0.1000 | 0.4000 | 0.4000 | 0.6000 | 1.0000 | 0.3429 | 1.0000 |

### payment (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.3000 | 0.3000 | 0.6000 | 0.8000 | 0.2478 | 1.0000 |
| frozen_m11 | 0.0000 | 0.1000 | 0.1000 | 0.3000 | 1.0000 | 0.1761 | 1.0000 |
| frozen_m13 | 0.1000 | 0.3000 | 0.4000 | 0.7000 | 1.0000 | 0.3358 | 1.0000 |
| metric_heuristic | 0.1000 | 0.2000 | 0.3000 | 0.5000 | 0.7000 | 0.2806 | 1.0000 |

### recommendation (n=10)

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.2000 | 0.3000 | 0.3000 | 0.4000 | 0.9000 | 0.3392 | 1.0000 |
| frozen_m11 | 0.2000 | 0.2000 | 0.3000 | 0.4000 | 0.4000 | 0.3129 | 1.0000 |
| frozen_m13 | 0.9000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9500 | 1.0000 |
| metric_heuristic | 0.9000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9500 | 1.0000 |

### Macro root

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0600 | 0.1600 | 0.2200 | 0.3400 | 0.7200 | 0.2263 | 1.0000 |
| frozen_m11 | 0.1600 | 0.4000 | 0.4800 | 0.5600 | 0.8800 | 0.3823 | 1.0000 |
| frozen_m13 | 0.5000 | 0.6400 | 0.7000 | 0.7800 | 0.8800 | 0.6300 | 1.0000 |
| metric_heuristic | 0.3000 | 0.4400 | 0.4600 | 0.6400 | 0.8200 | 0.4555 | 1.0000 |

### Worst root, metric-wise minimum

Different columns may attain their minimum in different groups; this is not a synthetic incident group.

| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0000 | 0.0000 | 0.1000 | 0.2000 | 0.5000 | 0.1384 | 1.0000 |
| frozen_m11 | 0.0000 | 0.1000 | 0.1000 | 0.2000 | 0.4000 | 0.1761 | 1.0000 |
| frozen_m13 | 0.1000 | 0.3000 | 0.4000 | 0.5000 | 0.7000 | 0.3358 | 1.0000 |
| metric_heuristic | 0.1000 | 0.2000 | 0.3000 | 0.3000 | 0.4000 | 0.2806 | 1.0000 |

## Locked gates

```json
{
  "ac_at_3_at_least_0_80": false,
  "ac_at_5_at_least_0_70": true,
  "ac_at_5_at_least_0_90": false,
  "beats_chance_cluster": true,
  "beats_frozen_m11_cluster": true,
  "beats_metric_heuristic_cluster": true,
  "catastrophic_fault_families": 0,
  "coverage_at_least_0_90": true,
  "no_majority_fault_catastrophe": true
}
```

## Collection and scope

Healthy warm-up: 1,800/1,800 HTTP 200; healthy baseline: 5,400/5,400 HTTP 200. Healthy telemetry: 43,248 metric samples / 48 service-family pairs / 123,218 native spans. All five mechanism canaries passed after a Docker process-inspection compatibility fix.

Accepted corpus operations: 9000; statuses: `{'200': 8366, '0': 633, '503': 1}`. These are fault-exposed operations, not healthy failures to exclude. Raw attempts retained: 51; rejected mechanical attempts: 1. Native spans: 190039; per-incident range 8–4110. Metric-pair range: 48–48 of 48.

The fixed observation window is 30 seconds; slow requests are drained after fault reset. Missing telemetry is not fabricated. Healthy-only target adaptation is permitted, but target fault labels never train a model.

Scoring latency is the combined four-method pipeline, not M13 alone: median 54.63 ms, p95 89.47 ms, maximum 112.52 ms; total 3.73 seconds. It is offline evidence, not a production latency SLA.

## Limitations

- One new system, five represented fault families and five injected roots; not arbitrary unseen-fault or production generalization.
- A single deterministic workload, 30-second windows, two repetitions per root/fault cluster, one host/run. Temporal carryover and co-load are not ruled out by cluster bootstrap.
- All candidates and PostgreSQL have a precollection 512 MiB ceiling; Checkout/ProductCatalog Go soft limit is 384 MiB. This differs from upstream defaults. Deployment/build exceptions and failed precollection smoke gates remain in `m14-engineering-log.md`.
- Docker ran with two CPUs and about 7.74 GiB RAM, alongside an unrelated project that was not stopped. Source commit, exact image IDs and environment are sealed in readiness evidence.
- Exact source and built image IDs are recorded, but upstream unlocked transitive dependencies mean a future source rebuild is not guaranteed byte-identical. Local experiment images and raw evidence must be retained; they are not published container artifacts.
- The 32 MiB allocation demonstrates an observable memory injection, not proof of OOM or user-visible memory exhaustion. CPU, netem and pause are controlled mechanisms, not every real incident of those families.
- CPU/memory acceptance requires the preregistered resource-signal increase as well as a running agent. This selects mechanically observable injections independently of rankings; it does not estimate performance on all attempted or weak-signal real-world faults.
- Native trace collection is anchored at frontend traces; not a claim of complete autonomous background telemetry. Canonical metrics are Docker resource signals, not full application RED/USE instrumentation.
- Rank is not causal proof or calibrated probability. Diagnostic error flags are descriptive hypotheses. No final-system ablation or retuning is authorized.
- Wilson intervals are descriptive binomial intervals; paired cluster intervals are primary for comparisons. Gates use AC@1 OR MRR as registered, without a new multiplicity correction.

Full grouped Wilson intervals and incident-level error records are in `ml/models/m14/evaluation.json`. Compact truth labels and all four sealed rankings are published in `evaluation-inputs.json` for independent metric reproduction (USED_TEST, never training). Original raw telemetry, process evidence and sealed files remain locally under `external-data/m14/runs/locked-v1/`, not embedded in Git.
