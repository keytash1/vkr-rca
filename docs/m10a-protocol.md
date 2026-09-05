# M10A protocol: research freeze and claim validation

M10A adds no model family, telemetry source, feature, threshold, or production behavior. It validates the frozen M9B research core at commit `b260dd6f22d5903a1313758d9dfad2b3402811ac`. All files under `ml/models/m9b-v1/` and all M5–M9B reports are immutable inputs. The analysis must hash them before and after execution and fail if any byte changes.

## Locked inputs and denominators

The source remains RCAEval commit `405c8fd24071af41ceb4b3aabb451e5e3e15d6c6`, Hugging Face revision `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`, and cases-index SHA256 `c49a288920dbba2e8e724679a14636d5c7eb2b45426bba14007ef79a6c0ab1bb`. M9B truth-free features must match their sealed SHA256 before labels are joined.

Triggered multi-source comparisons use the same 216 root-observable cases: RE2-OB 90, RE2-TT 90, RE3-OB 6, and RE3-TT 30. Metric conditional results use 336 root-observable cases. Metric full-denominator results use all 360 RE2/RE3 cases and assign rank zero to an unobservable root. No case is removed after outcomes are inspected.

## Paired comparisons

The unit is one incident. Paired bootstrap uses 10,000 resamples and seed `20260904` for AC@1 and MRR.

The fusion claim compares `m9b-multisource-lambdamart-v1` with a metrics-only model retrained under the identical frozen RE2 cross-system folds, hyperparameters, rounds, and candidate rows. It is reported overall and for RE2-OB, RE2-TT, RE3-OB, and RE3-TT. RE3-OB (`n=6`) is descriptive only because its effective sample is too small for a stable suite-level inference.

The metric-vs-trace claim compares frozen `m9b-metric-lambdamart-v1` with unchanged `soft_hybrid_v1` on the same 216 cases. The learned-vs-heuristic claim compares it with `metric_max_shift` on the same 336 observable metric cases.

BARO is directly compared only if both methods rank the same service-level target labels and cover the exact same 360 incident IDs. M9B-unobservable roots remain rank-zero failures. Candidate-universe differences are method differences, not grounds for removing incidents.

## Robustness to randomness

No search space or selected configuration changes. Five deterministic learner seeds (`20260904`, `20260917`, `20261001`, `20261015`, `20261029`) retrain each frozen RE1 system-holdout and each frozen RE2 cross-system fold using its original training/test membership, selected hyperparameters, and rounds. This tests XGBoost sampling randomness without creating a new tuned model. For AC@1 and MRR report mean, population standard deviation, min, max, and a deterministic 10,000-resample bootstrap CI of the mean across seeds.

## Feature-group stability

XGBoost `total_gain` is normalized within each frozen M9B model and aggregated into CPU, memory, disk, socket, workload, error, latency, trace, topology, and cross-family summary groups. A group is `stable_important` when it is used by every compared model, has at least 5% mean gain share, and spans less than 25 percentage points. A used group is `domain_dependent` when it is absent from at least one model or spans at least 25 points; the remainder is `low_or_unused`. Importance describes predictive use, not causality. Metric models and multi-source models are summarized separately because trace/topology features are structurally unavailable to metric-only models.

## Claim decisions

A paired improvement is called statistically supported only when its 95% bootstrap lower bound is above zero. A transfer claim must remain coverage-qualified and report the held-out systems. Descriptive end-to-end and historical claims must not be rewritten as causal claims. M9A remains rejected. The final architecture is frozen after M10A unless the analysis finds an implementation or mathematical error.
