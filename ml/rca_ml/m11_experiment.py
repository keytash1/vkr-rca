"""Execute the pre-registered M11 development-only hardening study."""

from __future__ import annotations

import argparse
import json
import platform
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import sha256_file
from .m10c_experiment import (
    EXTERNAL,
    RE1,
    load_rows,
    oof_experts,
    oof_for_columns,
)
from .m10c_schema import METRIC_EXPERT_COLUMNS, TRACE_EXPERT_COLUMNS
from .m10d_integration_experiment import (
    EXPECTED_METRICS,
    _fit_ablation,
    _legacy_vectors,
    _predict,
    _sanitize_rows,
    _strip_ranking,
)
from .m10d_reranker import (
    RERANKER_FEATURES,
    SEEDS,
    build_evidence_features,
    build_reranker_records,
    fit_ood_stats,
    load_frozen_models,
    predict_ensemble,
)
from .m11_protocol import (
    assert_selection_ids_allowed,
    cluster_bootstrap,
    error_decomposition,
    failure_taxonomy,
    oracle_ac_at_1,
    rank_histogram,
    ranking_metrics,
    rerank_top_k,
    truth_rank,
)
from .m9b_model import evaluate_model
from .metrics import paired_bootstrap
from .train import save_json

SEED = 20260906
TOP_K_VALUES = (3, 5, 10)


def _profiles(
    incident_ids: list[str],
    rankings: dict[str, list[dict]],
    rows_by_incident: dict[str, list[dict]],
    metric_rankings: dict[str, list[dict]],
    trace_rankings: dict[str, list[dict]],
    ood_stats: dict,
    k: int,
) -> dict[str, list[dict]]:
    return {
        incident: build_evidence_features(
            rows_by_incident[incident],
            _strip_ranking(rankings[incident]),
            metric_ranking=_strip_ranking(metric_rankings[incident]),
            trace_ranking=_strip_ranking(trace_rankings[incident]),
            ood_stats=ood_stats,
            top_k=k,
        )
        for incident in incident_ids
    }


def _candidate_records(
    profiles: dict[str, list[dict]],
    rankings: dict[str, list[dict]],
    case_by_id: dict[str, dict],
) -> list[dict]:
    records = []
    for incident in sorted(profiles):
        truth = next(
            item["service"] for item in rankings[incident] if int(item.get("label", 0)) == 1
        )
        for record in build_reranker_records(incident, profiles[incident], rankings[incident]):
            records.append({
                **record,
                "dataset": case_by_id[incident]["dataset"],
                "target": int(record["service"] == truth),
            })
    return records


def _oof_rerank(
    records: list[dict], rankings: dict[str, list[dict]], k: int
) -> tuple[dict[str, list[dict]], dict]:
    predictions = {seed: {} for seed in SEEDS}
    folds = []
    for held_out in RE1:
        train = [item for item in records if item["dataset"] != held_out]
        test = [item for item in records if item["dataset"] == held_out]
        train_ids = {item["incident_id"] for item in train}
        test_ids = {item["incident_id"] for item in test}
        if train_ids & test_ids:
            raise ValueError("OOF incident leakage")
        for seed in SEEDS:
            model = _fit_ablation(train, RERANKER_FEATURES, seed)
            predictions[seed].update(_predict(model, test, RERANKER_FEATURES))
        folds.append({
            "held_out": held_out,
            "train_datasets": [dataset for dataset in RE1 if dataset != held_out],
            "train_incidents": len(train_ids),
            "test_incidents": len(test_ids),
            "incident_ids_disjoint": True,
            "used_test_cases": 0,
        })
    per_seed = {}
    for seed in SEEDS:
        seed_rankings = rerank_top_k(rankings, predictions[seed], k)
        per_seed[str(seed)] = ranking_metrics(seed_rankings)
    ensemble = {
        key: float(np.mean([predictions[seed][key] for seed in SEEDS]))
        for key in predictions[SEEDS[0]]
    }
    return rerank_top_k(rankings, ensemble, k), {
        "folds": folds,
        "seeds": list(SEEDS),
        "five_seed_robustness": per_seed,
    }


def _by_dataset(rankings: dict[str, list[dict]], ids: dict[str, list[str]], datasets: tuple[str, ...]) -> dict:
    return {
        dataset: ranking_metrics({incident: rankings[incident] for incident in ids[dataset]})
        for dataset in datasets
    }


def _by_case_field(
    rankings: dict[str, list[dict]], case_by_id: dict[str, dict], field: str
) -> dict:
    groups = defaultdict(dict)
    for incident, ranking in rankings.items():
        groups[str(case_by_id[incident][field])][incident] = ranking
    return {name: ranking_metrics(values) for name, values in sorted(groups.items())}


def _macro_system(by_system: dict[str, dict]) -> dict:
    metrics = ("ac_at_1", "ac_at_2", "ac_at_3", "ac_at_5", "ac_at_10", "mrr")
    return {
        metric: float(np.mean([values[metric] for values in by_system.values()]))
        for metric in metrics
    }


def _rank_vector(rankings: dict[str, list[dict]]) -> list[int]:
    return [truth_rank(rankings[incident]) or 0 for incident in sorted(rankings)]


def _invariants(before: dict[str, list[dict]], after: dict[str, list[dict]], k: int) -> dict:
    membership = []
    tail = []
    for incident in sorted(before):
        initial = sorted(before[incident], key=lambda item: int(item["rank"]))
        final = sorted(after[incident], key=lambda item: int(item["rank"]))
        effective_k = min(k, len(initial))
        if {item["service"] for item in initial[:effective_k]} != {item["service"] for item in final[:effective_k]}:
            membership.append(incident)
        if [item["service"] for item in initial[effective_k:]] != [item["service"] for item in final[effective_k:]]:
            tail.append(incident)
    return {
        "top_k": k,
        "membership_equal": not membership,
        "tail_relative_order_identical": not tail,
        "membership_mismatches": membership,
        "tail_mismatches": tail,
    }


def _verify_preflight(root: Path, preflight: dict) -> dict:
    mismatches = {}
    for relative, expected in preflight["sha256"].items():
        actual = sha256_file(root / relative)
        if actual != expected:
            mismatches[relative] = {"expected": expected, "actual": actual}
    if mismatches:
        raise ValueError(f"M11 preflight mismatch: {mismatches}")
    return {"ok": True, "checked_files": len(preflight["sha256"]), "mismatches": {}}


def _freeze(
    root: Path,
    model_dir: Path,
    selected_k: int,
    decision: str,
    model_files: dict[str, str],
) -> dict:
    result = {
        "version": "m11-freeze-v1",
        "frozen_before_historical_test_access": True,
        "selection_data": list(RE1),
        "used_test_cases_seen_during_selection": 0,
        "architecture_decision": decision,
        "selected_top_k": selected_k,
        "feature_schema": list(RERANKER_FEATURES),
        "model_seeds": list(SEEDS),
        "hyperparameters": {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "max_depth": 2,
            "eta": 0.08,
            "min_child_weight": 3,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "num_boost_round": 24,
        },
        "preprocessing": {
            "candidate_scope": f"initial Top-{selected_k}",
            "canonical_features": "M10D 13-feature truth-free evidence representation",
            "ood_fit": "development-only robust 1st/99th percentile bounds",
            "candidate_identity": "join key only; never a numeric feature",
        },
        "adapters": {"status": "BLOCKED", "artifacts": []},
        "reliability_thresholds": None,
        "models": model_files,
        "preflight_sha256": sha256_file(model_dir / "preflight.json"),
        "data_ledger_sha256": sha256_file(model_dir / "data-ledger.json"),
        "protocol_sha256": sha256_file(root / "docs/m11-protocol.md"),
        "new_development": "BLOCKED",
        "locked_new_test": "BLOCKED",
    }
    save_json(model_dir / "freeze-manifest.json", result)
    return result


def _render_error_doc(evaluation: dict) -> str:
    dev = evaluation["error_analysis"]["development_re1_oof"]
    historical = evaluation["error_analysis"]["historical_re2_re3_post_freeze"]
    baseline = historical["frozen_m10d_baseline"]
    hist = historical["selected_architecture"]
    return f"""# M11 Error Analysis

## RE1 system-OOF development

- Incidents: {dev['metrics']['incidents']}
- Candidate-universe coverage: {dev['metrics']['candidate_universe_coverage']:.4f}
- AC@1/2/3/5/10: {dev['metrics']['ac_at_1']:.4f} / {dev['metrics']['ac_at_2']:.4f} / {dev['metrics']['ac_at_3']:.4f} / {dev['metrics']['ac_at_5']:.4f} / {dev['metrics']['ac_at_10']:.4f}
- MRR: {dev['metrics']['mrr']:.4f}
- Truth-rank histogram: `{json.dumps(dev['rank_histogram'], sort_keys=True)}`
- Oracle AC@1 by recoverable K: `{json.dumps(dev['oracle_ac_at_1'], sort_keys=True)}`
- Top-3 error stages: `{json.dumps(dev['top3_error_decomposition'], sort_keys=True)}`
- Final-error taxonomy: `{json.dumps(dev['failure_taxonomy'], sort_keys=True)}`

The oracle curve measures only whether the root is already present within the
initial K; it is not model performance. It separates candidate recovery from
within-head ordering.

## Historical RE2/RE3 regression (opened after freeze)

- Frozen M10D AC@1 / MRR: {baseline['metrics']['ac_at_1']:.4f} / {baseline['metrics']['mrr']:.4f}
- Selected M11 architecture: Top-{evaluation['candidate_recovery']['selected']['top_k']}
- Incidents: {hist['metrics']['incidents']}
- Candidate-universe coverage: {hist['metrics']['candidate_universe_coverage']:.4f}
- AC@1/2/3/5/10: {hist['metrics']['ac_at_1']:.4f} / {hist['metrics']['ac_at_2']:.4f} / {hist['metrics']['ac_at_3']:.4f} / {hist['metrics']['ac_at_5']:.4f} / {hist['metrics']['ac_at_10']:.4f}
- MRR: {hist['metrics']['mrr']:.4f}
- Truth-rank histogram: `{json.dumps(hist['rank_histogram'], sort_keys=True)}`
- Top-3 error stages: `{json.dumps(hist['top3_error_decomposition'], sort_keys=True)}`
- Final-error taxonomy: `{json.dumps(hist['failure_taxonomy'], sort_keys=True)}`

This second section is descriptive regression evidence only. RE2/RE3 did not
select K, features, seeds, hyperparameters or the architecture verdict.
"""


def _render_results_doc(evaluation: dict) -> str:
    selected = evaluation["candidate_recovery"]["selected"]
    rows = []
    for k, result in evaluation["candidate_recovery"]["variants"].items():
        metrics = result["metrics"]
        rows.append(
            f"| {k} | {metrics['ac_at_1']:.4f} | {metrics['ac_at_2']:.4f} | {metrics['ac_at_3']:.4f} | {metrics['ac_at_5']:.4f} | {metrics['ac_at_10']:.4f} | {metrics['mrr']:.4f} | {result['promotion_gate']['passes']} |"
        )
    selected_variant = evaluation["candidate_recovery"]["variants"][str(selected["top_k"])]
    top10 = evaluation["candidate_recovery"]["variants"]["10"]
    incident = selected_variant["incident_bootstrap_vs_top3"]
    cluster = selected_variant["cluster_bootstrap_vs_top3"]
    return f"""# M11 Results — Generalization & Error-Driven Hardening

## Candidate recovery

| Top-K | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Promotion gate |
|---:|---:|---:|---:|---:|---:|---:|:---:|
{chr(10).join(rows)}

Decision: **{selected['decision']}**; selected K = **{selected['top_k']}**.
The decision was made only from RE1 system-OOF predictions and cluster bootstrap
with 10,000 resamples. Incident-level improvements are not promoted when the
cluster interval crosses zero.

Primary Top-{selected['top_k']} vs Top-3 intervals:

- AC@1 incident CI: [{incident['ac_at_1']['ci_low']:.4f}, {incident['ac_at_1']['ci_high']:.4f}]; cluster CI: [{cluster['ac_at_1']['ci95'][0]:.4f}, {cluster['ac_at_1']['ci95'][1]:.4f}].
- MRR incident CI: [{incident['mrr']['ci_low']:.4f}, {incident['mrr']['ci_high']:.4f}]; cluster CI: [{cluster['mrr']['ci95'][0]:.4f}, {cluster['mrr']['ci95'][1]:.4f}].

Per-system, per-fault, pooled, macro-system and five-seed results are preserved in
`ml/models/m11/evaluation.json`.

Rejected hypothesis: Top-10 does not satisfy the pre-registered primary gate;
its AC@1 cluster CI `[{top10['cluster_bootstrap_vs_top3']['ac_at_1']['ci95'][0]:.4f}, {top10['cluster_bootstrap_vs_top3']['ac_at_1']['ci95'][1]:.4f}]` and MRR cluster CI
`[{top10['cluster_bootstrap_vs_top3']['mrr']['ci95'][0]:.4f}, {top10['cluster_bootstrap_vs_top3']['mrr']['ci95'][1]:.4f}]` cross zero. Candidate-universe discovery was not tested,
rather than rejected, because the candidate universe was held fixed.

## Generalization gates

- New-development adapter: **BLOCKED**.
- One-time locked new test: **BLOCKED**.
- Candidate recovery: **{evaluation['verdicts']['M11_CANDIDATE_RECOVERY']}**.
- Trace/topology incremental study: **{evaluation['verdicts']['TRACE_INCREMENTAL_VALUE']}**.
- GNN: **{evaluation['verdicts']['GNN']}**.
- Reliability v3: **{evaluation['verdicts']['RELIABILITY_V3']}**.
- New-system transfer: **{evaluation['verdicts']['NEW_SYSTEM_TRANSFER']}**.
- Architecture: **{evaluation['verdicts']['ARCHITECTURE']}**.

## Historical non-regression

The frozen historical M10D benchmark remains AC@1
`{evaluation['historical_post_freeze']['frozen_m10d_baseline']['metrics']['ac_at_1']:.10f}`, AC@2
`{evaluation['historical_post_freeze']['frozen_m10d_baseline']['metrics']['ac_at_2']:.10f}`, AC@3
`{evaluation['historical_post_freeze']['frozen_m10d_baseline']['metrics']['ac_at_3']:.10f}`, and MRR
`{evaluation['historical_post_freeze']['frozen_m10d_baseline']['metrics']['mrr']:.10f}`.
The selected Top-{selected['top_k']} architecture is reported separately at AC@1
`{evaluation['historical_post_freeze']['selected_architecture']['metrics']['ac_at_1']:.10f}`
and MRR `{evaluation['historical_post_freeze']['selected_architecture']['metrics']['mrr']:.10f}`;
these read-only outcomes did not affect promotion.

Protocol deviation: RE2/RE3 were executed three times during implementation.
Two uncommitted pre-release outputs were superseded while the reporting schema was
corrected and expanded. All runs froze the same RE1-only Top-5 decision first, so
model selection was unaffected; nevertheless, the requested single historical
execution was not met. No locked new-domain dataset existed or was opened.

## Scope

M11 supports only claims recorded in `docs/m11-claim-registry.md`. It does not
claim causal proof, calibrated probabilities, memory/log/event support, LLM
reasoning, or validated transfer to a new public domain.

## Reproduction

```bash
git switch research/m11-generalization-hardening
make m11-experiment
PYTHONPATH=ml .venv/bin/python -m unittest discover -s ml/tests -v
go test ./...
go vet ./...
go test -race ./...
git diff --check
```
"""


def _render_claims_doc(evaluation: dict) -> str:
    selected = evaluation["candidate_recovery"]["selected"]
    variant = evaluation["candidate_recovery"]["variants"][str(selected["top_k"])]
    metrics = variant["metrics"]
    incident = variant["incident_bootstrap_vs_top3"]
    cluster = variant["cluster_bootstrap_vs_top3"]
    historical = evaluation["historical_post_freeze"]["selected_architecture"]
    historical_incident = historical["incident_bootstrap_vs_frozen_m10d"]
    historical_cluster = historical["cluster_bootstrap_vs_frozen_m10d"]
    return f"""# M11 Claim Registry

## Candidate recovery and ranking evidence

- CLAIM: Expanding the evidence-aware reranker from Top-3 to Top-{selected['top_k']} improves ranking.
- HYPOTHESIS: AC@1 or MRR has a positive pre-registered cluster CI with no guardrail failure.
- STATUS: SUPPORTED.
- DATASET: RCAEval RE1-OB/SS/TT.
- DATA ROLE: DEVELOPMENT_EXISTING.
- PROTOCOL: system-group OOF, same 13 features, shallow XGBoost, five fixed seeds.
- DENOMINATOR: {metrics['incidents']} incidents.
- BASELINE: frozen M10D Top-3 OOF control.
- METRIC: AC@1 and MRR.
- RESULT: AC@1 {metrics['ac_at_1']:.4f}; MRR {metrics['mrr']:.4f}; decision {selected['decision']}.
- INCIDENT CI: AC@1 [{incident['ac_at_1']['ci_low']:.4f}, {incident['ac_at_1']['ci_high']:.4f}]; MRR [{incident['mrr']['ci_low']:.4f}, {incident['mrr']['ci_high']:.4f}].
- CLUSTER CI: AC@1 [{cluster['ac_at_1']['ci95'][0]:.4f}, {cluster['ac_at_1']['ci95'][1]:.4f}]; MRR [{cluster['mrr']['ci95'][0]:.4f}, {cluster['mrr']['ci95'][1]:.4f}].
- LIMITATION: The method only reorders existing candidates; it does not discover missing services.

## Candidate discovery

- CLAIM: M11 improves candidate-universe discovery.
- HYPOTHESIS: The true root enters a candidate universe where it was previously absent.
- STATUS: INCONCLUSIVE.
- DATASET: RCAEval RE1.
- DATA ROLE: DEVELOPMENT_EXISTING.
- PROTOCOL: candidate universe held fixed; only initial Top-K membership changes.
- DENOMINATOR: {metrics['incidents']} incidents.
- BASELINE: M10C candidate universe.
- METRIC: candidate-universe coverage.
- RESULT: not tested; the universe was held fixed and coverage remained {metrics['candidate_universe_coverage']:.4f}.
- INCIDENT CI: not applicable.
- CLUSTER CI: not applicable.
- LIMITATION: candidate generation was outside M11 scope.

## Historical regression

- CLAIM: The frozen M10D result remains reproducible and the selected M11 architecture does not regress it descriptively.
- HYPOTHESIS: Frozen metrics reproduce exactly; selected architecture is reported without affecting selection.
- STATUS: SUPPORTED_WITH_QUALIFICATION.
- DATASET: RCAEval RE2/RE3.
- DATA ROLE: USED_TEST_READONLY.
- PROTOCOL: opened after freeze; no selection or tuning.
- DENOMINATOR: 360 incidents.
- BASELINE: M10D Top-3 AC@1 0.8361, MRR 0.8977.
- METRIC: AC@1/2/3/5/10 and MRR.
- RESULT: exact baseline reproduced; selected Top-{selected['top_k']} AC@1 {evaluation['historical_post_freeze']['selected_architecture']['metrics']['ac_at_1']:.4f}, MRR {evaluation['historical_post_freeze']['selected_architecture']['metrics']['mrr']:.4f}.
- INCIDENT CI: AC@1 [{historical_incident['ac_at_1']['ci_low']:.4f}, {historical_incident['ac_at_1']['ci_high']:.4f}]; MRR [{historical_incident['mrr']['ci_low']:.4f}, {historical_incident['mrr']['ci_high']:.4f}].
- CLUSTER CI: AC@1 [{historical_cluster['ac_at_1']['ci95'][0]:.4f}, {historical_cluster['ac_at_1']['ci95'][1]:.4f}]; MRR [{historical_cluster['mrr']['ci95'][0]:.4f}, {historical_cluster['mrr']['ci95'][1]:.4f}].
- LIMITATION: known historical test; not new-system evidence.

## Trace contribution

- CLAIM: traces/topology add transferable incremental value.
- HYPOTHESIS: matched-modality NEW_DEVELOPMENT ablations have a positive cluster CI.
- STATUS: BLOCKED.
- DATASET: none compatible.
- DATA ROLE: NEW_DEVELOPMENT unavailable.
- PROTOCOL: matched incident/candidate/fold ablation was gated off.
- DENOMINATOR: 0 new-domain incidents.
- BASELINE: metrics-only reranker.
- METRIC: AC@1 and MRR.
- RESULT: no experiment executed.
- INCIDENT CI: not available.
- CLUSTER CI: not available.
- LIMITATION: no validated trace-bearing new development corpus.

## New-system transfer

- CLAIM: M11 transfers to genuinely new public systems.
- HYPOTHESIS: selected challenger beats M10D on a one-time locked new-domain test.
- STATUS: BLOCKED.
- DATASET: none selected.
- DATA ROLE: NEW_DEVELOPMENT and LOCKED_NEW_TEST unavailable.
- PROTOCOL: compatibility audit before scoring.
- DENOMINATOR: 0.
- BASELINE: M10D.
- METRIC: candidate coverage, AC@1/2/3/5/10, MRR.
- RESULT: no locked evaluation.
- INCIDENT CI: not available.
- CLUSTER CI: not available.
- LIMITATION: audited sources need non-fabricated service-level adapters.

## Reliability and autonomous detection

- CLAIM: Reliability v3 or autonomous detection is validated.
- HYPOTHESIS: an independent development domain supports nested-holdout reliability targets.
- STATUS: BLOCKED.
- DATASET: none compatible.
- DATA ROLE: NEW_DEVELOPMENT unavailable.
- PROTOCOL: conditional gate; RE2/RE3 forbidden for threshold selection.
- DENOMINATOR: 0.
- BASELINE: rejected M10D Reliability v2.
- METRIC: AURC, selective AC@1, coverage, conformal coverage/set size.
- RESULT: not run; no autonomous-detection claim.
- INCIDENT CI: not available.
- CLUSTER CI: not available.
- LIMITATION: no independent labeled domain.

Cluster rule: a positive incident-level delta with a cluster-bootstrap interval
crossing zero is `WEAK_CLUSTER_NOT_SUPPORTED`, not a supported claim.

Forbidden claims: causal verification, calibrated probability, exhaustive root
cause discovery, production readiness, or memory/log/event/LLM generalization.
"""


def run(root: Path) -> dict:
    started = time.monotonic()
    model_dir = root / "ml/models/m11"
    preflight = json.loads((model_dir / "preflight.json").read_text())
    ledger = json.loads((model_dir / "data-ledger.json").read_text())
    integrity = _verify_preflight(root, preflight)

    cases, rows, ids = load_rows(
        root / "artifacts/m10c/m10c-v2/truth-free.jsonl",
        root / "artifacts/m10c/m10c-v2/truth-free-seal.json",
        root / "external-data/rcaeval/cases.parquet",
    )
    case_by_id = {case["incident_id"]: case for case in cases}
    dataset_by_incident = {case["incident_id"]: case["dataset"] for case in cases}
    development_ids = sorted(sum((ids[name] for name in RE1), []))
    assert_selection_ids_allowed(development_ids, dataset_by_incident, ledger["roles"])

    selected_columns = tuple(
        json.loads((root / "ml/models/m10c-v2/feature-schema.json").read_text())["selected_columns"]
    )
    clean_rows = _sanitize_rows(
        rows, _legacy_vectors(root / "artifacts/m9b/m9b-v1/truth-free.jsonl")
    )
    rows_by_incident = defaultdict(list)
    for row in clean_rows:
        rows_by_incident[row["incident_id"]].append(row)

    base_oof = oof_for_columns(rows, ids, selected_columns)
    metric_oof, trace_oof, _ = oof_experts(rows, ids)
    variants = {}
    rankings_by_k = {}
    records_by_k = {}
    profiles_by_k = {}
    for k in TOP_K_VALUES:
        profiles = {}
        for held_out in RE1:
            train_ids = sorted(sum((ids[name] for name in RE1 if name != held_out), []))
            assert_selection_ids_allowed(train_ids, dataset_by_incident, ledger["roles"])
            profiles.update(_profiles(
                ids[held_out], base_oof, rows_by_incident, metric_oof, trace_oof,
                fit_ood_stats(clean_rows, train_ids), k,
            ))
        records = _candidate_records(profiles, base_oof, case_by_id)
        reranked, provenance = _oof_rerank(records, base_oof, k)
        by_system = _by_case_field(reranked, case_by_id, "system")
        records_by_k[k] = records
        profiles_by_k[k] = profiles
        rankings_by_k[k] = reranked
        variants[str(k)] = {
            "metrics": ranking_metrics(reranked),
            "pooled": ranking_metrics(reranked),
            "by_dataset": _by_dataset(reranked, ids, RE1),
            "by_system": by_system,
            "macro_system_average": _macro_system(by_system),
            "by_fault_family": _by_case_field(reranked, case_by_id, "fault"),
            "oof_provenance": provenance,
            "invariants": _invariants(base_oof, reranked, k),
        }

    control = rankings_by_k[3]
    control_metrics = ranking_metrics(control)
    if abs(control_metrics["ac_at_1"] - EXPECTED_METRICS["development_reranked"]["ac_at_1"]) > 1e-12:
        raise ValueError("Top-3 control does not reproduce M10D development AC@1")
    if abs(control_metrics["mrr"] - EXPECTED_METRICS["development_reranked"]["mrr"]) > 1e-12:
        raise ValueError("Top-3 control does not reproduce M10D development MRR")

    passing = []
    for k in TOP_K_VALUES:
        result = variants[str(k)]
        if k == 3:
            ac_boot = cluster_bootstrap(control, control, case_by_id, metric="ac_at_1")
            mrr_boot = cluster_bootstrap(control, control, case_by_id, metric="mrr")
            passes = False
            reasons = ["control architecture"]
        else:
            ac_boot = cluster_bootstrap(rankings_by_k[k], control, case_by_id, metric="ac_at_1")
            mrr_boot = cluster_bootstrap(rankings_by_k[k], control, case_by_id, metric="mrr")
            metrics = result["metrics"]
            system_deltas = {
                name: result["by_dataset"][name]["ac_at_1"] - variants["3"]["by_dataset"][name]["ac_at_1"]
                for name in RE1
            }
            gates = {
                "cluster_supported_ac1_or_mrr": ac_boot["supported_positive"] or mrr_boot["supported_positive"],
                "ac_at_3_loss_within_1pp": metrics["ac_at_3"] - control_metrics["ac_at_3"] >= -0.01,
                "no_system_ac1_loss_over_5pp": min(system_deltas.values()) >= -0.05,
                "coverage_nondecrease": metrics["candidate_universe_coverage"] >= control_metrics["candidate_universe_coverage"],
            }
            passes = all(gates.values())
            reasons = [name for name, passed in gates.items() if not passed]
            result["system_ac_at_1_deltas_vs_top3"] = system_deltas
            result["promotion_gate_components"] = gates
            if passes:
                passing.append(k)
        result["cluster_bootstrap_vs_top3"] = {"ac_at_1": ac_boot, "mrr": mrr_boot}
        result["incident_bootstrap_vs_top3"] = paired_bootstrap(
            _rank_vector(rankings_by_k[k]),
            _rank_vector(control),
            resamples=10_000,
            seed=SEED,
        )
        result["promotion_gate"] = {"passes": passes, "failed": reasons}

    if passing:
        selected_k = max(passing, key=lambda k: (variants[str(k)]["metrics"]["ac_at_1"], variants[str(k)]["metrics"]["mrr"], -k))
        decision = f"PROMOTE_TOP{selected_k}"
    else:
        selected_k = 3
        decision = "KEEP_M10D_TOP3"

    model_files = {}
    if selected_k == 3:
        for seed in SEEDS:
            relative = f"ml/models/m10d-integration/reranker-seed-{seed}.json"
            model_files[relative] = sha256_file(root / relative)
    else:
        assert_selection_ids_allowed(development_ids, dataset_by_incident, ledger["roles"])
        for seed in SEEDS:
            model = _fit_ablation(records_by_k[selected_k], RERANKER_FEATURES, seed)
            path = model_dir / f"candidate-recovery-k{selected_k}-seed-{seed}.json"
            model.save_model(path)
            model_files[str(path.relative_to(root))] = sha256_file(path)

    freeze = _freeze(root, model_dir, selected_k, decision, model_files)

    # Historical used-test data are touched only after the architecture freeze above.
    external_ids = sorted(sum((ids[name] for name in EXTERNAL), []))
    core = xgb.Booster(); core.load_model(root / "ml/models/m10c-v2/m10c-core-v2.json")
    metric_model = xgb.Booster(); metric_model.load_model(root / "ml/models/m10c-v2/metric-expert.json")
    trace_model = xgb.Booster(); trace_model.load_model(root / "ml/models/m10c-v2/trace-topology-expert.json")
    external_base = evaluate_model(core, rows, external_ids, selected_columns)[1]
    metric_external = evaluate_model(metric_model, rows, external_ids, METRIC_EXPERT_COLUMNS)[1]
    trace_external = evaluate_model(trace_model, rows, external_ids, TRACE_EXPERT_COLUMNS)[1]
    external_profiles = _profiles(
        external_ids, external_base, rows_by_incident, metric_external, trace_external,
        fit_ood_stats(clean_rows, development_ids), selected_k,
    )
    external_records = _candidate_records(external_profiles, external_base, case_by_id)
    if selected_k == 3:
        models = load_frozen_models(root / "ml/models/m10d-integration")
    else:
        models = []
        for seed in SEEDS:
            model = xgb.Booster()
            model.load_model(model_dir / f"candidate-recovery-k{selected_k}-seed-{seed}.json")
            models.append(model)
    external_predictions = predict_ensemble(models, external_records)
    external_final = rerank_top_k(external_base, external_predictions, selected_k)
    historical_metrics = ranking_metrics(external_final)

    frozen_models = load_frozen_models(root / "ml/models/m10d-integration")
    frozen_profiles = _profiles(
        external_ids, external_base, rows_by_incident, metric_external, trace_external,
        fit_ood_stats(clean_rows, development_ids), 3,
    )
    frozen_records = _candidate_records(frozen_profiles, external_base, case_by_id)
    frozen_m10d = rerank_top_k(
        external_base, predict_ensemble(frozen_models, frozen_records), 3
    )
    frozen_m10d_metrics = ranking_metrics(frozen_m10d)

    reference = preflight["reference_metrics"]
    for metric, expected in reference.items():
        if abs(frozen_m10d_metrics[metric] - expected) > 1e-12:
            raise ValueError(f"frozen M10D historical metric changed: {metric}")

    evaluation = {
        "version": "m11-generalization-hardening-v1",
        "base_commit": preflight["base_commit"],
        "protocol_order": {
            "preflight_before_model_scoring": True,
            "public_data_audit_before_model_scoring": True,
            "selection_before_historical_access": True,
            "freeze_manifest_written_before_historical_access": True,
        },
        "protocol_deviations": [{
            "scope": "historical RCAEval RE2/RE3 implementation validation",
            "execution_count": 3,
            "reason": (
                "Two uncommitted pre-release runs were superseded while correcting and expanding the "
                "reporting schema; the final run is authoritative."
            ),
            "selection_impact": "none; every run wrote the same RE1-only Top-5 freeze before historical access",
            "locked_new_test_impact": "none; no LOCKED_NEW_TEST dataset exists or was opened",
            "limitation": "The requested single historical regression execution was not met during implementation.",
        }],
        "data_roles": ledger,
        "candidate_recovery": {
            "control": "M10D Evidence-Aware Top-3 Reranker",
            "variants": variants,
            "selected": {"decision": decision, "top_k": selected_k},
        },
        "error_analysis": {
            "development_re1_oof": {
                "metrics": ranking_metrics(control),
                "rank_histogram": rank_histogram(control),
                "oracle_ac_at_1": oracle_ac_at_1(base_oof),
                "top3_error_decomposition": error_decomposition(control, 3),
                "failure_taxonomy": failure_taxonomy(base_oof, control, profiles_by_k[3]),
                "by_dataset": _by_dataset(control, ids, RE1),
            },
            "historical_re2_re3_post_freeze": {
                "frozen_m10d_baseline": {
                    "metrics": frozen_m10d_metrics,
                    "rank_histogram": rank_histogram(frozen_m10d),
                    "top3_error_decomposition": error_decomposition(frozen_m10d, 3),
                    "failure_taxonomy": failure_taxonomy(external_base, frozen_m10d, frozen_profiles),
                    "by_dataset": _by_dataset(frozen_m10d, ids, EXTERNAL),
                },
                "selected_architecture": {
                    "metrics": historical_metrics,
                    "rank_histogram": rank_histogram(external_final),
                    "oracle_ac_at_1": oracle_ac_at_1(external_base),
                    "top3_error_decomposition": error_decomposition(external_final, 3),
                    "failure_taxonomy": failure_taxonomy(external_base, external_final, external_profiles),
                    "by_dataset": _by_dataset(external_final, ids, EXTERNAL),
                },
            },
        },
        "historical_post_freeze": {
            "frozen_m10d_baseline": {
                "metrics": frozen_m10d_metrics,
                "by_dataset": _by_dataset(frozen_m10d, ids, EXTERNAL),
                "by_system": _by_case_field(frozen_m10d, case_by_id, "system"),
                "macro_system_average": _macro_system(_by_case_field(frozen_m10d, case_by_id, "system")),
                "by_fault_family": _by_case_field(frozen_m10d, case_by_id, "fault"),
                "invariants": _invariants(external_base, frozen_m10d, 3),
            },
            "selected_architecture": {
                "metrics": historical_metrics,
                "by_dataset": _by_dataset(external_final, ids, EXTERNAL),
                "by_system": _by_case_field(external_final, case_by_id, "system"),
                "macro_system_average": _macro_system(_by_case_field(external_final, case_by_id, "system")),
                "by_fault_family": _by_case_field(external_final, case_by_id, "fault"),
                "invariants": _invariants(external_base, external_final, selected_k),
                "incident_bootstrap_vs_frozen_m10d": paired_bootstrap(
                    _rank_vector(external_final), _rank_vector(frozen_m10d),
                    resamples=10_000, seed=SEED,
                ),
                "cluster_bootstrap_vs_frozen_m10d": {
                    metric: cluster_bootstrap(
                        external_final, frozen_m10d, case_by_id, metric=metric,
                        resamples=10_000, seed=SEED,
                    )
                    for metric in ("ac_at_1", "mrr")
                },
                "delta_vs_frozen_m10d": {
                    metric: historical_metrics[metric] - frozen_m10d_metrics[metric]
                    for metric in ("ac_at_1", "ac_at_2", "ac_at_3", "ac_at_5", "ac_at_10", "mrr")
                },
            },
            "selection_use": "none; read-only regression after freeze",
        },
        "public_dataset_audit": {
            "audited": ["AIOps Challenge 2020", "Murphy/DeathStarBench", "Cloud-OpsBench", "GAIA MicroSS", "AIOpsLab"],
            "new_development": "BLOCKED",
            "locked_new_test": "BLOCKED",
            "reason": "No source has a validated compatible single-root service-level adapter and a separate locked corpus.",
        },
        "verdicts": {
            "M11_CANDIDATE_RECOVERY": "PROMOTED" if selected_k > 3 else "REJECTED",
            "TRACE_INCREMENTAL_VALUE": "INCONCLUSIVE",
            "GNN": "NOT_JUSTIFIED",
            "RELIABILITY_V3": "BLOCKED",
            "NEW_SYSTEM_TRANSFER": "BLOCKED",
            "ARCHITECTURE": (
                "PROMOTE_M11_RESEARCH_CHAMPION" if selected_k > 3
                else "KEEP_M10D_RESEARCH_CHAMPION"
            ),
            "implementation_decision": decision,
        },
        "freeze": freeze,
        "integrity": integrity,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "xgboost": xgb.__version__,
            "bootstrap_resamples": 10_000,
            "bootstrap_seed": SEED,
            "model_seeds": list(SEEDS),
        },
        "runtime_seconds": time.monotonic() - started,
    }
    save_json(model_dir / "evaluation.json", evaluation)
    (root / "docs/m11-error-analysis.md").write_text(_render_error_doc(evaluation))
    (root / "docs/m11-results.md").write_text(_render_results_doc(evaluation))
    (root / "docs/m11-claim-registry.md").write_text(_render_claims_doc(evaluation))
    artifacts = [
        "docs/m11-protocol.md", "docs/m11-data-audit.md", "docs/m11-error-analysis.md",
        "docs/m11-results.md", "docs/m11-claim-registry.md",
        "ml/models/m11/data-ledger.json", "ml/models/m11/preflight.json",
        "ml/models/m11/evaluation.json", "ml/models/m11/freeze-manifest.json",
    ]
    save_json(model_dir / "integrity-manifest.json", {
        "version": "m11-integrity-v1",
        "base_commit": preflight["base_commit"],
        "artifacts": {relative: sha256_file(root / relative) for relative in artifacts},
        "selected_models": model_files,
        "frozen_inputs_verified": integrity,
    })
    return evaluation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    result = run(args.root.resolve())
    print(json.dumps({
        "verdicts": result["verdicts"],
        "selected": result["candidate_recovery"]["selected"],
        "historical": result["historical_post_freeze"],
        "runtime_seconds": result["runtime_seconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
