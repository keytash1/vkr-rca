# M10D-C results: active RCA diagnostic planner

## Verdict

`ACTIVE_PLANNER: REJECTED`

The preregistered gate required a strictly positive paired-bootstrap lower
bound for MRR against the best non-oracle baseline at at least two non-full
budgets. No budget passed. The failure is decisive even though the simulator,
cost accounting, truth isolation, and full-evidence invariant all passed.
External results below are locked post-M10C observations and did not alter this
verdict.

## Frozen inputs and isolation

- Base commit: `b18c70c4deddb86c637a5fad4c9f68a2ff465423`.
- Frozen ranker: M10C compact stability, 32 columns.
- Development: 375 RE1 incidents, outer system holdout.
- Synthetic A/B/C: not applicable because the detector corpus has no
  service-level candidate universe or per-family hidden evidence.
- External: 360 RE2/RE3 incidents, opened only after the five final models and
  configuration were hashed.
- External data were not used for action selection, hyperparameters, costs,
  thresholds, or the acceptance gate.

The hidden environment owns complete feature rows and labels. `VisibleState`
contains only the current Top-3 scores/services, margins, concentration,
candidate count, revealed/available masks, coverage, set size, spent cost, and
zero-valued standalone placeholders for OOD, expert disagreement, and optional
verifier support. The learned policy schema contains no service, system,
dataset, fault, case semantics, root, or label.

Forced reveal of all available actions reproduced every frozen external rank:
maximum score delta `0.0`; AC@1 `0.7889`, AC@3 `0.9417`, MRR `0.8690`. The
planner's `full` budget row below still applies its preregistered singleton-set
stop rule, so it is not the forced-full invariant endpoint.

## Cross-system development

| Budget | AC@1 | AC@3 | MRR | Mean set | Set coverage | Mean cost |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.1333 | 0.3333 | 0.3012 | 21.152 | 1.000 | 0.000 |
| 1 | 0.5893 | 0.7920 | 0.7062 | 1.581 | 0.645 | 1.000 |
| 2 | 0.6427 | 0.8267 | 0.7445 | 1.077 | 0.648 | 1.072 |
| 3 | 0.6427 | 0.8267 | 0.7445 | 1.075 | 0.648 | 1.080 |
| 5 | 0.6427 | 0.8267 | 0.7445 | 1.075 | 0.648 | 1.091 |
| full policy | 0.6427 | 0.8267 | 0.7445 | 1.075 | 0.648 | 1.091 |

At budget 3 the system-held-out results were:

| System | AC@1 | AC@3 | MRR | Mean cost |
|---|---:|---:|---:|---:|
| Online Boutique | 0.696 | 0.864 | 0.7966 | 1.232 |
| Sock Shop | 0.832 | 1.000 | 0.9107 | 1.008 |
| Train Ticket | 0.400 | 0.616 | 0.5264 | 1.000 |

The gap on Train Ticket is the clearest domain-shift failure. The policy mostly
selected latency (250 actions), then CPU (152), and almost never workload (3).
It learned an over-aggressive one-action stopping pattern instead of a robust
cross-system diagnostic sequence.

### Baselines and promotion statistics

At budget 3, fixed/metrics-first/trace-first/strongest-current all reached MRR
`0.7865`; random reached `0.7623`; the planner reached `0.7445`; the isolated
oracle upper bound reached `0.9378`.

| Budget | Best non-oracle baseline | Delta MRR | 95% CI |
|---:|---|---:|---:|
| 1 | TRACE_FIRST | -0.0390 | [-0.0711, -0.0080] |
| 2 | TRACE_FIRST | +0.0020 | [-0.0341, +0.0376] |
| 3 | TRACE_FIRST | -0.0420 | [-0.0743, -0.0107] |
| 5 | ALL_EVIDENCE_IMMEDIATELY | -0.1813 | [-0.2141, -0.1506] |

All intervals use 10,000 paired incident resamples and seed `20260906`. The
number of passing non-full budgets is zero; two were required.

Area under the development cost curves was `0.3830` for AC@1 and `0.5225` for
MRR, versus `0.4093` and `0.5590` for the fixed-order family. The isolated
oracle reached `0.5563` and `0.6554`, showing that useful action information
exists but V1 did not learn it robustly.

The additional efficiency result also failed: frozen full-evidence RE1 MRR was
`0.9259`, so the 95% target was `0.8796`; the planner reached only `0.7445` at
mean cost `1.08` versus full cost `5.0`.

Five seeds produced identical development budget-3 MRR (`0.7445`) and AC@1
(`0.6427`). This is deterministic stability of the same inadequate policy, not
evidence of quality.

## Locked external 360

| Budget | AC@1 | AC@3 | MRR | Mean set | Set coverage | Mean cost |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.1056 | 0.2417 | 0.2599 | 20.783 | 1.000 | 0.000 |
| 1 | 0.6000 | 0.8583 | 0.7406 | 1.869 | 0.661 | 1.000 |
| 2 | 0.6444 | 0.8750 | 0.7693 | 1.028 | 0.650 | 1.144 |
| 3 | 0.6444 | 0.8750 | 0.7693 | 1.028 | 0.650 | 1.167 |
| 5 | 0.6444 | 0.8750 | 0.7693 | 1.028 | 0.650 | 1.211 |
| full policy | 0.6417 | 0.8750 | 0.7673 | 1.014 | 0.647 | 1.339 |

Budget-3 MRR by suite was RE2-OB `0.9133`, RE2-SS `0.8972`, RE2-TT `0.6122`,
RE3-OB `0.8742`, RE3-SS `0.7198`, and RE3-TT `0.3690`. Aggregated by system,
MRR was `0.9035` for Online Boutique, `0.8529` for Sock Shop, and `0.5514` for
Train Ticket. These results reinforce, but do not cause, the rejection.

The five external seed models had budget-3 MRR mean `0.7703`, standard
deviation `0.0020`, and range `[0.7693, 0.7743]`; AC@1 mean was `0.6456`,
standard deviation `0.0022`, and range `[0.6444, 0.6500]`. Uniform and
trace-expensive sensitivity both produced MRR `0.7693` and mean cost `1.167`
at budget 3 because the selected path was overwhelmingly latency-first and did
not reach trace acquisition.

## Prediction-set diagnosis

The training-calibrated active score-gap set shrank rapidly: under external
budget 2, 100% of incidents reached size at most 3, 99.7% size at most 2, and
97.8% singleton, at mean first costs `1.094`, `1.106`, and `1.125`. But its
empirical coverage was only `0.650`. Therefore set shrinkage is not a success;
it is the main confidence error. The frozen M10C rank-normalized conformal
output remains untouched and must not be replaced by this active score-gap
challenger.

At external budget 3, the mutually exclusive diagnostic taxonomy contains 124
confidence errors and 4 residual frozen-ranking errors. The remaining required
categories—domain shift, metric ambiguity, missing modality, candidate
ambiguity, planner bad action, and verifier contradiction miss—are zero under
this priority taxonomy; verifier contradiction is not applicable because V1
has no verifier dependency. The per-system table still exposes the broader
Train Ticket domain shift that the mutually exclusive local taxonomy does not.

## Performance and artifacts

The bounded run used 30,000 RE1 state/action examples, 37 truth-free policy
features, 562 cached reveal masks, and completed in 17.9 seconds after
vectorized ranking simulation. Mean budget-3 action selection overhead was
`0.48 ms/incident`. Five serialized depth-2 models occupy 124,930 bytes total.
The pure tree evaluator was checked against native XGBoost (maximum difference
approximately `2.1e-08`) and changes only inference overhead, not the policy.

Artifacts are isolated under `ml/models/m10d-planner/`: action schema, five
seed models, pre-external freeze manifest, and evaluation. No M10A/M10C file was
modified. Two-step lookahead was not attempted because V1 failed its gate.
