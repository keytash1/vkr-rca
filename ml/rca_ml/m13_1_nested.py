"""Strict nested grouped validation of the frozen M13 selection procedure."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from collections import Counter, defaultdict
from pathlib import Path

import xgboost as xgb

from .dataset import sha256_file
from .m12_adapter import canonical_features
from .m12_evaluate import rank_candidates
from .m13_experiment import (
    ABLATIONS,
    GRID,
    _base_rank_features,
    _comparison,
    _fit,
    _fusion_rows,
    _groups,
    _macro,
    _predict,
    _rerank_top_k,
)
from .m13_features import (
    COVERAGE_FEATURES,
    DIRECT_FEATURES,
    DISAPPEARANCE_FEATURES,
    PROPAGATION_FEATURES,
    TRACE_FEATURES,
    build_candidate_rows,
)
from .m13_protocol import (
    SEED,
    assert_selection_ids_allowed,
    cluster_key,
    deterministic_chance,
    grouped_folds,
    ranking_metrics,
)

OUTER_FOLDS = 5
INNER_FOLDS = 4
EXPERT_FOLDS = 3
ARCHITECTURES = (
    "extended_full_top5",
    "two_expert_fusion_top5",
    "full_candidate_challenger",
)
FULL_COLUMNS = ABLATIONS["full_with_ranking_context"]
DIRECT_EXPERT_COLUMNS = DIRECT_FEATURES + TRACE_FEATURES + COVERAGE_FEATURES
CONTEXT_EXPERT_COLUMNS = PROPAGATION_FEATURES + DISAPPEARANCE_FEATURES + COVERAGE_FEATURES
FUSION_COLUMNS = (
    "direct_score",
    "context_score",
    "score_mean",
    "score_disagreement",
    "base_rank_percentile",
    "candidate_count_log",
    "missing_metric_modality",
    "missing_trace_modality",
    "trace_coverage",
)


def _id_sha(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def _verify_frozen_inputs(root: Path) -> dict:
    manifest = json.loads((root / "ml/models/m13-1/frozen-inputs.json").read_text())
    for relative, expected in manifest["m13_sha256"].items():
        actual = sha256_file(root / relative)
        if actual != expected:
            raise RuntimeError(f"M13.1 frozen input changed: {relative}: {actual} != {expected}")
    if manifest["reserved_final_scored"]:
        raise RuntimeError("reserved final system is not available to M13.1")
    return manifest


def _load_development(root: Path) -> tuple[dict, dict, list[dict], dict]:
    run_dir = root / "external-data/m13/runs/development-v1"
    model_dir = root / "ml/models/m13"
    baseline = json.loads((model_dir / "healthy-baseline.json").read_text())
    legacy_baseline = json.loads((model_dir / "legacy-metric-baseline.json").read_text())
    corpus = json.loads((model_dir / "corpus-manifest.json").read_text())
    services = json.loads((model_dir / "system-manifest.json").read_text())["candidate_services"]
    index_path = run_dir / "telemetry-index.jsonl"
    truth_path = run_dir / "truth.jsonl"
    if sha256_file(index_path) != corpus["telemetry_index_sha256"]:
        raise RuntimeError("M13.1 telemetry index differs from frozen M13 corpus")
    if sha256_file(truth_path) != corpus["truth_sha256"]:
        raise RuntimeError("M13.1 truth differs from frozen M13 corpus")

    index = [json.loads(line) for line in index_path.read_text().splitlines() if line]
    rows_by_id: dict[str, list[dict]] = {}
    rankings = {name: {} for name in ("chance", "metric_heuristic", "frozen_m11")}
    for item in index:
        incident_id = str(item["incident_id"])
        assert_selection_ids_allowed([incident_id])
        telemetry_path = run_dir / item["telemetry_path"]
        if sha256_file(telemetry_path) != item["sha256"]:
            raise RuntimeError(f"M13.1 telemetry seal mismatch: {incident_id}")
        payload = json.loads(telemetry_path.read_text())
        clean = {key: value for key, value in payload.items() if key != "incident_id"}
        rows = build_candidate_rows(clean, baseline, services)
        legacy_rows = canonical_features(payload["metrics"], legacy_baseline, services, baseline["expected_edges"])
        frozen = rank_candidates(incident_id, legacy_rows, root)["m11_top5"]
        _base_rank_features(rows, frozen)
        for row in rows:
            row["incident_id"] = incident_id
        rows_by_id[incident_id] = rows
        rankings["chance"][incident_id] = deterministic_chance(incident_id, services)
        rankings["metric_heuristic"][incident_id] = sorted(
            (
                {"service": row["service"], "score": float(row["features"]["metric_max_shift"])}
                for row in rows
            ),
            key=lambda value: (-value["score"], value["service"]),
        )
        for rank, value in enumerate(rankings["metric_heuristic"][incident_id], 1):
            value["rank"] = rank
        rankings["frozen_m11"][incident_id] = frozen

    truth_items = [json.loads(line) for line in truth_path.read_text().splitlines() if line]
    truth = {
        item["incident_id"]: {**item, "system": "DeathStarBench-SocialNetwork"}
        for item in truth_items
        if item["valid_injection"]
    }
    if set(truth) != set(rows_by_id) or len(truth) != 120:
        raise RuntimeError("M13.1 requires the complete frozen 120-incident denominator")
    cases = [truth[incident_id] for incident_id in sorted(truth)]
    for incident_id, rows in rows_by_id.items():
        for row in rows:
            row["target"] = int(row["service"] == truth[incident_id]["root_service"])
    return rows_by_id, truth, cases, rankings


def _fit_predict_fusion(
    rows_by_id: dict,
    truth: dict,
    cases: list[dict],
    train_ids: list[str],
    test_ids: list[str],
    config: dict,
    seed: int,
    expert_folds: int,
) -> tuple[dict, dict]:
    train_cases = [item for item in cases if item["incident_id"] in set(train_ids)]
    train_truth = {incident_id: truth[incident_id] for incident_id in train_ids}
    assignments = grouped_folds(train_cases, folds=expert_folds, seed=seed + 17)
    direct_oof, direct_provenance = _fixed_oof(
        rows_by_id, train_truth, train_cases, DIRECT_EXPERT_COLUMNS, config, seed + 101, assignments
    )
    context_oof, context_provenance = _fixed_oof(
        rows_by_id, train_truth, train_cases, CONTEXT_EXPERT_COLUMNS, config, seed + 211, assignments
    )
    fusion_train = _fusion_rows(rows_by_id, train_ids, direct_oof, context_oof)
    fusion_model = _fit(fusion_train, train_ids, FUSION_COLUMNS, config, seed + 307)
    direct_model = _fit(rows_by_id, train_ids, DIRECT_EXPERT_COLUMNS, config, seed + 401)
    context_model = _fit(rows_by_id, train_ids, CONTEXT_EXPERT_COLUMNS, config, seed + 503)
    direct_test = _predict(direct_model, rows_by_id, test_ids, DIRECT_EXPERT_COLUMNS)
    context_test = _predict(context_model, rows_by_id, test_ids, CONTEXT_EXPERT_COLUMNS)
    fusion_test = _fusion_rows(rows_by_id, test_ids, direct_test, context_test)
    predictions = _predict(fusion_model, fusion_test, test_ids, FUSION_COLUMNS)
    return predictions, {
        "fusion_training_expert_predictions": "GROUPED_OOF_ONLY",
        "in_sample_expert_scores_used_for_fusion": False,
        "expert_folds": expert_folds,
        "direct_expert_provenance": direct_provenance,
        "context_expert_provenance": context_provenance,
    }


def _fixed_oof(rows_by_id, truth, cases, columns, config, seed, assignments):
    predictions, provenance = {}, []
    for fold in sorted(set(assignments.values())):
        test_ids = sorted(incident_id for incident_id, value in assignments.items() if value == fold)
        train_ids = sorted(set(assignments) - set(test_ids))
        train_clusters = {cluster_key(truth[incident_id]) for incident_id in train_ids}
        test_clusters = {cluster_key(truth[incident_id]) for incident_id in test_ids}
        if train_clusters & test_clusters:
            raise RuntimeError("M13.1 inner repetition-cluster leakage")
        model = _fit(rows_by_id, train_ids, columns, config, seed + int(fold))
        predictions.update(_predict(model, rows_by_id, test_ids, columns))
        provenance.append({
            "fold": int(fold),
            "train_incidents": len(train_ids),
            "test_incidents": len(test_ids),
            "train_test_clusters_disjoint": True,
            "expert_predictions_in_sample": False,
        })
    if set(predictions) != set(truth):
        raise RuntimeError("M13.1 inner OOF denominator mismatch")
    return predictions, provenance


def _fusion_oof_for_selection(rows_by_id, truth, cases, config, assignments, seed):
    predictions, provenance = {}, []
    for fold in sorted(set(assignments.values())):
        test_ids = sorted(incident_id for incident_id, value in assignments.items() if value == fold)
        train_ids = sorted(set(assignments) - set(test_ids))
        current, detail = _fit_predict_fusion(
            rows_by_id, truth, cases, train_ids, test_ids, config, seed + int(fold) * 1000, EXPERT_FOLDS
        )
        predictions.update(current)
        provenance.append({
            "inner_architecture_fold": int(fold),
            "train_incidents": len(train_ids),
            "test_incidents": len(test_ids),
            "outer_test_incidents_used": 0,
            **detail,
        })
    if set(predictions) != set(truth):
        raise RuntimeError("M13.1 fusion selection denominator mismatch")
    return predictions, provenance


def _select_inside_outer_train(rows_by_id, truth, cases, rankings, outer_fold):
    inner_assignments = grouped_folds(cases, folds=INNER_FOLDS, seed=SEED + 100 + outer_fold)
    config_search, full_predictions = [], {}
    for config in GRID:
        predictions, provenance = _fixed_oof(
            rows_by_id, truth, cases, FULL_COLUMNS, config, SEED + 1000 + outer_fold * 100, inner_assignments
        )
        metrics = ranking_metrics(predictions, truth)
        key = json.dumps(config, sort_keys=True)
        full_predictions[key] = (predictions, provenance)
        config_search.append({"config": config, "ac_at_1": metrics["ac_at_1"], "mrr": metrics["mrr"]})
    config_search.sort(
        key=lambda item: (
            -item["mrr"], -item["ac_at_1"], item["config"]["max_depth"],
            item["config"]["rounds"], -item["config"]["eta"],
        )
    )
    selected_config = config_search[0]["config"]
    full, full_provenance = full_predictions[json.dumps(selected_config, sort_keys=True)]
    frozen = {incident_id: rankings["frozen_m11"][incident_id] for incident_id in truth}
    architecture_predictions = {
        "extended_full_top5": _rerank_top_k(frozen, full, 5),
        "full_candidate_challenger": full,
    }
    fusion, fusion_provenance = _fusion_oof_for_selection(
        rows_by_id, truth, cases, selected_config, inner_assignments, SEED + 20_000 + outer_fold * 1000
    )
    architecture_predictions["two_expert_fusion_top5"] = _rerank_top_k(frozen, fusion, 5)
    architecture_search = [
        {"architecture": name, **{key: value for key, value in ranking_metrics(predictions, truth).items() if key in {"ac_at_1", "mrr"}}}
        for name, predictions in architecture_predictions.items()
    ]
    architecture_search.sort(key=lambda item: (-item["mrr"], -item["ac_at_1"], item["architecture"]))
    return {
        "selected_config": selected_config,
        "selected_architecture": architecture_search[0]["architecture"],
        "config_search": config_search,
        "architecture_search": architecture_search,
        "full_oof_provenance": full_provenance,
        "fusion_oof_provenance": fusion_provenance,
        "inner_assignments": inner_assignments,
    }


def _fit_selected_outer(rows_by_id, truth, cases, rankings, train_ids, test_ids, selection, outer_fold):
    config = selection["selected_config"]
    architecture = selection["selected_architecture"]
    seed = SEED + 50_000 + outer_fold * 10_000
    if architecture == "two_expert_fusion_top5":
        full, provenance = _fit_predict_fusion(
            rows_by_id, truth, cases, train_ids, test_ids, config, seed, INNER_FOLDS
        )
        frozen_test = {incident_id: rankings["frozen_m11"][incident_id] for incident_id in test_ids}
        return _rerank_top_k(frozen_test, full, 5), provenance
    model = _fit(rows_by_id, train_ids, FULL_COLUMNS, config, seed)
    full = _predict(model, rows_by_id, test_ids, FULL_COLUMNS)
    if architecture == "extended_full_top5":
        frozen_test = {incident_id: rankings["frozen_m11"][incident_id] for incident_id in test_ids}
        full = _rerank_top_k(frozen_test, full, 5)
    return full, {"fusion_training_expert_predictions": "NOT_APPLICABLE", "in_sample_expert_scores_used_for_fusion": False}


def _render_docs(root: Path, evaluation: dict) -> None:
    models = evaluation["pooled"]
    table = [
        "| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, value in models.items():
        table.append(
            f"| {name} | {value['ac_at_1']:.4f} | {value['ac_at_2']:.4f} | "
            f"{value['ac_at_3']:.4f} | {value['ac_at_5']:.4f} | {value['ac_at_10']:.4f} | "
            f"{value['mrr']:.4f} | {value['candidate_universe_coverage']:.4f} |"
        )
    folds = [
        "| Outer fold | Selected architecture | depth | eta | rounds | Outer AC@1 | Outer MRR |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for item in evaluation["outer_folds"]:
        config = item["selected_config"]
        metrics = item["outer_test_metrics"]
        folds.append(
            f"| {item['outer_fold']} | {item['selected_architecture']} | {config['max_depth']} | "
            f"{config['eta']} | {config['rounds']} | {metrics['ac_at_1']:.4f} | {metrics['mrr']:.4f} |"
        )
    result = f"""# M13.1 Nested Validation Results

This is a strict outer grouped estimate of the frozen M13 selection procedure.
No outer-test incident participated in configuration or architecture selection.

{chr(10).join(table)}

## Fold-level selection

{chr(10).join(folds)}

Selection stability: `{json.dumps(evaluation['selection_stability'], sort_keys=True)}`.

Nested minus original M13 headline: AC@1
`{evaluation['selection_optimism']['ac_at_1_delta']:.4f}`, MRR
`{evaluation['selection_optimism']['mrr_delta']:.4f}`. This difference is a
method-selection optimism diagnostic, not a new tuning target.

`FINAL_TEST_READY = {evaluation['verdicts']['final_test_ready']}`.

The result remains development-only. OpenTelemetry Astronomy Shop was not
cloned, deployed, faulted or scored.
"""
    (root / "docs/m13-1-results.md").write_text(result)

    claim_lines = ["# M13.1 Claim Registry", ""]
    for name, comparison in evaluation["paired_nested_vs"].items():
        supported = comparison["ac_at_1"]["cluster"]["supported_positive"] or comparison["mrr"]["cluster"]["supported_positive"]
        claim_lines.extend([
            f"## Nested selection procedure vs {name}", "",
            f"- CLAIM: nested selection procedure vs {name}",
            "- HYPOTHESIS: nested procedure improves AC@1 or MRR",
            f"- STATUS: {'SUPPORTED' if supported else 'NOT_SUPPORTED'}",
            "- DATASET: DeathStarBench Social Network",
            "- DATA ROLE: NEW_DEVELOPMENT",
            "- PROTOCOL: five-fold outer grouped validation with inner-only selection",
            "- DENOMINATOR: 120 incidents / 60 clusters",
            f"- BASELINE: {name}",
            "- METRIC: AC@1 or MRR",
            f"- RESULT: {json.dumps(comparison, sort_keys=True)}",
            f"- INCIDENT CI: {json.dumps(comparison['mrr']['incident']['ci95'])}",
            f"- CLUSTER CI: {json.dumps(comparison['mrr']['cluster']['ci95'])}",
            "- LIMITATION: one development system; final cross-system test remains untouched",
            "",
        ])
    (root / "docs/m13-1-claim-registry.md").write_text("\n".join(claim_lines))


def run(root: Path) -> dict:
    frozen_inputs = _verify_frozen_inputs(root)
    rows_by_id, truth, cases, rankings = _load_development(root)
    outer_assignments = grouped_folds(cases, folds=OUTER_FOLDS, seed=SEED)
    nested_predictions, outer_records = {}, []
    all_outer_test_ids: list[str] = []

    for outer_fold in sorted(set(outer_assignments.values())):
        test_ids = sorted(incident_id for incident_id, value in outer_assignments.items() if value == outer_fold)
        train_ids = sorted(set(outer_assignments) - set(test_ids))
        train_truth = {incident_id: truth[incident_id] for incident_id in train_ids}
        train_cases = [item for item in cases if item["incident_id"] in set(train_ids)]
        train_rankings = {name: {incident_id: value[incident_id] for incident_id in train_ids} for name, value in rankings.items()}
        train_clusters = {cluster_key(truth[incident_id]) for incident_id in train_ids}
        test_clusters = {cluster_key(truth[incident_id]) for incident_id in test_ids}
        if train_clusters & test_clusters:
            raise RuntimeError("M13.1 outer repetition-cluster leakage")
        selection = _select_inside_outer_train(
            rows_by_id, train_truth, train_cases, train_rankings, int(outer_fold)
        )
        if set(selection["inner_assignments"]) != set(train_ids):
            raise RuntimeError("M13.1 outer-test incident reached inner selection")
        current, final_fit_provenance = _fit_selected_outer(
            rows_by_id, truth, cases, rankings, train_ids, test_ids, selection, int(outer_fold)
        )
        if set(current) != set(test_ids):
            raise RuntimeError("M13.1 outer prediction denominator mismatch")
        nested_predictions.update(current)
        all_outer_test_ids.extend(test_ids)
        outer_truth = {incident_id: truth[incident_id] for incident_id in test_ids}
        outer_records.append({
            "outer_fold": int(outer_fold),
            "train_incidents": len(train_ids),
            "test_incidents": len(test_ids),
            "train_clusters": len(train_clusters),
            "test_clusters": len(test_clusters),
            "train_test_clusters_disjoint": True,
            "outer_test_used_for_selection": False,
            "outer_train_ids_sha256": _id_sha(train_ids),
            "outer_test_ids": test_ids,
            "inner_selection_ids_sha256": _id_sha(list(selection["inner_assignments"])),
            "selected_config": selection["selected_config"],
            "selected_architecture": selection["selected_architecture"],
            "config_search": selection["config_search"],
            "architecture_search": selection["architecture_search"],
            "full_oof_provenance": selection["full_oof_provenance"],
            "fusion_oof_provenance": selection["fusion_oof_provenance"],
            "final_fit_provenance": final_fit_provenance,
            "outer_test_metrics": ranking_metrics(current, outer_truth),
        })

    if set(nested_predictions) != set(truth) or Counter(all_outer_test_ids) != Counter({incident_id: 1 for incident_id in truth}):
        raise RuntimeError("M13.1 outer-test aggregation is not exactly-once")

    rankings["nested_selected_procedure"] = nested_predictions
    pooled = {name: ranking_metrics(values, truth) for name, values in rankings.items()}
    comparisons = {
        name: _comparison(nested_predictions, rankings[name], truth)
        for name in ("chance", "metric_heuristic", "frozen_m11")
    }
    per_fault = {name: _groups(values, truth, "fault_family") for name, values in rankings.items()}
    per_root = {name: _groups(values, truth, "root_service") for name, values in rankings.items()}
    beats = {
        name: comparisons[name]["ac_at_1"]["cluster"]["supported_positive"]
        or comparisons[name]["mrr"]["cluster"]["supported_positive"]
        for name in comparisons
    }
    coverage_ok = pooled["nested_selected_procedure"]["candidate_universe_coverage"] == 1.0
    provenance_ok = all(
        item["train_test_clusters_disjoint"] and not item["outer_test_used_for_selection"]
        and not item["final_fit_provenance"]["in_sample_expert_scores_used_for_fusion"]
        for item in outer_records
    )
    ready = beats["metric_heuristic"] and beats["frozen_m11"] and coverage_ok and provenance_ok
    original = json.loads((root / "ml/models/m13/evaluation.json").read_text())["pooled"]["full_candidate_challenger"]
    selected = pooled["nested_selected_procedure"]
    architecture_counts = Counter(item["selected_architecture"] for item in outer_records)
    config_counts = Counter(json.dumps(item["selected_config"], sort_keys=True) for item in outer_records)
    selected_fault = per_fault["nested_selected_procedure"]
    selected_root = per_root["nested_selected_procedure"]

    evaluation = {
        "version": "m13-1-nested-evaluation-v1",
        "base_commit": frozen_inputs["base_commit"],
        "protocol": {
            "outer_folds": OUTER_FOLDS,
            "inner_folds": INNER_FOLDS,
            "expert_oof_folds": EXPERT_FOLDS,
            "outer_unit": "complete repetition cluster",
            "cluster_key": ["system", "root_service", "fault_family", "workload_regime", "intensity"],
            "architecture_candidates": list(ARCHITECTURES),
            "feature_changes": 0,
            "new_model_families": 0,
        },
        "pooled": pooled,
        "paired_nested_vs": comparisons,
        "per_fault": per_fault,
        "per_root": per_root,
        "macro_fault": {name: _macro(values) for name, values in per_fault.items()},
        "macro_root": {name: _macro(values) for name, values in per_root.items()},
        "worst_groups": {
            "fault_ac_at_1": min(selected_fault.items(), key=lambda item: item[1]["ac_at_1"]),
            "root_ac_at_1": min(selected_root.items(), key=lambda item: item[1]["ac_at_1"]),
        },
        "outer_folds": outer_records,
        "selection_stability": {
            "architecture_counts": dict(sorted(architecture_counts.items())),
            "config_counts": dict(sorted(config_counts.items())),
        },
        "selection_optimism": {
            "original_m13_ac_at_1": original["ac_at_1"],
            "nested_ac_at_1": selected["ac_at_1"],
            "ac_at_1_delta": selected["ac_at_1"] - original["ac_at_1"],
            "original_m13_mrr": original["mrr"],
            "nested_mrr": selected["mrr"],
            "mrr_delta": selected["mrr"] - original["mrr"],
        },
        "decision_gates": {
            "beats_metric_heuristic_cluster_supported": beats["metric_heuristic"],
            "beats_frozen_m11_cluster_supported": beats["frozen_m11"],
            "candidate_coverage_full": coverage_ok,
            "complete_denominator": len(nested_predictions) == 120,
            "outer_provenance_valid": provenance_ok,
        },
        "verdicts": {
            "nested_vs_metric_heuristic": "SUPPORTED" if beats["metric_heuristic"] else "NOT_SUPPORTED",
            "nested_vs_frozen_m11": "SUPPORTED" if beats["frozen_m11"] else "NOT_SUPPORTED",
            "final_test_ready": "YES" if ready else "NO",
        },
        "data_isolation": {
            "m12_incidents_used": 0,
            "re2_re3_incidents_used": 0,
            "reserved_final_incidents_used": 0,
            "reserved_final_scored": False,
        },
        "environment": {"python": platform.python_version(), "xgboost": xgb.__version__},
    }
    output_dir = root / "ml/models/m13-1"
    evaluation_path = output_dir / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation, indent=2, sort_keys=True) + "\n")
    _render_docs(root, evaluation)

    integrity_files = sorted({
        "Makefile",
        "docs/m13-1-protocol.md",
        "docs/m13-1-results.md",
        "docs/m13-1-claim-registry.md",
        "ml/rca_ml/m13_1_nested.py",
        "ml/tests/test_m13_1.py",
        "ml/models/m13-1/frozen-inputs.json",
        "ml/models/m13-1/evaluation.json",
        *frozen_inputs["m13_sha256"].keys(),
    })
    integrity = {
        "version": "m13-1-integrity-v1",
        "sha256": {relative: sha256_file(root / relative) for relative in integrity_files},
    }
    (output_dir / "integrity-manifest.json").write_text(json.dumps(integrity, indent=2, sort_keys=True) + "\n")
    return evaluation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    evaluation = run(Path(args.root).resolve())
    print(json.dumps({
        "pooled": evaluation["pooled"],
        "selection_stability": evaluation["selection_stability"],
        "verdicts": evaluation["verdicts"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
