"""M10A statistical validation over the immutable M9B research core."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from .dataset import read_jsonl, sha256_file
from .m8b_experiment import INDEX_SHA256
from .m9b_experiment import (
    METRIC_EXTERNAL,
    METRIC_SYSTEM_HOLDOUTS,
    MULTISOURCE,
    MULTISOURCE_FOLDS,
    baseline_evaluation,
    ids_by_dataset,
    join_labels,
    metrics_from_combined,
)
from .m9b_model import _base_parameters, _dmatrix, evaluate_model, truth_ranks
from .m9b_schema import FEATURE_COLUMNS_M9B, METRIC_MODEL_COLUMNS, TOPOLOGY_COLUMNS
from .metrics import paired_bootstrap, rank_metrics
from .train import save_json

M9B_COMMIT = "b260dd6f22d5903a1313758d9dfad2b3402811ac"
SEED = 20260904
BOOTSTRAP_RESAMPLES = 10_000
ROBUSTNESS_SEEDS = (20260904, 20260917, 20261001, 20261015, 20261029)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("external-data/rcaeval"))
    parser.add_argument("--m9b-work", type=Path, default=Path("artifacts/m9b/m9b-v1"))
    parser.add_argument("--m9b-models", type=Path, default=Path("ml/models/m9b-v1"))
    parser.add_argument("--output", type=Path, default=Path("ml/models/m10a-freeze/evaluation.json"))
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        print(json.dumps(smoke(), indent=2, sort_keys=True))
        return
    run(args)


def smoke() -> dict:
    learned = [1, 1, 2, 1, 3]
    baseline = [2, 1, 3, 2, 3]
    paired = paired_bootstrap(learned, baseline, resamples=500, seed=SEED)
    full = full_denominator_metrics({"a": 1, "b": 2}, ["a", "b", "c"])
    summary = summarize_seed_values([.5, .6, .7], 99, resamples=500)
    if full["cases"] != 3 or full["missing_failures"] != 1 or paired["ac_at_1"]["difference"] <= 0:
        raise ValueError("M10A smoke failed")
    return {"paired": paired, "full_denominator": full, "seed_summary": summary,
            "research_mutation": "none"}


def run(args: argparse.Namespace) -> dict:
    immutable_before = immutable_hashes(args.m9b_models, args.docs)
    m9b = json.loads((args.m9b_models / "evaluation.json").read_text())
    records, cases, rows = load_rows(args)
    dataset_ids = ids_by_dataset(cases)

    metric_model = xgb.Booster()
    metric_model.load_model(args.m9b_models / "m9b-metric-lambdamart-v1.json")
    external_observable = sum((dataset_ids[name] for name in METRIC_EXTERNAL), [])
    _, metric_rankings = evaluate_model(metric_model, rows, external_observable, METRIC_MODEL_COLUMNS)

    fusion = fusion_validation(rows, dataset_ids, m9b, args.m9b_models)
    denominator = full_denominator_validation(cases, metric_rankings, m9b)
    baro = baro_validation(cases, metric_rankings, m9b)
    robustness = robustness_validation(rows, dataset_ids, m9b)
    importance = feature_group_stability(args.m9b_models)
    supporting = supporting_claim_statistics(rows, dataset_ids, metric_rankings, fusion)

    result = {
        "version": "m10a-freeze-v1",
        "m9b_commit": M9B_COMMIT,
        "protocol": {"bootstrap_resamples": BOOTSTRAP_RESAMPLES, "seed": SEED,
                     "robustness_seeds": list(ROBUSTNESS_SEEDS)},
        "source": m9b["source"],
        "truth_free_seal": m9b["truth_free_seal"],
        "coverage": m9b["coverage"],
        "fusion": fusion,
        "metric_denominators": denominator,
        "baro_comparison": baro,
        "robustness": robustness,
        "feature_group_stability": importance,
        "supporting_claim_statistics": supporting,
        "immutable_inputs_before": immutable_before,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_json(args.output, result)
    from .m10a_report import render_all
    render_all(result, m9b, args.docs)
    immutable_after = immutable_hashes(args.m9b_models, args.docs)
    if immutable_after != immutable_before:
        raise ValueError("M10A mutated a frozen M7-M9B input")
    manifest = {
        "version": result["version"], "implementation_parent_commit": M9B_COMMIT,
        "evaluation_sha256": sha256_file(args.output), "immutable_inputs": immutable_after,
        "truth_free_records": len(records), "truth_free_sha256": m9b["truth_free_seal"]["sha256"],
        "cases_index_sha256": INDEX_SHA256, "python": __import__("platform").python_version(),
        "numpy": np.__version__, "xgboost": xgb.__version__, "seed": SEED,
    }
    save_json(args.output.parent / "integrity-manifest.json", manifest)
    return result


def load_rows(args: argparse.Namespace) -> tuple[list[dict], list[dict], list[dict]]:
    index_path = args.data_dir / "cases.parquet"
    if sha256_file(index_path) != INDEX_SHA256:
        raise ValueError("pinned RCAEval index hash mismatch")
    truth_path = args.m9b_work / "truth-free.jsonl"
    seal = json.loads((args.m9b_work / "truth-free-seal.json").read_text())
    if sha256_file(truth_path) != seal["sha256"] or not seal.get("sealed_before_label_join"):
        raise ValueError("M9B truth-free seal mismatch")
    records = read_jsonl(truth_path)
    cases, rows = join_labels(records, pd.read_parquet(index_path), seal)
    return records, cases, rows


def fusion_validation(rows: list[dict], ids: dict[str, list[str]], m9b: dict, model_dir: Path) -> dict:
    all_rankings, metric_rankings = {}, {}
    for name, train_set, test_sets in MULTISOURCE_FOLDS:
        fold = m9b["multisource_study"]["folds"][name]
        selected = fold["tuning"]["selected"]
        all_model = xgb.Booster()
        all_model.load_model(model_dir / "multisource-folds" / f"{name}.json")
        metrics_model = fit_seed(rows, ids[train_set], METRIC_MODEL_COLUMNS,
                                 selected["hyperparameters"], selected["training_rounds"], SEED)
        for dataset in test_sets:
            _, all_values = evaluate_model(all_model, rows, ids[dataset], FEATURE_COLUMNS_M9B)
            _, metric_values = evaluate_model(metrics_model, rows, ids[dataset], METRIC_MODEL_COLUMNS)
            all_rankings.update(all_values)
            metric_rankings.update(metric_values)
    overall_ids = sum((ids[name] for name in MULTISOURCE), [])
    result = paired_result(all_rankings, metric_rankings, overall_ids)
    result["by_dataset"] = {}
    for dataset in MULTISOURCE:
        value = paired_result(all_rankings, metric_rankings, ids[dataset])
        value["inference"] = "descriptive_small_n" if len(ids[dataset]) < 30 else "paired_bootstrap"
        result["by_dataset"][dataset] = value
    expected = m9b["multisource_study"]["triggered"]["overall"]
    if not np.isclose(result["all_modalities"]["ac_at_1"], expected["ac_at_1"]):
        raise ValueError("frozen all-modality predictions do not reproduce M9B")
    return result


def paired_result(first: dict, second: dict, incident_ids: list[str]) -> dict:
    first_ranks = truth_ranks({value: first[value] for value in incident_ids})
    second_ranks = truth_ranks({value: second[value] for value in incident_ids})
    ordered = sorted(incident_ids)
    a = [first_ranks[value] for value in ordered]
    b = [second_ranks[value] for value in ordered]
    return {"cases": len(ordered), "all_modalities": {"cases": len(a), **rank_metrics(a)},
            "metrics_only": {"cases": len(b), **rank_metrics(b)},
            "paired_all_minus_metrics": paired_bootstrap(a, b, resamples=BOOTSTRAP_RESAMPLES, seed=SEED)}


def full_denominator_validation(cases: list[dict], rankings: dict, m9b: dict) -> dict:
    external = [case for case in cases if case["dataset"] in METRIC_EXTERNAL]
    rank_map = truth_ranks(rankings)
    conditional = {"overall": m9b["metric_study"]["external"]["overall"],
                   "by_dataset": m9b["metric_study"]["external"]["by_dataset"]}
    full = {"overall": full_denominator_metrics(rank_map, [case["external_case_id"] for case in external]),
            "by_dataset": {dataset: full_denominator_metrics(
                rank_map, [case["external_case_id"] for case in external if case["dataset"] == dataset])
                for dataset in METRIC_EXTERNAL}}
    return {"conditional_root_observable": conditional, "full_360": full,
            "rule": "root_not_observable is rank-zero failure in the full denominator"}


def full_denominator_metrics(rank_map: dict[str, int], incident_ids: list[str]) -> dict:
    ranks = [int(rank_map.get(value, 0)) for value in incident_ids]
    return {"cases": len(ranks), "missing_failures": sum(rank <= 0 for rank in ranks), **rank_metrics(ranks)}


def baro_validation(cases: list[dict], metric_rankings: dict, m9b: dict) -> dict:
    external = [case for case in cases if case["dataset"] in METRIC_EXTERNAL]
    expected_ids = {case["external_case_id"] for case in external}
    official = m9b["official_baselines"]["methods"]["baro"]
    baro_cases = official["cases"]
    baro_ids = {value["case"] for value in baro_cases}
    labels = {case["external_case_id"]: case["root_service"] for case in external}
    roots_match = all(value["root"] == labels[value["case"]] for value in baro_cases)
    comparable = (official["status"] == "success" and expected_ids == baro_ids
                  and len(baro_cases) == 360 and roots_match)
    audit = {"comparable": comparable, "m9b_granularity": "service",
             "baro_granularity": "official coarse service projection", "same_incident_ids": expected_ids == baro_ids,
             "same_root_labels": roots_match, "denominator": 360,
             "candidate_universe_note": "Candidate universes differ by method, but both produce service-level ranks for the same target and incidents."}
    if not comparable:
        return {"audit": audit, "comparison": None}
    metric_map = truth_ranks(metric_rankings)
    ordered = sorted(expected_ids)
    metric_ranks = [metric_map.get(value, 0) for value in ordered]
    baro_map = {value["case"]: int(value["rank"]) for value in baro_cases}
    baro_ranks = [baro_map[value] for value in ordered]
    return {"audit": audit, "comparison": {
        "m9b_metric": {"cases": 360, **rank_metrics(metric_ranks)},
        "baro": {"cases": 360, **rank_metrics(baro_ranks)},
        "paired_m9b_minus_baro": paired_bootstrap(metric_ranks, baro_ranks,
                                                    resamples=BOOTSTRAP_RESAMPLES, seed=SEED)}}


def robustness_validation(rows: list[dict], ids: dict[str, list[str]], m9b: dict) -> dict:
    metric_runs = {}
    for name, train_sets, test_set in METRIC_SYSTEM_HOLDOUTS:
        fold = m9b["metric_study"]["system_holdout"][name]
        selected = fold["tuning"]["selected"]
        train_ids = sum((ids[value] for value in train_sets), [])
        metric_runs[name] = seed_runs(rows, train_ids, ids[test_set], METRIC_MODEL_COLUMNS,
                                      selected["hyperparameters"], selected["training_rounds"])
    multisource_runs = {}
    for name, train_set, test_sets in MULTISOURCE_FOLDS:
        fold = m9b["multisource_study"]["folds"][name]
        selected = fold["tuning"]["selected"]
        multisource_runs[name] = seed_runs(rows, ids[train_set], ids[test_sets[0]], FEATURE_COLUMNS_M9B,
                                           selected["hyperparameters"], selected["training_rounds"])
    return {"method": "fixed folds/hyperparameters/rounds; varied deterministic XGBoost learner seed",
            "metric_re1_system_holdout": summarize_runs(metric_runs),
            "multisource_re2_cross_system": summarize_runs(multisource_runs)}


def seed_runs(rows: list[dict], train_ids: list[str], test_ids: list[str], columns: tuple[str, ...],
              hyperparameters: dict, rounds: int) -> list[dict]:
    result = []
    for seed in ROBUSTNESS_SEEDS:
        model = fit_seed(rows, train_ids, columns, hyperparameters, rounds, seed)
        metrics, _ = evaluate_model(model, rows, test_ids, columns)
        result.append({"seed": seed, "cases": metrics["cases"], "ac_at_1": metrics["ac_at_1"], "mrr": metrics["mrr"]})
    return result


def fit_seed(rows: list[dict], incident_ids: list[str], columns: tuple[str, ...], hyperparameters: dict,
             rounds: int, seed: int) -> xgb.Booster:
    data = _dmatrix(rows, incident_ids, columns, labels=True)[0]
    return xgb.train({**_base_parameters(), **hyperparameters, "seed": seed}, data,
                     num_boost_round=rounds, verbose_eval=False)


def summarize_runs(folds: dict[str, list[dict]]) -> dict:
    by_fold = {name: {"runs": values,
                      "ac_at_1": summarize_seed_values([value["ac_at_1"] for value in values], SEED),
                      "mrr": summarize_seed_values([value["mrr"] for value in values], SEED + 1)}
               for name, values in folds.items()}
    by_seed = []
    for seed in ROBUSTNESS_SEEDS:
        values = [next(value for value in fold if value["seed"] == seed) for fold in folds.values()]
        by_seed.append({"seed": seed, "ac_at_1": statistics.mean(value["ac_at_1"] for value in values),
                        "mrr": statistics.mean(value["mrr"] for value in values)})
    return {"by_fold": by_fold, "across_folds_by_seed": by_seed,
            "overall_ac_at_1": summarize_seed_values([value["ac_at_1"] for value in by_seed], SEED + 2),
            "overall_mrr": summarize_seed_values([value["mrr"] for value in by_seed], SEED + 3)}


def summarize_seed_values(values: list[float], seed: int, resamples: int = BOOTSTRAP_RESAMPLES) -> dict:
    rng = random.Random(seed)
    means = sorted(statistics.mean(values[rng.randrange(len(values))] for _ in values) for _ in range(resamples))
    return {"n_seeds": len(values), "mean": statistics.mean(values), "std": statistics.pstdev(values),
            "min": min(values), "max": max(values), "ci_low": percentile(means, .025),
            "ci_high": percentile(means, .975)}


def feature_group_stability(model_dir: Path) -> dict:
    groups = {
        "metric_models": [model_dir / "m9b-metric-lambdamart-v1.json",
                          *sorted((model_dir / "metric-holdouts").glob("*.json"))],
        "multisource_models": sorted((model_dir / "multisource-folds").glob("*.json")),
    }
    result = {}
    for category, paths in groups.items():
        models = {}
        for path in paths:
            model = xgb.Booster(); model.load_model(path)
            raw = model.get_score(importance_type="total_gain")
            totals = {name: 0.0 for name in ("cpu", "memory", "disk", "socket", "workload", "error",
                                                  "latency", "trace", "topology", "cross_family")}
            for feature, gain in raw.items():
                totals[feature_group(feature)] += float(gain)
            denominator = sum(totals.values()) or 1.0
            models[path.name] = {name: value / denominator for name, value in totals.items()}
        summary = {}
        for group in next(iter(models.values())):
            values = [model[group] for model in models.values()]
            present = sum(value > 0 for value in values) / len(values)
            spread = max(values) - min(values)
            status = ("stable_important" if present == 1 and statistics.mean(values) >= .05 and spread < .25
                      else "domain_dependent" if present > 0 and (present < 1 or spread >= .25)
                      else "low_or_unused")
            summary[group] = {"mean_share": statistics.mean(values), "min_share": min(values),
                              "max_share": max(values), "present_fraction": present, "status": status}
        result[category] = {"models": models, "summary": summary}
    return result


def feature_group(feature: str) -> str:
    if feature in TOPOLOGY_COLUMNS:
        return "topology"
    if feature == "has_trace" or feature.startswith("trace_"):
        return "trace"
    prefixes = (("metric_cpu_", "cpu"), ("metric_memory_", "memory"),
                ("metric_disk_io_", "disk"), ("metric_socket_", "socket"),
                ("metric_workload_", "workload"), ("metric_error_", "error"))
    for prefix, group in prefixes:
        if feature.startswith(prefix):
            return group
    if feature.startswith(("metric_latency_p50_", "metric_latency_p90_")):
        return "latency"
    return "cross_family"


def supporting_claim_statistics(rows: list[dict], ids: dict[str, list[str]], metric_rankings: dict,
                                fusion: dict) -> dict:
    primary_ids = sum((ids[name] for name in MULTISOURCE), [])
    primary_metrics, primary_rankings = baseline_evaluation(rows, primary_ids)
    metric_ranks = truth_ranks({value: metric_rankings[value] for value in primary_ids})
    trace_ranks = truth_ranks(primary_rankings["soft_hybrid_v1"])
    ordered = sorted(primary_ids)
    metric_vs_trace = paired_bootstrap([metric_ranks[value] for value in ordered],
                                       [trace_ranks[value] for value in ordered],
                                       resamples=BOOTSTRAP_RESAMPLES, seed=SEED)
    external_ids = sum((ids[name] for name in METRIC_EXTERNAL), [])
    _, heuristic_rankings = baseline_evaluation(rows, external_ids)
    heuristic_ranks = truth_ranks(heuristic_rankings["metric_max_shift"])
    ordered_external = sorted(external_ids)
    learned_vs_heuristic = paired_bootstrap([truth_ranks(metric_rankings)[value] for value in ordered_external],
                                            [heuristic_ranks[value] for value in ordered_external],
                                            resamples=BOOTSTRAP_RESAMPLES, seed=SEED + 1)
    re3_ids = ids["RE3-OB"] + ids["RE3-TT"]
    re3_metric = truth_ranks({value: metric_rankings[value] for value in re3_ids})
    re3_trace = truth_ranks({value: primary_rankings["soft_hybrid_v1"][value] for value in re3_ids})
    ordered_re3 = sorted(re3_ids)
    return {
        "metric_vs_trace_216": {"metric": {"cases": len(ordered), **rank_metrics(metric_ranks.values())},
                                "trace": primary_metrics["soft_hybrid_v1"], "paired": metric_vs_trace},
        "learned_metric_vs_max_shift_336": {
            "learned": {"cases": len(ordered_external), **rank_metrics(truth_ranks(metric_rankings).values())},
            "heuristic": {"cases": len(ordered_external), **rank_metrics(heuristic_ranks.values())},
            "paired": learned_vs_heuristic},
        "code_fault_metric_vs_trace_36": {
            "metric": {"cases": len(ordered_re3), **rank_metrics(re3_metric.values())},
            "trace": {"cases": len(ordered_re3), **rank_metrics(re3_trace.values())},
            "paired": paired_bootstrap([re3_metric[value] for value in ordered_re3],
                                         [re3_trace[value] for value in ordered_re3],
                                         resamples=BOOTSTRAP_RESAMPLES, seed=SEED + 2)},
        "fusion_reference": fusion["paired_all_minus_metrics"],
    }


def immutable_hashes(model_dir: Path, docs: Path) -> dict[str, str]:
    paths = sorted(model_dir.glob("**/*"))
    paths += sorted(path for path in docs.glob("m[789]*.md") if path.is_file())
    paths.append(docs / "rca-v1.md")
    return {str(path): sha256_file(path) for path in paths if path.is_file()}


def percentile(values: list[float], fraction: float) -> float:
    return values[round((len(values) - 1) * fraction)]


if __name__ == "__main__":
    main()
