# M11 Public Dataset Compatibility Audit

This audit was completed before M11 candidate-recovery scores were generated.
Selection uses only data-contract compatibility, independence and licensing—not
model performance.

## Required contract

A compatible corpus must provide incident boundaries, a candidate service
universe, service-level root truth independent of filenames/aliases, usable
telemetry, stable public provenance, and a truth-free adapter boundary. Two roles
are needed: development and a separately locked test, preferably from genuinely
different systems or domains.

## Audited sources

| Dataset | License | Systems / overlap | Incidents | Fault / roots | Metrics / healthy baseline | Traces / topology | Time / label and mapping quality | Adapter complexity |
|---|---|---|---|---|---|---|---|---|
| AIOps Challenge 2020 | Custom non-commercial research/classroom terms | One production microservice environment; no documented OB/SS/TT overlap | Fault records, not a published clean service-incident count | CPU, memory, database and network families; location may be metric/instance rather than single service | Business and infrastructure metrics; healthy periods exist in the time series | Parent-linked traces; topology reconstructable | Timestamps present; fault CSV is authoritative but service aggregation needs validation | High |
| Murphy / DeathStarBench | MIT | Hotel Reservation; no RCAEval system overlap | Multiple experimental runs; no canonical single-root incident count | Compute, memory and disk interference; runs may be multi-fault; root entity is a container instance | Prometheus container metrics; non-fault intervals available | Jaeger traces; observed call topology reconstructable | Injection times/entities are explicit; pod-to-service mapping must come from deployment metadata | Medium-high |
| Cloud-OpsBench | MIT | 2: Online Boutique and Train Ticket; both overlap RCAEval | 754 (550 OB, 204 TT) | 57 Kubernetes/application/infrastructure fault types; case answer granularity varies | Metrics in some cases, plus alerts/Kubernetes state/logs; no uniform healthy baseline contract | No uniform trace contract in the standard case layout; topology partly reconstructable from Kubernetes/code | Per-case snapshots and metadata; component labels are agentic-task answers rather than a sealed RCAEval-style service truth | High and not a new domain |
| GAIA MicroSS | Repository licensing requires reconciliation before redistribution | One MicroSS scenario; no documented RCAEval overlap | Continuous corpus, not canonical incident cases | Injection records; single-vs-multi-root incident segmentation not pre-packaged | More than 6,500 metric series and continuous healthy/fault periods | Detailed parent-linked traces; observed topology reconstructable | Timestamps and injection logs exist; time windows and service truth require a validated segmentation contract | High |
| AIOpsLab | MIT repository framework | Configurable deployed systems; not a fixed corpus | No frozen incident count | Configurable injected faults | Exportable telemetry and controllable healthy runs | Framework can collect traces/topology | Reproducibility depends on Kubernetes deployment and workload; labels arise from generated experiments | Very high / data generation |

### AIOps Challenge 2020

Official source: <https://github.com/NetManAIOps/AIOps-Challenge-2020-Data>

The available Stage One archive contains business/infrastructure/trace telemetry
and fault records. Fault locations can be instance or metric-level, Stage Two is
not available, and the repository imposes a non-commercial research/classroom
license. A defensible service-level incident adapter therefore needs downloaded
raw-data validation and an explicit location-to-service contract.

Decision: `CANDIDATE_SOURCE_NOT_ADAPTED`; no M11 role assigned.

### Murphy / DeathStarBench hotel reservation

Official source: <https://github.com/netarch/Murphy-traces>

The MIT-licensed corpus contains Prometheus container metrics, Jaeger traces and
injection records for DeathStarBench hotel reservation. Runs may contain multiple
faults and injection entities are container instances. Converting these records
to a single-root service-level benchmark would require a pre-registered incident
segmentation and pod-to-service aggregation validated from telemetry metadata,
not names or truth.

Decision: `CANDIDATE_SOURCE_NOT_ADAPTED`; no M11 role assigned.

### Cloud-OpsBench

Official source: <https://github.com/LLM4Ops/Cloud-OpsBench>

The MIT-licensed benchmark has 754 operational cases over Online Boutique and
Train Ticket, with alerts, Kubernetes state, logs, metrics and code snapshots.
Those systems overlap the existing RCAEval systems, the benchmark is primarily an
agentic troubleshooting task, and metrics are absent in some cases. It is not an
independent new-system transfer test and does not expose the same telemetry/trace
contract as M10D.

Decision: `INCOMPATIBLE_AS_NEW_DOMAIN`; no M11 role assigned.

### GAIA MicroSS

Official source: <https://github.com/CloudWise-OpenSource/GAIA-DataSet>

GAIA provides continuous metrics, logs, traces and anomaly-injection records for
a different microservice scenario. It is promising, but not packaged as clean
single-root incidents; robust time-window segmentation and service-truth mapping
must be validated on the raw corpus. The README and repository license metadata
also need reconciliation before redistribution.

Decision: `CANDIDATE_SOURCE_NOT_ADAPTED`; no M11 role assigned.

### AIOpsLab

Official source: <https://github.com/microsoft/AIOpsLab>

AIOpsLab is a Kubernetes experimentation framework that deploys systems, injects
faults and exports telemetry. It is not a frozen, immediately auditable incident
corpus and would introduce environment-dependent data generation.

Decision: `FRAMEWORK_NOT_LOCKED_DATASET`; no M11 role assigned.

## Frozen selection verdict

`NEW_DEVELOPMENT = BLOCKED` and `LOCKED_NEW_TEST = BLOCKED`.

No audited source currently satisfies the complete service-level contract without
substantial raw-data acquisition and adapter validation. Fabricating aliases,
inferring truth from paths, or silently reusing Online Boutique/Train Ticket as a
new domain would invalidate the generalization claim. M11 therefore proceeds only
with RE1 development diagnostics and post-freeze read-only historical regression.
