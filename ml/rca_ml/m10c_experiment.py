"""Bounded end-to-end evaluation for M10C Robust RCA Core v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from .dataset import read_jsonl, sha256_file
from .m8b_experiment import INDEX_SHA256, RCAEVAL_REVISION, normalize_root
from .m9b_model import (
    _base_parameters, _dmatrix, evaluate_model, fit_fixed, incident_split,
    metrics_for_rankings, predict_rankings,
)
from .m9b_experiment import join_labels as join_m9b_labels
from .m9b_schema import METRIC_MODEL_COLUMNS as M9B_METRIC_COLUMNS
from .metrics import paired_bootstrap
from .m10c_fusion import META_COLUMNS, build_meta_rows, simple_fusion
from .m10c_integrity import verify_frozen
from .m10c_schema import FEATURE_COLUMNS_M10C, METRIC_EXPERT_COLUMNS, TRACE_EXPERT_COLUMNS
from .m10c_uncertainty import (
    assert_disjoint_partitions, calibrate_abstention, evaluate_abstention,
    evaluate_conformal, reliability_record,
)
from .train import save_json

SEED = 20260905
SEEDS = (20260905, 20260906, 20260907)
ROUNDS = 12
HP = {"max_depth": 3, "eta": .1, "min_child_weight": 1, "subsample": .8, "colsample_bytree": .8}
RE1 = ("RE1-OB", "RE1-SS", "RE1-TT")
EXTERNAL = ("RE2-OB", "RE2-SS", "RE2-TT", "RE3-OB", "RE3-SS", "RE3-TT")
FROZEN = {"ac_at_1": .7638888888888888, "ac_at_3": .8972222222222223,
          "mrr": .8358796296296297, "features": 253, "root_observable": 336}


def extended_metrics(rankings: dict[str, list[dict]]) -> dict:
    result = metrics_for_rankings(rankings)
    ranks = [next(item["rank"] for item in ranking if item["label"] == 1)
             for ranking in rankings.values()]
    result["ac_at_2"] = sum(rank <= 2 for rank in ranks) / len(ranks) if ranks else 0.0
    return result


def load_rows(truth_free: Path, seal_path: Path, index_path: Path) -> tuple[list[dict], list[dict], dict[str, list[str]]]:
    seal = json.loads(seal_path.read_text())
    if sha256_file(truth_free) != seal["sha256"] or not seal.get("sealed_before_label_join"):
        raise ValueError("M10C truth-free seal mismatch")
    records = read_jsonl(truth_free)
    index = pd.read_parquet(index_path)
    truth = {str(row.case): row for row in index.itertuples(index=False)}
    cases, rows, ids = [], [], defaultdict(list)
    for record in records:
        label = truth[record["external_case_id"]]
        dataset = str(label.dataset); root = normalize_root(str(label.root_cause_service), dataset)
        candidates = record["features"]["candidate_services"]
        ids[dataset].append(record["external_case_id"])
        cases.append({"incident_id": record["external_case_id"], "dataset": dataset,
                      "system": str(label.system), "fault": str(label.fault), "root": root,
                      "root_observable": root in candidates, "candidate_count": len(candidates)})
        for item in record["features"]["services"]:
            rows.append({"incident_id": record["external_case_id"], "dataset": dataset,
                         "system": str(label.system), "service": item["service"],
                         "label": int(item["service"] == root), **item["vector"]})
    return cases, rows, dict(ids)


def fit_seed(rows: list[dict], ids: list[str], columns: tuple[str, ...], seed: int = SEED) -> xgb.Booster:
    data = _dmatrix(rows, ids, columns, labels=True)[0]
    return xgb.train({**_base_parameters(), **HP, "seed": seed}, data,
                     num_boost_round=ROUNDS, verbose_eval=False)


def evaluate_by_dataset(model: xgb.Booster, rows: list[dict], ids: dict[str, list[str]],
                        columns: tuple[str, ...]) -> tuple[dict, dict[str, list[dict]]]:
    rankings = {}; by_dataset = {}
    for dataset in EXTERNAL:
        metrics, values = evaluate_model(model, rows, ids[dataset], columns)
        by_dataset[dataset] = extended_metrics(values); rankings.update(values)
    return {"overall": extended_metrics(rankings), "by_dataset": by_dataset}, rankings


def feature_group(name: str) -> str:
    for token, group in (("cpu", "cpu"), ("latency", "latency"), ("memory", "memory"),
                         ("disk", "disk"), ("network", "network"),
                         ("traffic_rate", "workload"), ("workload_", "workload"),
                         ("trace_", "trace"), ("topology_", "topology"),
                         ("coverage_", "coverage")):
        if token in name: return group
    return "other_metrics"


def feature_stability(rows: list[dict], ids: dict[str, list[str]]) -> dict:
    observations = {name: [] for name in FEATURE_COLUMNS_M10C}
    fold_metrics = []
    for held_out in RE1:
        train_ids = sum((ids[value] for value in RE1 if value != held_out), [])
        test_ids = ids[held_out]
        for seed in SEEDS:
            model = fit_seed(rows, train_ids, FEATURE_COLUMNS_M10C, seed)
            baseline, rankings = evaluate_model(model, rows, test_ids, FEATURE_COLUMNS_M10C)
            data, _, groups, selected = _dmatrix(rows, test_ids, FEATURE_COLUMNS_M10C, labels=False)
            matrix = np.asarray([[float(row[name]) for name in FEATURE_COLUMNS_M10C] for row in selected], dtype=np.float32)
            gain = model.get_score(importance_type="total_gain")
            total_gain = sum(float(value) for value in gain.values()) or 1.0
            rng = np.random.default_rng(seed)
            for position, name in enumerate(FEATURE_COLUMNS_M10C):
                used = name in gain
                delta = 0.0
                if used:
                    shuffled = matrix.copy()
                    # Shuffle within each incident so case-level coverage constants cannot leak.
                    offset = 0
                    for size in groups:
                        shuffled[offset:offset + size, position] = rng.permutation(
                            shuffled[offset:offset + size, position])
                        offset += size
                    altered = xgb.DMatrix(shuffled, feature_names=list(FEATURE_COLUMNS_M10C))
                    altered.set_group(np.asarray(groups, dtype=np.uint32))
                    permuted = metrics_for_rankings(predict_rankings(model, selected, altered))
                    delta = baseline["mrr"] - permuted["mrr"]
                observations[name].append({"used": used,
                                           "normalized_total_gain": float(gain.get(name, 0)) / total_gain,
                                           "permutation_mrr_drop": delta})
            fold_metrics.append({"held_out": held_out, "seed": seed, **baseline})
    features = {}
    for name, values in observations.items():
        use_frequency = sum(item["used"] for item in values) / len(values)
        positive = sum(item["permutation_mrr_drop"] > 1e-12 for item in values) / len(values)
        structural = name.endswith("_has") or name.startswith(("coverage_", "topology_"))
        eligible = structural or (use_frequency >= .6 and positive >= .6)
        features[name] = {"group": feature_group(name), "use_frequency": use_frequency,
                          "mean_normalized_total_gain": float(np.mean([x["normalized_total_gain"] for x in values])),
                          "positive_permutation_fraction": positive,
                          "structural_exception": structural, "eligible": eligible}
    selected = tuple(name for name in FEATURE_COLUMNS_M10C if features[name]["eligible"])
    gate = compact_gate(rows, ids, selected)
    return {"models": len(fold_metrics), "seeds": list(SEEDS), "fold_results": fold_metrics,
            "features": features, "selected_columns": list(selected), "selected_count": len(selected),
            "candidate_schema_count": len(FEATURE_COLUMNS_M10C), "compact_gate": gate,
            "decision": "PROMOTE_STABILITY_SUBSET" if gate["passes"] else "REJECT_STABILITY_SUBSET_KEEP_90"}


def compact_gate(rows: list[dict], ids: dict[str, list[str]], selected: tuple[str, ...]) -> dict:
    if not selected:
        return {"passes": False, "reason": "no eligible features"}
    full, compact = [], []
    for held_out in RE1:
        train_ids = sum((ids[value] for value in RE1 if value != held_out), [])
        full_model = fit_seed(rows, train_ids, FEATURE_COLUMNS_M10C)
        compact_model = fit_seed(rows, train_ids, selected)
        full.append(evaluate_model(full_model, rows, ids[held_out], FEATURE_COLUMNS_M10C)[0])
        compact.append(evaluate_model(compact_model, rows, ids[held_out], selected)[0])
    full_ac = float(np.mean([x["ac_at_1"] for x in full])); compact_ac = float(np.mean([x["ac_at_1"] for x in compact]))
    full_mrr = float(np.mean([x["mrr"] for x in full])); compact_mrr = float(np.mean([x["mrr"] for x in compact]))
    return {"full": {"ac_at_1": full_ac, "mrr": full_mrr},
            "compact": {"ac_at_1": compact_ac, "mrr": compact_mrr},
            "delta_ac_at_1": compact_ac - full_ac, "delta_mrr": compact_mrr - full_mrr,
            "passes": compact_ac - full_ac >= -.015 and compact_mrr - full_mrr >= -.015}


def workload_validation(rows: list[dict], ids: dict[str, list[str]]) -> dict:
    without = tuple(name for name in FEATURE_COLUMNS_M10C if not name.startswith("workload_"))
    with_values, without_values = [], []
    for held_out in RE1:
        train_ids = sum((ids[value] for value in RE1 if value != held_out), [])
        with_model = fit_seed(rows, train_ids, FEATURE_COLUMNS_M10C)
        without_model = fit_seed(rows, train_ids, without)
        with_values.append(evaluate_model(with_model, rows, ids[held_out], FEATURE_COLUMNS_M10C)[0])
        without_values.append(evaluate_model(without_model, rows, ids[held_out], without)[0])
    summary = lambda values: {"ac_at_1": float(np.mean([x["ac_at_1"] for x in values])),
                              "mrr": float(np.mean([x["mrr"] for x in values]))}
    present, absent = summary(with_values), summary(without_values)
    return {"selection_data": "RE1 system holdouts only", "with_residuals": present,
            "without_residuals": absent, "delta_ac_at_1": present["ac_at_1"] - absent["ac_at_1"],
            "delta_mrr": present["mrr"] - absent["mrr"],
            "decision": "PROMOTE" if present["mrr"] > absent["mrr"] else "REJECT"}


def oof_experts(rows: list[dict], ids: dict[str, list[str]]) -> tuple[dict, dict, dict]:
    metric, trace, early = {}, {}, {}
    provenance = {}
    for held_out in RE1:
        train_ids = sum((ids[value] for value in RE1 if value != held_out), [])
        for columns, destination in ((METRIC_EXPERT_COLUMNS, metric),
                                     (TRACE_EXPERT_COLUMNS, trace),
                                     (FEATURE_COLUMNS_M10C, early)):
            model = fit_seed(rows, train_ids, columns)
            destination.update(evaluate_model(model, rows, ids[held_out], columns)[1])
        for incident in ids[held_out]: provenance[incident] = train_ids
    if set(metric) != set(trace) or any(incident in provenance[incident] for incident in provenance):
        raise ValueError("OOF expert isolation failed")
    return metric, trace, early


def oof_for_columns(rows: list[dict], ids: dict[str, list[str]], columns: tuple[str, ...]) -> dict:
    rankings = {}
    for held_out in RE1:
        train_ids = sum((ids[value] for value in RE1 if value != held_out), [])
        model = fit_seed(rows, train_ids, columns)
        rankings.update(evaluate_model(model, rows, ids[held_out], columns)[1])
    return rankings


def subset_rankings(rankings: dict, ids: list[str]) -> dict:
    return {incident: rankings[incident] for incident in ids}


def fusion_study(rows: list[dict], ids: dict[str, list[str]], fit_ids_by_dataset: dict[str, list[str]],
                 calibration_ids: list[str], test_ids: list[str], compact_columns: tuple[str, ...],
                 model_dir: Path) -> tuple[dict, dict, dict]:
    metric_oof, trace_oof, _ = oof_experts(rows, fit_ids_by_dataset)
    fit_ids = sorted(metric_oof)
    meta_rows = build_meta_rows(metric_oof, trace_oof, rows)
    meta_model = fit_seed(meta_rows, fit_ids, META_COLUMNS)

    metric_model = fit_seed(rows, fit_ids, METRIC_EXPERT_COLUMNS)
    trace_model = fit_seed(rows, fit_ids, TRACE_EXPERT_COLUMNS)
    early_model = fit_seed(rows, fit_ids, FEATURE_COLUMNS_M10C)
    compact_model = fit_seed(rows, fit_ids, compact_columns)
    metric_calibration = evaluate_model(metric_model, rows, calibration_ids, METRIC_EXPERT_COLUMNS)[1]
    trace_calibration = evaluate_model(trace_model, rows, calibration_ids, TRACE_EXPERT_COLUMNS)[1]
    early_calibration = evaluate_model(early_model, rows, calibration_ids, FEATURE_COLUMNS_M10C)[1]
    compact_calibration = evaluate_model(compact_model, rows, calibration_ids, compact_columns)[1]
    calibration_meta_rows = build_meta_rows(metric_calibration, trace_calibration, rows)
    stacked_calibration = evaluate_model(meta_model, calibration_meta_rows, calibration_ids, META_COLUMNS)[1]
    validation = {
        "compact_stability": extended_metrics(compact_calibration),
        "early_fusion": extended_metrics(early_calibration),
        "rank_average": extended_metrics(simple_fusion(metric_calibration, trace_calibration, "rank_average")),
        "rrf": extended_metrics(simple_fusion(metric_calibration, trace_calibration, "rrf")),
        "stacked_lambdamart": extended_metrics(stacked_calibration),
    }
    complexity = {"rank_average": 0, "rrf": 1, "compact_stability": 2,
                  "early_fusion": 3, "stacked_lambdamart": 4}
    selected = sorted(validation, key=lambda name: (-validation[name]["mrr"], -validation[name]["ac_at_1"], complexity[name]))[0]

    metric_test = evaluate_model(metric_model, rows, test_ids, METRIC_EXPERT_COLUMNS)[1]
    trace_test = evaluate_model(trace_model, rows, test_ids, TRACE_EXPERT_COLUMNS)[1]
    early_test = evaluate_model(early_model, rows, test_ids, FEATURE_COLUMNS_M10C)[1]
    compact_test = evaluate_model(compact_model, rows, test_ids, compact_columns)[1]
    test_meta_rows = build_meta_rows(metric_test, trace_test, rows)
    stacked_test = evaluate_model(meta_model, test_meta_rows, test_ids, META_COLUMNS)[1]
    test_rankings = {
        "compact_stability": compact_test,
        "early_fusion": early_test,
        "rank_average": simple_fusion(metric_test, trace_test, "rank_average"),
        "rrf": simple_fusion(metric_test, trace_test, "rrf"),
        "stacked_lambdamart": stacked_test,
    }
    final = {name: extended_metrics(value) for name, value in test_rankings.items()}
    selected_by_dataset = {
        dataset: extended_metrics(subset_rankings(test_rankings[selected], ids[dataset]))
        for dataset in EXTERNAL
    }
    calibration_rankings = {
        "compact_stability": compact_calibration,
        "early_fusion": early_calibration,
        "rank_average": simple_fusion(metric_calibration, trace_calibration, "rank_average"),
        "rrf": simple_fusion(metric_calibration, trace_calibration, "rrf"),
        "stacked_lambdamart": stacked_calibration,
    }
    stress = {}
    conditions = ("complete", "metrics_missing", "traces_missing", "topology_missing",
                  "trace_spans_30pct_removed", "trace_spans_50pct_removed",
                  "cpu_family_missing", "cpu_latency_families_missing")
    for condition in conditions:
        altered = rows if condition == "complete" else masked_rows(rows, condition)
        if selected == "compact_stability":
            ranking = evaluate_model(compact_model, altered, test_ids, compact_columns)[1]
        elif selected == "early_fusion":
            ranking = evaluate_model(early_model, altered, test_ids, FEATURE_COLUMNS_M10C)[1]
        else:
            metric_values = evaluate_model(metric_model, altered, test_ids, METRIC_EXPERT_COLUMNS)[1]
            trace_values = evaluate_model(trace_model, altered, test_ids, TRACE_EXPERT_COLUMNS)[1]
            if selected in {"rank_average", "rrf"}:
                ranking = simple_fusion(metric_values, trace_values, selected)
            else:
                altered_meta = build_meta_rows(metric_values, trace_values, altered)
                ranking = evaluate_model(final_meta, altered_meta, test_ids, META_COLUMNS)[1]
        stress[condition] = extended_metrics(ranking)
    model_dir.mkdir(parents=True, exist_ok=True)
    persisted = {
        "metric-expert.json": metric_model,
        "trace-topology-expert.json": trace_model,
        "early-fusion.json": early_model,
        "compact-stability.json": compact_model,
        "stacked-meta-ranker.json": meta_model,
    }
    for name, fitted in persisted.items():
        fitted.save_model(model_dir / name)
    selected_model = {
        "compact_stability": compact_model,
        "early_fusion": early_model,
        "stacked_lambdamart": meta_model,
    }.get(selected)
    if selected_model is not None:
        selected_model.save_model(model_dir / "m10c-core-v2.json")
    return {"oof_incidents": len(metric_oof), "meta_train_incidents": len(fit_ids),
            "selection_incidents": len(calibration_ids), "validation": validation,
            "selection_rule": "MRR, then AC@1, then simpler method", "selected": selected,
            "final_360": final, "selected_by_dataset": selected_by_dataset,
            "selected_missingness_stress": stress}, test_rankings[selected], calibration_rankings[selected]


def masked_rows(rows: list[dict], condition: str) -> list[dict]:
    result = []
    for original in rows:
        row = dict(original)
        if condition == "metrics_missing":
            prefixes = ("metric_", "workload_"); attenuation = 0
        elif condition == "traces_missing":
            prefixes = ("trace_",); attenuation = 0
        elif condition == "topology_missing":
            prefixes = ("topology_",); attenuation = 0
        elif condition in {"trace_spans_30pct_removed", "trace_spans_50pct_removed"}:
            prefixes = ("trace_",); attenuation = .7 if "30pct" in condition else .5
        elif condition == "cpu_family_missing":
            prefixes = ("metric_cpu_",); attenuation = 0
        elif condition == "cpu_latency_families_missing":
            prefixes = ("metric_cpu_", "metric_latency_"); attenuation = 0
        else: raise ValueError(condition)
        for name in FEATURE_COLUMNS_M10C:
            if name.startswith(prefixes): row[name] = float(row[name]) * attenuation
        if condition == "metrics_missing": row["coverage_has_metrics"] = row["coverage_metric_family_ratio"] = 0.0
        if condition.startswith("trace_") or condition == "traces_missing": row["coverage_has_traces"] = 0.0
        if condition == "topology_missing": row["coverage_has_topology"] = 0.0
        result.append(row)
    return result


def stress_study(model: xgb.Booster, rows: list[dict], test_ids: list[str],
                 columns: tuple[str, ...]) -> dict:
    conditions = ("metrics_missing", "traces_missing", "topology_missing",
                  "trace_spans_30pct_removed", "trace_spans_50pct_removed",
                  "cpu_family_missing", "cpu_latency_families_missing")
    baseline = extended_metrics(evaluate_model(model, rows, test_ids, columns)[1])
    result = {"complete": baseline}
    for condition in conditions:
        result[condition] = extended_metrics(evaluate_model(model, masked_rows(rows, condition), test_ids, columns)[1])
    return result


def frozen_m10a_ranks(root: Path, index_path: Path, test_ids: list[str]) -> list[int]:
    work = root / "artifacts/m9b/m9b-v1"
    records = read_jsonl(work / "truth-free.jsonl")
    seal = json.loads((work / "truth-free-seal.json").read_text())
    cases, rows = join_m9b_labels(records, pd.read_parquet(index_path), seal)
    eligible = {case["external_case_id"] for case in cases if case["triggered_eligible"]}
    model = xgb.Booster(); model.load_model(root / "ml/models/m9b-v1/m9b-metric-lambdamart-v1.json")
    wanted = [incident for incident in test_ids if incident in eligible]
    rankings = evaluate_model(model, rows, wanted, M9B_METRIC_COLUMNS)[1]
    rank_map = {incident: next(item["rank"] for item in ranking if item["label"] == 1)
                for incident, ranking in rankings.items()}
    return [int(rank_map.get(incident, 0)) for incident in test_ids]


def grouped_metrics(cases: list[dict], rankings: dict[str, list[dict]]) -> dict:
    external_cases = [case for case in cases if case["dataset"] in EXTERNAL]
    result = {}
    for field in ("system", "fault"):
        values = {}
        for name in sorted({case[field] for case in external_cases}):
            wanted = [case["incident_id"] for case in external_cases if case[field] == name]
            values[name] = extended_metrics(subset_rankings(rankings, wanted))
        result[f"by_{field}"] = values
    return result


def ood_fit(rows: list[dict], train_ids: list[str]) -> dict:
    selected = [row for row in rows if row["incident_id"] in set(train_ids)]
    stats = {}
    for name in FEATURE_COLUMNS_M10C:
        values = np.asarray([float(row[name]) for row in selected])
        median = float(np.median(values)); iqr = float(np.quantile(values, .75) - np.quantile(values, .25))
        stats[name] = {"median": median, "scale": max(iqr, 1e-9),
                       "low": float(np.quantile(values, .01)), "high": float(np.quantile(values, .99))}
    return stats


def ood_score(row: dict, stats: dict) -> float:
    return sum(float(row[name]) < value["low"] or float(row[name]) > value["high"]
               for name, value in stats.items()) / len(stats)


def uncertainty_study(calibration_rankings: dict, test_rankings: dict, rows: list[dict],
                      train_ids: list[str]) -> dict:
    source = {(row["incident_id"], row["service"]): row for row in rows}
    stats = ood_fit(rows, train_ids)
    calibration_records = [reliability_record(ranking, source, incident,
                           ood_score(source[(incident, ranking[0]["service"])], stats))
                           for incident, ranking in calibration_rankings.items()]
    test_records = [reliability_record(ranking, source, incident,
                    ood_score(source[(incident, ranking[0]["service"])], stats))
                    for incident, ranking in test_rankings.items()]
    policies = {}
    for target in (.9, .95):
        policy = calibrate_abstention(calibration_records, target)
        policies[str(target)] = {"calibration": policy,
                                 "test": evaluate_abstention(test_records, policy["threshold"])}
    return {
        "ood": {"enters_ranking": False, "fit_incidents": len(train_ids),
                "test_mean_outlier_fraction": float(np.mean([
                    ood_score(source[(incident, ranking[0]["service"])], stats)
                    for incident, ranking in test_rankings.items()]))},
        "conformal": {str(target): evaluate_conformal(calibration_rankings, test_rankings, target)
                      for target in (.9, .95)},
        "abstention": policies,
    }


def run(root: Path, artifact_dir: Path, model_dir: Path) -> dict:
    started = time.monotonic()
    integrity = verify_frozen(root)
    if not integrity["ok"]: raise ValueError(f"frozen inputs changed: {integrity['mismatches']}")
    truth_free = artifact_dir / "truth-free.jsonl"; seal = artifact_dir / "truth-free-seal.json"
    cases, rows, ids = load_rows(truth_free, seal, root / "external-data/rcaeval/cases.parquet")
    train_ids = sum((ids[name] for name in RE1), []); test_ids = sum((ids[name] for name in EXTERNAL), [])
    fit_ids, calibration_ids = incident_split(train_ids, "m10c-final-calibration", 5)
    assert_disjoint_partitions(fit_ids, calibration_ids, test_ids)
    fit_set = set(fit_ids)
    fit_ids_by_dataset = {dataset: [incident for incident in ids[dataset] if incident in fit_set]
                          for dataset in RE1}
    if len(test_ids) != 360 or sum(case["root_observable"] for case in cases if case["dataset"] in EXTERNAL) != 360:
        raise ValueError("M10C requires 360 observable external roots")

    stability = feature_stability(rows, fit_ids_by_dataset)
    workload_validation_result = workload_validation(rows, fit_ids_by_dataset)
    final_columns = tuple(stability["selected_columns"]) if stability["compact_gate"]["passes"] else FEATURE_COLUMNS_M10C
    model = fit_seed(rows, fit_ids, final_columns)
    model_dir.mkdir(parents=True, exist_ok=True)
    main_result, main_rankings = evaluate_by_dataset(model, rows, ids, final_columns)
    workload_columns = tuple(name for name in final_columns if not name.startswith("workload_"))
    workload_model = fit_seed(rows, fit_ids, workload_columns)
    workload_result = evaluate_by_dataset(workload_model, rows, ids, workload_columns)[0]
    fusion, core_rankings, calibration_rankings = fusion_study(
        rows, ids, fit_ids_by_dataset, calibration_ids, test_ids, final_columns, model_dir)
    # Selection is frozen on RE1 validation; final external metrics never choose the method.
    core_name = fusion["selected"]
    uncertainty = uncertainty_study(calibration_rankings, core_rankings, rows, fit_ids)
    stress = fusion["selected_missingness_stress"]
    deployed_feature_count = len(final_columns) if core_name == "compact_stability" else len(FEATURE_COLUMNS_M10C)
    external = extended_metrics(core_rankings)
    ordered_test = sorted(test_ids)
    core_rank_map = {incident: next(item["rank"] for item in ranking if item["label"] == 1)
                     for incident, ranking in core_rankings.items()}
    core_ranks = [core_rank_map[incident] for incident in ordered_test]
    frozen_ranks = frozen_m10a_ranks(root, root / "external-data/rcaeval/cases.parquet", ordered_test)
    paired = paired_bootstrap(core_ranks, frozen_ranks, resamples=10000, seed=SEED)
    selective = uncertainty["abstention"]["0.9"]["test"]
    conformal90 = uncertainty["conformal"]["0.9"]; conformal95 = uncertainty["conformal"]["0.95"]
    minimum = {
        "ac_at_1": external["ac_at_1"] >= FROZEN["ac_at_1"] - .01,
        "mrr": external["mrr"] >= FROZEN["mrr"] - .01,
        "root_coverage": True,
        "compact_or_robust": deployed_feature_count <= 126,
        "selective_90": selective["selective_ac_at_1"] is not None and selective["selective_ac_at_1"] >= .9
                        and selective["coverage"] >= .2,
        "conformal": conformal90["empirical_coverage"] >= .88 and conformal95["empirical_coverage"] >= .93,
        "graceful_degradation": stress["traces_missing"]["mrr"] >= stress["complete"]["mrr"] - .15,
    }
    strong_a = external["ac_at_1"] >= FROZEN["ac_at_1"] + .03
    strong_b = (external["ac_at_1"] >= FROZEN["ac_at_1"] - .01 and deployed_feature_count <= 126
                and selective["coverage"] >= .6 and conformal90["mean_set_size"] <= 3)
    verdict = "PROMOTE_CORE_V2" if all(minimum.values()) and (strong_a or strong_b) else "KEEP_FROZEN_M10A_CORE"
    result = {
        "version": "m10c-core-v2", "verdict": verdict, "selected_core": core_name,
        "partitions": {"fit_cases": len(fit_ids), "calibration_cases": len(calibration_ids),
                       "test_cases": len(test_ids), "pairwise_disjoint": True},
        "frozen_reference": FROZEN, "root_coverage": {"observable": 360, "cases": 360},
        "feature_selection": stability, "final_feature_count": deployed_feature_count,
        "final_columns": list(final_columns), "compact_early_fusion": main_result,
        "workload_conditioning": {"validation": workload_validation_result,
                                  "external_descriptive": {"with_residuals": main_result,
                                                           "without_residuals": workload_result},
                                  "decision": workload_validation_result["decision"]},
        "fusion": fusion, "selected_core_metrics": external,
        "selected_core_breakdown": grouped_metrics(cases, core_rankings),
        "paired_vs_frozen_m10a": paired,
        "stress": stress, "uncertainty": uncertainty,
        "promotion_gates": {"minimum": minimum, "strong_accuracy": strong_a, "strong_robust": strong_b},
        "integrity": integrity, "runtime_seconds": time.monotonic() - started,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "xgboost": xgb.__version__,
                        "seed": SEED, "rcaeval_revision": RCAEVAL_REVISION, "cases_index_sha256": INDEX_SHA256},
        "rejected_hypotheses": [],
    }
    if stability["decision"].startswith("REJECT"): result["rejected_hypotheses"].append("strict stability-selected subset")
    if result["workload_conditioning"]["decision"] == "REJECT": result["rejected_hypotheses"].append("workload-conditioned residuals")
    for alternative in fusion["validation"]:
        if alternative != fusion["selected"]:
            result["rejected_hypotheses"].append(f"fusion alternative: {alternative}")
    if not minimum["selective_90"]:
        result["rejected_hypotheses"].append("90% selective Top-1 transfer at meaningful coverage")
    if verdict == "KEEP_FROZEN_M10A_CORE":
        result["rejected_hypotheses"].append("M10C replacement of the frozen M10A champion")
    save_json(model_dir / "evaluation.json", result)
    save_json(model_dir / "feature-schema.json", {"version": "m10c-v2-candidate",
              "candidate_columns": list(FEATURE_COLUMNS_M10C), "selected_columns": list(final_columns)})
    model_files = sorted(model_dir.glob("*.json"))
    model_hashes = {path.name: sha256_file(path) for path in model_files
                    if path.name not in {"evaluation.json", "integrity-manifest.json"}}
    save_json(model_dir / "integrity-manifest.json", {"truth_free_sha256": sha256_file(truth_free),
              "selected_model_sha256": sha256_file(model_dir / "m10c-core-v2.json"),
              "model_artifacts": model_hashes, "frozen": integrity})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/m10c/m10c-v2"))
    parser.add_argument("--models", type=Path, default=Path("ml/models/m10c-v2"))
    args = parser.parse_args()
    result = run(args.root.resolve(), args.artifacts, args.models)
    print(json.dumps({"verdict": result["verdict"], "selected_core": result["selected_core"],
                      "metrics": result["selected_core_metrics"], "runtime_seconds": result["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
