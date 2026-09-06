"""Reproduce and interpret the promoted M10D Evidence-Aware Top-3 Reranker."""

from __future__ import annotations

import argparse
import json
import platform
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import read_jsonl, sha256_file
from .m10c_experiment import (
    EXTERNAL,
    RE1,
    extended_metrics,
    load_rows,
    oof_experts,
    oof_for_columns,
    subset_rankings,
)
from .m10c_integrity import verify_frozen
from .m10c_schema import (
    FEATURE_COLUMNS_M10C,
    METRIC_EXPERT_COLUMNS,
    TRACE_EXPERT_COLUMNS,
)
from .m10d_reranker import (
    COMPONENTS,
    EVIDENCE_FEATURES,
    RANKING_CONTEXT_FEATURES,
    RERANKER_FEATURES,
    SEEDS,
    TOP_K,
    build_evidence_features,
    build_reranker_records,
    fit_ood_stats,
    load_frozen_models,
    predict_ensemble,
    rerank_top3,
)
from .m9b_model import evaluate_model
from .metrics import paired_bootstrap
from .train import save_json

SEED = 20260906
EXPECTED_MODEL_HASHES = {
    "reranker-seed-20260906.json": "880f7870eab35a73cfa37adaeddd8f80d7ddba92abd4cf6223b4828446b3a5da",
    "reranker-seed-20260907.json": "06c0d4343bb48c679084b89e8896e2b76d0e207ffba31801dcb3ced596785b44",
    "reranker-seed-20260908.json": "22b32193cd7c7d7b5e84833315761166a88415be55073cc71d73c5f6647bdc07",
    "reranker-seed-20260909.json": "0b63c093f9d9d29b2f5412f8194a57cf04c9cc0bc6fcd2664f5bbba63fe27a0b",
    "reranker-seed-20260910.json": "88648e01f8e67d6fc06d5eaf5b2d16cf6d386ef498df93724249b15bd87f156c",
}
EXPECTED_METRICS = {
    "development_base": {"ac_at_1": .72, "mrr": .8326417261101472},
    "development_reranked": {"ac_at_1": .7813333333333333, "mrr": .865530614999036},
    "external_base": {"ac_at_1": .7888888888888889, "mrr": .8690174062049062},
    "external_reranked": {"ac_at_1": .8361111111111111, "mrr": .8977211099086099},
}
ABLATIONS = {
    "ranking_context_only": RANKING_CONTEXT_FEATURES,
    "diagnostic_evidence_only": EVIDENCE_FEATURES,
    "full_evidence_aware": RERANKER_FEATURES,
}


def _strip_ranking(ranking: list[dict]) -> list[dict]:
    return [
        {"service": item["service"], "rank": int(item["rank"]), "score": float(item["score"])}
        for item in ranking
    ]


def _legacy_vectors(path: Path) -> dict[tuple[str, str], dict]:
    result = {}
    for record in read_jsonl(path):
        for item in record["features"]["services"]:
            result[(record["external_case_id"], item["service"])] = item["vector"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--m10c-artifacts", type=Path, default=Path("artifacts/m10c/m10c-v2")
    )
    parser.add_argument(
        "--m9b-truth-free",
        type=Path,
        default=Path("artifacts/m9b/m9b-v1/truth-free.jsonl"),
    )
    parser.add_argument(
        "--models", type=Path, default=Path("ml/models/m10d-integration")
    )
    args = parser.parse_args()
    result = run(
        args.root.resolve(),
        args.m10c_artifacts.resolve(),
        args.m9b_truth_free.resolve(),
        args.models.resolve(),
    )
    print(json.dumps({
        "verdicts": result["verdicts"],
        "development": result["development"],
        "external_post_freeze": result["external_post_freeze"],
        "ablation": result["ablation"],
        "runtime_seconds": result["runtime_seconds"],
    }, indent=2))


def _sanitize_rows(rows: list[dict], legacy: dict[tuple[str, str], dict]) -> list[dict]:
    result = []
    for source in rows:
        row = {"incident_id": source["incident_id"], "service": source["service"]}
        row.update({name: float(source.get(name, 0.0)) for name in FEATURE_COLUMNS_M10C})
        old = legacy.get((source["incident_id"], source["service"]), {})
        row.update({
            name: float(value)
            for name, value in old.items()
            if name.startswith("trace_") or name == "has_trace"
        })
        result.append(row)
    return result


def _profiles_for_incidents(
    incident_ids: list[str],
    rankings: dict[str, list[dict]],
    rows_by_incident: dict[str, list[dict]],
    metric_rankings: dict[str, list[dict]],
    trace_rankings: dict[str, list[dict]],
    ood_stats: dict,
) -> dict[str, list[dict]]:
    return {
        incident: build_evidence_features(
            rows_by_incident[incident],
            _strip_ranking(rankings[incident]),
            metric_ranking=_strip_ranking(metric_rankings[incident]),
            trace_ranking=_strip_ranking(trace_rankings[incident]),
            ood_stats=ood_stats,
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
        ranking = sorted(rankings[incident], key=lambda item: int(item["rank"]))
        truth = next(item["service"] for item in ranking if int(item["label"]) == 1)
        for record in build_reranker_records(incident, profiles[incident], ranking):
            records.append({
                **record,
                "dataset": case_by_id[incident]["dataset"],
                "target": int(record["service"] == truth),
            })
    return records


def _fit_ablation(records: list[dict], columns: tuple[str, ...], seed: int) -> xgb.Booster:
    if not records or len({item["target"] for item in records}) < 2:
        raise ValueError("reranker training requires positive and negative candidates")
    matrix = np.asarray(
        [[float(item[name]) for name in columns] for item in records], dtype=np.float32
    )
    target = np.asarray([int(item["target"]) for item in records], dtype=np.float32)
    data = xgb.DMatrix(matrix, label=target, feature_names=list(columns))
    return xgb.train(
        {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "max_depth": 2,
            "eta": .08,
            "min_child_weight": 3,
            "subsample": .8,
            "colsample_bytree": .8,
            "seed": seed,
            "nthread": 4,
        },
        data,
        num_boost_round=24,
        verbose_eval=False,
    )


def _predict(
    model: xgb.Booster,
    records: list[dict],
    columns: tuple[str, ...],
) -> dict[tuple[str, str], float]:
    matrix = np.asarray(
        [[float(item[name]) for name in columns] for item in records], dtype=np.float32
    )
    values = model.predict(xgb.DMatrix(matrix, feature_names=list(columns)))
    return {
        (item["incident_id"], item["service"]): float(value)
        for item, value in zip(records, values, strict=True)
    }


def _oof_ablation(
    records: list[dict],
    rankings: dict[str, list[dict]],
    columns: tuple[str, ...],
) -> tuple[dict[str, list[dict]], dict]:
    predictions = {seed: {} for seed in SEEDS}
    provenance = []
    for held_out in RE1:
        train = [item for item in records if item["dataset"] != held_out]
        test = [item for item in records if item["dataset"] == held_out]
        train_incidents = {item["incident_id"] for item in train}
        test_incidents = {item["incident_id"] for item in test}
        if train_incidents & test_incidents:
            raise ValueError("OOF incident leakage")
        for seed in SEEDS:
            model = _fit_ablation(train, columns, seed)
            predictions[seed].update(_predict(model, test, columns))
        provenance.append({
            "held_out": held_out,
            "train_datasets": [name for name in RE1 if name != held_out],
            "train_incidents": len(train_incidents),
            "test_incidents": len(test_incidents),
            "incident_ids_disjoint": True,
            "external_cases_used": 0,
        })
    ensemble = {
        key: float(np.mean([predictions[seed][key] for seed in SEEDS]))
        for key in predictions[SEEDS[0]]
    }
    reranked = rerank_top3(rankings, ensemble)
    return reranked, {"folds": provenance, "seeds": list(SEEDS)}


def _rank_values(rankings: dict[str, list[dict]], incidents: list[str]) -> list[int]:
    return [
        next(int(item["rank"]) for item in rankings[incident] if int(item["label"]) == 1)
        for incident in incidents
    ]


def _by_dataset(
    rankings: dict[str, list[dict]],
    ids: dict[str, list[str]],
    datasets: tuple[str, ...],
) -> dict:
    return {
        dataset: extended_metrics(subset_rankings(rankings, ids[dataset]))
        for dataset in datasets
    }


def _assert_ranking_invariants(
    before: dict[str, list[dict]], after: dict[str, list[dict]]
) -> dict:
    membership_mismatches = []
    tail_mismatches = []
    for incident in sorted(before):
        original = sorted(before[incident], key=lambda item: int(item["rank"]))
        final = sorted(after[incident], key=lambda item: int(item["rank"]))
        if {item["service"] for item in original[:TOP_K]} != {
            item["service"] for item in final[:TOP_K]
        }:
            membership_mismatches.append(incident)
        if [item["service"] for item in original[TOP_K:]] != [
            item["service"] for item in final[TOP_K:]
        ]:
            tail_mismatches.append(incident)
    return {
        "top3_membership_equal": not membership_mismatches,
        "tail_relative_order_identical": not tail_mismatches,
        "top3_membership_mismatches": membership_mismatches,
        "tail_order_mismatches": tail_mismatches,
    }


def _verify_m10c_artifacts(root: Path) -> dict:
    manifest = json.loads((root / "ml/models/m10c-v2/integrity-manifest.json").read_text())
    actual = {
        name: sha256_file(root / "ml/models/m10c-v2" / name)
        for name in manifest["model_artifacts"]
    }
    mismatches = {
        name: {"expected": manifest["model_artifacts"][name], "actual": actual[name]}
        for name in actual
        if actual[name] != manifest["model_artifacts"][name]
    }
    return {
        "ok": not mismatches,
        "checked_files": len(actual),
        "mismatches": mismatches,
        "selected_model_sha256": actual["m10c-core-v2.json"],
    }


def _verify_model_hashes(model_dir: Path) -> dict:
    actual = {
        name: sha256_file(model_dir / name) for name in EXPECTED_MODEL_HASHES
    }
    mismatches = {
        name: {"expected": EXPECTED_MODEL_HASHES[name], "actual": actual[name]}
        for name in actual
        if actual[name] != EXPECTED_MODEL_HASHES[name]
    }
    return {"ok": not mismatches, "expected": EXPECTED_MODEL_HASHES, "actual": actual, "mismatches": mismatches}


def _feature_importance(models: list[xgb.Booster]) -> dict:
    per_seed = []
    for seed, model in zip(SEEDS, models, strict=True):
        gain = model.get_score(importance_type="total_gain")
        per_seed.append({
            "seed": seed,
            "total_gain": {name: float(gain.get(name, 0.0)) for name in RERANKER_FEATURES},
        })
    summary = {}
    for name in RERANKER_FEATURES:
        values = np.asarray([item["total_gain"][name] for item in per_seed], dtype=float)
        summary[name] = {"mean_total_gain": float(np.mean(values)), "std_total_gain": float(np.std(values))}
    groups = {
        "metric_evidence": ("component_MetricSupport",),
        "trace_evidence": ("component_TraceLocalSupport", "component_DependencyWaitSupport"),
        "topology_evidence": ("component_PropagationSupport", "component_TopologySupport"),
        "coverage_ood": ("component_CoverageSupport", "component_OODPenalty"),
        "cross_evidence": ("component_ContradictionEvidence", "component_ExpertAgreement", "support_score"),
        "base_ranking_context": RANKING_CONTEXT_FEATURES,
    }
    grouped = {}
    for group, names in groups.items():
        values = np.asarray(
            [sum(item["total_gain"][name] for name in names) for item in per_seed], dtype=float
        )
        grouped[group] = {"mean_total_gain": float(np.mean(values)), "std_total_gain": float(np.std(values))}
    return {
        "importance_type": "predictive total_gain; not causal importance",
        "per_seed": per_seed,
        "feature_summary": summary,
        "group_summary": grouped,
        "trace_limitation": (
            "RE1 has insufficient trace evidence; cross-domain use of the trace modality is not established."
        ),
    }


def _assert_metrics(name: str, actual: dict, tolerance: float = 1e-12) -> None:
    expected = EXPECTED_METRICS[name]
    for metric, value in expected.items():
        if abs(float(actual[metric]) - value) > tolerance:
            raise ValueError(
                f"{name}.{metric} changed: expected {value}, got {actual[metric]}"
            )


def run(root: Path, m10c_artifacts: Path, m9b_truth_free: Path, model_dir: Path) -> dict:
    started = time.monotonic()
    frozen = verify_frozen(root)
    m10c_integrity = _verify_m10c_artifacts(root)
    model_integrity = _verify_model_hashes(model_dir)
    if not frozen["ok"] or not m10c_integrity["ok"] or not model_integrity["ok"]:
        raise ValueError("frozen M10A/M10B/M10C or reranker inputs changed")

    cases, rows, ids = load_rows(
        m10c_artifacts / "truth-free.jsonl",
        m10c_artifacts / "truth-free-seal.json",
        root / "external-data/rcaeval/cases.parquet",
    )
    case_by_id = {item["incident_id"]: item for item in cases}
    clean_rows = _sanitize_rows(rows, _legacy_vectors(m9b_truth_free))
    rows_by_incident = defaultdict(list)
    for row in clean_rows:
        rows_by_incident[row["incident_id"]].append(row)

    selected_columns = tuple(
        json.loads((root / "ml/models/m10c-v2/feature-schema.json").read_text())["selected_columns"]
    )
    development_ids = sum((ids[name] for name in RE1), [])
    external_ids = sum((ids[name] for name in EXTERNAL), [])

    development_rankings = oof_for_columns(rows, ids, selected_columns)
    metric_development, trace_development, _ = oof_experts(rows, ids)
    development_profiles = {}
    for held_out in RE1:
        train_ids = sum((ids[name] for name in RE1 if name != held_out), [])
        development_profiles.update(
            _profiles_for_incidents(
                ids[held_out],
                development_rankings,
                rows_by_incident,
                metric_development,
                trace_development,
                fit_ood_stats(clean_rows, train_ids),
            )
        )
    development_candidates = _candidate_records(
        development_profiles, development_rankings, case_by_id
    )

    ablation = {
        "base_ranking": {
            "columns": [],
            "metrics": extended_metrics(development_rankings),
            "note": "Frozen M10C system-OOF ranking; no reranker.",
        }
    }
    full_development = None
    full_provenance = None
    for name, columns in ABLATIONS.items():
        reranked, provenance = _oof_ablation(
            development_candidates, development_rankings, columns
        )
        metrics = extended_metrics(reranked)
        ablation[name] = {
            "columns": list(columns),
            "metrics": metrics,
            "paired_bootstrap_vs_base": paired_bootstrap(
                _rank_values(reranked, sorted(development_ids)),
                _rank_values(development_rankings, sorted(development_ids)),
                resamples=10_000,
                seed=SEED,
            ),
            "selection_use": "interpretability only; final promoted model unchanged",
        }
        if name == "full_evidence_aware":
            full_development = reranked
            full_provenance = provenance

    if full_development is None or full_provenance is None:
        raise AssertionError("full reranker ablation missing")
    development_base = extended_metrics(development_rankings)
    development_reranked = extended_metrics(full_development)
    _assert_metrics("development_base", development_base)
    _assert_metrics("development_reranked", development_reranked)

    models = load_frozen_models(model_dir)
    core_model = xgb.Booster()
    core_model.load_model(root / "ml/models/m10c-v2/m10c-core-v2.json")
    metric_model = xgb.Booster()
    metric_model.load_model(root / "ml/models/m10c-v2/metric-expert.json")
    trace_model = xgb.Booster()
    trace_model.load_model(root / "ml/models/m10c-v2/trace-topology-expert.json")
    external_rankings = evaluate_model(core_model, rows, external_ids, selected_columns)[1]
    metric_external = evaluate_model(
        metric_model, rows, external_ids, METRIC_EXPERT_COLUMNS
    )[1]
    trace_external = evaluate_model(
        trace_model, rows, external_ids, TRACE_EXPERT_COLUMNS
    )[1]
    external_profiles = _profiles_for_incidents(
        external_ids,
        external_rankings,
        rows_by_incident,
        metric_external,
        trace_external,
        fit_ood_stats(clean_rows, development_ids),
    )
    external_candidates = _candidate_records(external_profiles, external_rankings, case_by_id)
    external_reranked_rankings = rerank_top3(
        external_rankings, predict_ensemble(models, external_candidates)
    )
    external_base = extended_metrics(external_rankings)
    external_reranked = extended_metrics(external_reranked_rankings)
    _assert_metrics("external_base", external_base)
    _assert_metrics("external_reranked", external_reranked)

    development_invariants = _assert_ranking_invariants(
        development_rankings, full_development
    )
    external_invariants = _assert_ranking_invariants(
        external_rankings, external_reranked_rankings
    )
    if not all(
        value
        for invariants in (development_invariants, external_invariants)
        for key, value in invariants.items()
        if key.endswith("equal") or key.endswith("identical")
    ):
        raise AssertionError("Top-3/tail invariant failed")

    result = {
        "version": "m10d-integration-v1",
        "component": "Evidence-Aware Top-3 Reranker",
        "verdicts": {
            "RELIABILITY_V2": "REJECTED",
            "DETERMINISTIC_VERIFIER": "INCONCLUSIVE",
            "EVIDENCE_RERANKER": "PROMOTED",
            "ACTIVE_PLANNER": "REJECTED",
            "M10D_INTEGRATION": "EVIDENCE_RERANKER_ONLY",
        },
        "architecture": [
            "M10C compact LambdaMART",
            "initial full ranking",
            "initial Top-3",
            "truth-free diagnostic evidence feature extraction",
            "frozen five-seed shallow XGBoost reranker",
            "reordered Top-3",
            "unchanged tail",
            "final ranking",
        ],
        "feature_schema": {
            "columns": list(RERANKER_FEATURES),
            "count": len(RERANKER_FEATURES),
            "service_identifier_use": "candidate matching key only; never a numeric model feature",
        },
        "data_protocol": {
            "development": "RE1 system-OOF; each held-out system is predicted by models fit on the other two",
            "external": "360 known external cases opened only after method freeze",
            "external_used_for_training": False,
            "external_used_for_feature_selection": False,
            "external_used_for_hyperparameter_selection": False,
            "external_used_for_model_selection": False,
            "external_used_for_final_non_degradation_guard": True,
            "promotion_basis": "positive system-OOF development result",
            "external_role": "post-hoc evaluation and pre-specified non-degradation guard",
        },
        "development": {
            "base": development_base,
            "reranked": development_reranked,
            "by_dataset_base": _by_dataset(development_rankings, ids, RE1),
            "by_dataset_reranked": _by_dataset(full_development, ids, RE1),
            "paired_bootstrap": paired_bootstrap(
                _rank_values(full_development, sorted(development_ids)),
                _rank_values(development_rankings, sorted(development_ids)),
                resamples=10_000,
                seed=SEED,
            ),
            "oof_provenance": full_provenance,
        },
        "external_post_freeze": {
            "base": external_base,
            "reranked": external_reranked,
            "by_dataset_base": _by_dataset(external_rankings, ids, EXTERNAL),
            "by_dataset_reranked": _by_dataset(external_reranked_rankings, ids, EXTERNAL),
            "paired_bootstrap": paired_bootstrap(
                _rank_values(external_reranked_rankings, sorted(external_ids)),
                _rank_values(external_rankings, sorted(external_ids)),
                resamples=10_000,
                seed=SEED,
            ),
        },
        "ablation": {
            "scope": "development system-OOF interpretability study only; not model reselection",
            "variants": ablation,
        },
        "feature_importance": _feature_importance(models),
        "invariants": {
            "development": development_invariants,
            "external": external_invariants,
        },
        "claims": {
            "supported": (
                "Evidence-aware Top-3 reranking improves the ordering of candidates already present in the initial Top-3."
            ),
            "not_claimed": [
                "candidate discovery improvement",
                "causal verification or causal proof",
                "calibrated probability",
            ],
        },
        "limitations": [
            "The reranker cannot recover a true root cause ranked below Top-3 by the base M10C ranker.",
            "RE1 has insufficient trace evidence, so trace-modality cross-domain transfer is not established.",
            "Feature total_gain is predictive importance and must not be interpreted causally.",
        ],
        "integrity": {
            "m10a_m10b": frozen,
            "m10c": m10c_integrity,
            "reranker_models": model_integrity,
            "source_research_commit": "e7a03959494bd89bb8df02fb51f5ce65e8bc6060",
        },
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
    save_json(model_dir / "evaluation.json", result)
    save_json(model_dir / "protocol.json", {
        "version": result["version"],
        "component": result["component"],
        "architecture": result["architecture"],
        "feature_schema": result["feature_schema"],
        "data_protocol": result["data_protocol"],
        "claims": result["claims"],
        "limitations": result["limitations"],
    })
    save_json(model_dir / "integrity-manifest.json", {
        "source_research_commit": result["integrity"]["source_research_commit"],
        "m10c_truth_free_sha256": sha256_file(m10c_artifacts / "truth-free.jsonl"),
        "m9b_truth_free_sha256": sha256_file(m9b_truth_free),
        "reranker_models": model_integrity["actual"],
        "frozen_inputs": {"m10a_m10b": frozen, "m10c": m10c_integrity},
        "protocol_sha256": sha256_file(model_dir / "protocol.json"),
        "evaluation_sha256": sha256_file(model_dir / "evaluation.json"),
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--m10c-artifacts", type=Path, default=Path("artifacts/m10c/m10c-v2"))
    parser.add_argument("--m9b-truth-free", type=Path, default=Path("artifacts/m9b/m9b-v1/truth-free.jsonl"))
    parser.add_argument("--models", type=Path, default=Path("ml/models/m10d-integration"))
    args = parser.parse_args()
    result = run(
        args.root.resolve(),
        args.m10c_artifacts.resolve(),
        args.m9b_truth_free.resolve(),
        args.models.resolve(),
    )
    print(json.dumps({
        "verdicts": result["verdicts"],
        "development": result["development"]["reranked"],
        "external": result["external_post_freeze"]["reranked"],
        "ablation": {
            name: value["metrics"]
            for name, value in result["ablation"]["variants"].items()
        },
        "runtime_seconds": result["runtime_seconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
