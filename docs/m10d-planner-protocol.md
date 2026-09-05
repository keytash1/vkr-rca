# M10D-C protocol: active RCA diagnostic planner

Status: preregistered before the locked 360-case evaluation. The M10C compact
stability ranker and its 32-column schema are frozen inputs. This branch does
not alter the M10A/M10C results, models, reliability layer, or verifier.

## Question and simulation boundary

The experiment asks whether a truth-free myopic value-of-information (VOI)
policy can choose which telemetry family to reveal next and outperform fixed,
non-oracle acquisition policies at the same cost. Existing complete telemetry
is the hidden environment. A policy receives only the current ranking summary,
modality masks, action availability, coverage, prediction-set size, OOD and
expert-disagreement placeholders, and spent cost. Root labels and unrevealed
feature values never enter deployable state or policy features.

The canonical actions are `GET_LATENCY_METRICS`, `GET_ERROR_METRICS`,
`GET_CPU_METRICS`, `GET_MEMORY_METRICS`, `GET_NETWORK_METRICS`,
`GET_DISK_METRICS`, `GET_WORKLOAD_METRICS`, `GET_TRACE_EVIDENCE`,
`GET_TOPOLOGY`, and `GET_DEPENDENCY_EVIDENCE`. An action is unavailable when
its source family/modality is absent. The base costs are one for a metric family
and topology and two for trace and dependency analysis. Uniform and
trace-expensive costs are fixed sensitivity analyses.

All selected M10C feature columns are assigned to an acquisition action.
Metric coverage becomes visible after the first metric acquisition; trace and
topology coverage become visible with their corresponding actions. Revealing
all available actions must reproduce the frozen full-evidence ranking exactly.

## Development protocol

Planner fitting and policy assessment use only RE1. Each outer fold holds out
one complete system (Online Boutique, Sock Shop, or Train Ticket); the other
two systems generate offline state/action/utility examples. The detector-only
Synthetic A/B/C corpus has no service candidate universe or per-family hidden
RCA evidence and is therefore schema-incompatible with this planner experiment.
It is reported as not applicable and is not converted into invented examples.

The preregistered deployable model is a small XGBoost squared-error regressor:
depth 2, 32 rounds, learning rate 0.08, minimum child weight 5, row and column
subsampling 0.9, L2 regularization 5. Five seeds are used: 20260906 through
20260910. There is no hyperparameter search and no RL.

For each reachable RE1 action subset, the offline target is:

`delta MRR + 0.20 * normalized prediction-set reduction - 0.02 * base cost`.

The 90% score-gap prediction-set threshold is fit only on the training systems.
At inference, the policy evaluates every affordable available action, chooses
the maximum predicted utility with a lexical tie break, and stops when the
prediction set is a singleton, the budget is exhausted, or no action remains.
OOD and verifier-dependent values do not
affect V1; they remain explicit zero-valued state fields so V1 is independently
deployable.

Budgets are 0, 1, 2, 3, 5, and full available-evidence cost. Metrics are AC@1,
AC@3, MRR, mean 90% set size, mean spent cost, cost to first correct Top-1 and
root-in-Top-3, solved fractions, and trapezoidal accuracy/MRR/set-size curves.

## Comparators and statistics

Comparators are deterministic RANDOM (opaque incident hash plus seed),
FIXED_ORDER, METRICS_FIRST, TRACE_FIRST, STRONGEST_CURRENT_SIGNAL, and atomic
ALL_EVIDENCE_IMMEDIATELY. The latter acquires everything only when the full
cost fits. `ORACLE_ACTION` uses truth to maximize realized one-step utility and
is stored in a separately named upper-bound section; it is never serialized as
a deployable policy.

At each non-full budget, the best non-oracle baseline is selected on aggregate
outer-held-out RE1 MRR. The planner comparison uses 10,000 paired incident
bootstrap resamples with seed 20260906. Promotion requires strictly positive
95% lower bounds for delta MRR at at least two non-full budgets and exact
full-evidence rank invariance. Otherwise the verdict is `REJECTED`.

Only after the configuration and final five RE1-trained models are hashed is
the already-used RE2/RE3 360-case suite opened for post-M10C descriptive
evaluation. It cannot change the method, costs, baselines, or verdict gate.
