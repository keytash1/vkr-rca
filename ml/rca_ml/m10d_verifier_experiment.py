"""Leakage-safe evaluation of the M10D-B diagnostic evidence verifier."""

from __future__ import annotations

import argparse
import json
import platform
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from .dataset import read_jsonl, sha256_file
from .m10c_experiment import (
    EXTERNAL,
    RE1,
    extended_metrics,
    fit_seed,
    load_rows,
    oof_experts,
    oof_for_columns,
    subset_rankings,
)
from .m10c_integrity import verify_frozen
from .m10c_schema import FEATURE_COLUMNS_M10C, METRIC_EXPERT_COLUMNS, TRACE_EXPERT_COLUMNS
from .m10d_verifier import (
    COMPONENTS,
    STATUSES,
    build_evidence_profiles,
    calibrate_status_policy,
    evaluate_abstention,
    evaluate_statuses,
    fit_ood_stats,
    status_for,
)
from .m9b_model import evaluate_model, metrics_for_rankings
from .metrics import paired_bootstrap
from .train import save_json

SEED = 20260906
SEEDS = (20260906, 20260907, 20260908, 20260909, 20260910)
TOP_K = 3
LEARNED_COLUMNS = (
    *(f"component_{name}" for name in COMPONENTS),
    "support_score",
    "base_rank_percentile",
    "base_relative_score",
    "base_margin",
)


def _strip_ranking(ranking: list[dict]) -> list[dict]:
    return [{"service": item["service"], "rank": int(item["rank"]), "score": float(item["score"])}
            for item in ranking]


def _sanitize_rows(rows: list[dict], legacy: dict[tuple[str, str], dict]) -> list[dict]:
    result = []
    for source in rows:
        row = {"incident_id": source["incident_id"], "service": source["service"]}
        row.update({name: float(source.get(name, 0.0)) for name in FEATURE_COLUMNS_M10C})
        old = legacy.get((source["incident_id"], source["service"]), {})
        row.update({name: float(value) for name, value in old.items()
                    if name.startswith("trace_") or name == "has_trace"})
        result.append(row)
    return result


def _legacy_vectors(path: Path) -> dict[tuple[str, str], dict]:
    result = {}
    for record in read_jsonl(path):
        incident = record["external_case_id"]
        for item in record["features"]["services"]:
            result[(incident, item["service"])] = item["vector"]
    return result


def _profiles_for_incidents(
    incident_ids: list[str],
    rankings: dict[str, list[dict]],
    rows_by_incident: dict[str, list[dict]],
    metric_rankings: dict[str, list[dict]],
    trace_rankings: dict[str, list[dict]],
    ood_stats: dict,
    policy: dict | None = None,
) -> dict[str, list[dict]]:
    return {
        incident: build_evidence_profiles(
            rows_by_incident[incident],
            _strip_ranking(rankings[incident]),
            metric_ranking=_strip_ranking(metric_rankings[incident]),
            trace_ranking=_strip_ranking(trace_rankings[incident]),
            ood_stats=ood_stats,
            top_k=TOP_K,
            policy=policy,
        )
        for incident in incident_ids
    }


def _labeled_top1(profiles: dict[str, list[dict]], rankings: dict[str, list[dict]],
                  case_by_id: dict[str, dict]) -> list[dict]:
    result = []
    for incident in sorted(profiles):
        ranking = rankings[incident]
        top = profiles[incident][0]
        truth = next(item for item in ranking if int(item["label"]) == 1)
        result.append({
            "incident_id": incident,
            "dataset": case_by_id[incident]["dataset"],
            "system": case_by_id[incident]["system"],
            "correct": int(top["service"] == truth["service"]),
            "truth_rank": int(truth["rank"]),
            "truth_service": truth["service"],
            "service": top["service"],
            "components": top["components"],
            "support_score": top["support_score"],
            "profile": top,
        })
    return result


def _candidate_records(profiles: dict[str, list[dict]], rankings: dict[str, list[dict]],
                       case_by_id: dict[str, dict]) -> list[dict]:
    records = []
    for incident in sorted(profiles):
        ranking = sorted(rankings[incident], key=lambda item: int(item["rank"]))
        count = len(ranking)
        scores = [float(item["score"]) for item in ranking]
        low, high = min(scores), max(scores)
        scale = high - low
        margin = 1.0 if count == 1 else (scores[0] - scores[1]) / max(abs(scores[0]), abs(scores[1]), 1e-9)
        truth = next(item["service"] for item in ranking if int(item["label"]) == 1)
        for profile in profiles[incident]:
            records.append({
                "incident_id": incident,
                "dataset": case_by_id[incident]["dataset"],
                "system": case_by_id[incident]["system"],
                "service": profile["service"],
                "target": int(profile["service"] == truth),
                **{f"component_{name}": float(profile["components"][name]) for name in COMPONENTS},
                "support_score": float(profile["support_score"]),
                "base_rank_percentile": 1.0 if count == 1 else 1.0 - (profile["base_rank"] - 1) / (count - 1),
                "base_relative_score": .5 if scale <= 1e-12 else (profile["base_score"] - low) / scale,
                "base_margin": margin if profile["base_rank"] == 1 else 0.0,
            })
    return records


def _fit_learned(records: list[dict], seed: int) -> xgb.Booster:
    if not records or len({item["target"] for item in records}) < 2:
        raise ValueError("learned verifier requires positive and negative development candidates")
    matrix = np.asarray([[float(item[name]) for name in LEARNED_COLUMNS] for item in records], dtype=np.float32)
    target = np.asarray([int(item["target"]) for item in records], dtype=np.float32)
    data = xgb.DMatrix(matrix, label=target, feature_names=list(LEARNED_COLUMNS))
    return xgb.train({
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
    }, data, num_boost_round=24, verbose_eval=False)


def _predict_learned(model: xgb.Booster, records: list[dict]) -> dict[tuple[str, str], float]:
    matrix = np.asarray([[float(item[name]) for name in LEARNED_COLUMNS] for item in records], dtype=np.float32)
    data = xgb.DMatrix(matrix, feature_names=list(LEARNED_COLUMNS))
    values = model.predict(data)
    return {(item["incident_id"], item["service"]): float(value)
            for item, value in zip(records, values, strict=True)}


def _rerank(rankings: dict[str, list[dict]], predictions: dict[tuple[str, str], float]) -> dict[str, list[dict]]:
    result = {}
    for incident, original in rankings.items():
        ordered = sorted(original, key=lambda item: int(item["rank"]))
        head, tail = ordered[:TOP_K], ordered[TOP_K:]
        head = sorted(head, key=lambda item: (
            -predictions[(incident, item["service"])], int(item["rank"]), item["service"]
        ))
        reranked = [{**item, "verifier_score": predictions[(incident, item["service"])]}
                    for item in head] + [dict(item) for item in tail]
        for rank, item in enumerate(reranked, 1):
            item["rank"] = rank
        result[incident] = reranked
    return result


def _rank_values(rankings: dict[str, list[dict]], incidents: list[str]) -> list[int]:
    return [next(int(item["rank"]) for item in rankings[incident] if int(item["label"]) == 1)
            for incident in incidents]


def _seed_summary(values: list[dict]) -> dict:
    result = {"seeds": list(SEEDS), "runs": values}
    for metric in ("ac_at_1", "mrr"):
        numbers = np.asarray([item[metric] for item in values], dtype=float)
        result[metric] = {
            "mean": float(np.mean(numbers)), "std": float(np.std(numbers)),
            "min": float(np.min(numbers)), "max": float(np.max(numbers)),
        }
    return result


def _nested_status_and_abstention(records: list[dict]) -> tuple[dict, list[dict]]:
    annotated = []
    folds = []
    for held_out in RE1:
        train = [item for item in records if item["dataset"] != held_out]
        test = [dict(item) for item in records if item["dataset"] == held_out]
        policy = calibrate_status_policy(train)
        accepted = _select_acceptance(train, policy)
        for item in test:
            item["nested_status"] = status_for(item["components"], item["support_score"], policy)
        status_summary = _evaluate_annotated_statuses(test)
        abstention = _evaluate_annotated_abstention(test, accepted)
        folds.append({
            "held_out": held_out,
            "policy_fit_cases": len(train),
            "policy": policy,
            "status": status_summary,
            "abstention": abstention,
        })
        annotated.extend(test)
    return {
        "protocol": "nested RE1 system holdout; status and acceptance policies fit on the other two systems",
        "folds": folds,
        "overall_status": _evaluate_annotated_statuses(annotated),
        "overall_abstention": _evaluate_annotated_abstention(
            annotated, None, already_annotated=True
        ),
    }, annotated


def _evaluate_annotated_statuses(records: list[dict]) -> dict:
    count = len(records)
    verified = [item for item in records if item["nested_status"] == "VERIFIED"]
    contradicted = [item for item in records if item["nested_status"] == "CONTRADICTED"]
    return {
        "cases": count,
        "base_accuracy": float(np.mean([item["correct"] for item in records])),
        "verified_cases": len(verified),
        "verified_coverage": len(verified) / count,
        "verified_precision": float(np.mean([item["correct"] for item in verified])) if verified else 0.0,
        "contradicted_cases": len(contradicted),
        "contradicted_coverage": len(contradicted) / count,
        "contradicted_error_precision": float(np.mean([not item["correct"] for item in contradicted])) if contradicted else 0.0,
        "status_counts": {status: sum(item["nested_status"] == status for item in records) for status in STATUSES},
    }


def _select_acceptance(records: list[dict], policy: dict) -> list[str]:
    choices = [
        ["VERIFIED"],
        ["VERIFIED", "PARTIALLY_SUPPORTED"],
        ["VERIFIED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE"],
    ]
    feasible = []
    for statuses in choices:
        result = evaluate_abstention(records, policy, statuses)
        if result["selective_ac_at_1"] is not None and result["selective_ac_at_1"] >= .90:
            feasible.append((result["coverage"], -len(statuses), statuses))
    return max(feasible)[2] if feasible else ["VERIFIED"]


def _evaluate_annotated_abstention(records: list[dict], accepted: list[str] | None,
                                    already_annotated: bool = False) -> dict:
    if already_annotated:
        # Every record already carries the train-side decision via nested_accept.
        chosen = [item for item in records if item.get("nested_accept", False)]
    else:
        accepted_set = set(accepted or [])
        chosen = [item for item in records if item["nested_status"] in accepted_set]
        for item in records:
            item["nested_accept"] = item["nested_status"] in accepted_set
    return {
        "cases": len(records), "accepted": len(chosen),
        "coverage": len(chosen) / len(records) if records else 0.0,
        "selective_ac_at_1": float(np.mean([item["correct"] for item in chosen])) if chosen else None,
        "selective_mrr": float(np.mean([1 / item["truth_rank"] for item in chosen])) if chosen else None,
    }


def _by_dataset_status(records: list[dict], policy: dict) -> dict:
    result = {}
    for dataset in sorted({item["dataset"] for item in records}):
        selected = [item for item in records if item["dataset"] == dataset]
        result[dataset] = evaluate_statuses(selected, policy)
    return result


def _by_dataset_rankings(rankings: dict[str, list[dict]], ids: dict[str, list[str]], datasets: tuple[str, ...]) -> dict:
    return {dataset: extended_metrics(subset_rankings(rankings, ids[dataset])) for dataset in datasets}


def _synthetic_semantic_stress() -> dict:
    empty = {name: 0.0 for name in FEATURE_COLUMNS_M10C}
    def make(service: str, **values: float) -> dict:
        return {**empty, "incident_id": "synthetic", "service": service, **values}
    ordering = lambda names: [{"service": value, "rank": index + 1, "score": 1 / (index + 1)}
                              for index, value in enumerate(names)]
    local = [
        make("caller", coverage_has_traces=1, trace_median_downstream_wait_ratio=.95,
             trace_median_exclusive_ratio=.05, trace_local_evidence=.1),
        make("root", coverage_has_traces=1, trace_median_downstream_wait_ratio=.05,
             trace_median_exclusive_ratio=.95, trace_local_evidence=.9),
    ]
    a = build_evidence_profiles(local, ordering(["caller", "root"]), top_k=2)
    metric = [make("metric-root", coverage_has_metrics=1, coverage_metric_family_ratio=1 / 13,
                   metric_cpu_has=1, metric_cpu_max_shift=30,
                   metric_cpu_max_shift_percentile=1, metric_cpu_persistence=1)]
    b = build_evidence_profiles(metric, ordering(["metric-root"]))[0]
    topology = [make("candidate", coverage_has_topology=1, topology_active_trace_coverage=1,
                     trace_topology_precision=0, trace_topology_recall=0, trace_topology_f1=0,
                     trace_observed_anomaly_ratio=.8, trace_expected_affected_ratio=.2)]
    c = build_evidence_profiles(topology, ordering(["candidate"]))[0]
    return {
        "Synthetic-A-local-vs-propagated": {
            "pass": a[1]["components"]["TraceLocalSupport"] > a[0]["components"]["TraceLocalSupport"]
                    and a[0]["components"]["ContradictionEvidence"] > .5,
        },
        "Synthetic-B-metric-only": {
            "pass": b["components"]["MetricSupport"] > .8
                    and b["components"]["TraceLocalSupport"] == 0,
        },
        "Synthetic-C-topology-contradiction": {
            "pass": c["components"]["ContradictionEvidence"] > .5,
        },
    }


def _case_studies(records: list[dict], rows_by_incident: dict[str, list[dict]], policy: dict) -> list[dict]:
    enriched = []
    for item in records:
        value = dict(item)
        value["status"] = status_for(item["components"], item["support_score"], policy)
        row = next(row for row in rows_by_incident[item["incident_id"]] if row["service"] == item["service"])
        value["has_metrics"] = bool(row["coverage_has_metrics"])
        value["has_traces"] = bool(row["coverage_has_traces"])
        enriched.append(value)
    selectors = [
        ("correct strongly verified", lambda x: x["correct"] and x["status"] == "VERIFIED", True),
        ("correct weakly supported", lambda x: x["correct"] and x["status"] in {"PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE"}, False),
        ("wrong but contradicted", lambda x: not x["correct"] and x["status"] == "CONTRADICTED", True),
        ("wrong but falsely verified", lambda x: not x["correct"] and x["status"] == "VERIFIED", True),
        ("trace-missing correct", lambda x: x["correct"] and not x["has_traces"], True),
        ("metric-only candidate correct", lambda x: x["correct"] and x["has_metrics"] and not x["has_traces"], True),
    ]
    output = []
    for name, predicate, descending in selectors:
        matches = [item for item in enriched if predicate(item)]
        matches.sort(key=lambda item: item["support_score"], reverse=descending)
        if not matches:
            output.append({"case_study": name, "observed": False,
                           "note": "No exact case matched after the policy was frozen; no substitute was relabeled."})
            continue
        item = matches[0]
        output.append({
            "case_study": name, "observed": True,
            "incident_id": item["incident_id"], "dataset": item["dataset"],
            "predicted_service": item["service"], "truth_service": item["truth_service"],
            "truth_rank": item["truth_rank"], "status": item["status"],
            "support_score": item["support_score"], "components": item["components"],
            "contradictions": item["profile"]["contradictions"],
            "dominant_metric_families": item["profile"]["dominant_metric_families"],
            "claim_scope": "post-hoc evidence audit; not causal proof",
        })
    return output


def _failure_taxonomy(records: list[dict], rankings: dict[str, list[dict]],
                      profiles: dict[str, list[dict]], policy: dict) -> dict:
    wrong = [item for item in records if not item["correct"]]
    counts = defaultdict(int)
    for item in wrong:
        components = item["components"]
        status = status_for(components, item["support_score"], policy)
        if components["OODPenalty"] > .10:
            counts["domain_shift"] += 1
        top = profiles[item["incident_id"]]
        if len(top) > 1 and abs(top[0]["components"]["MetricSupport"] - top[1]["components"]["MetricSupport"]) < .10:
            counts["metric_ambiguity"] += 1
        if not all(item["profile"]["coverage_detail"][name]
                   for name in ("has_metrics", "has_traces", "has_topology")):
            counts["missing_modality"] += 1
        ordered = sorted(rankings[item["incident_id"]], key=lambda x: int(x["rank"]))
        if len(ordered) > 1 and abs(float(ordered[0]["score"]) - float(ordered[1]["score"])) < .05:
            counts["candidate_ambiguity"] += 1
        counts["ranking_error"] += 1
        if status == "VERIFIED":
            counts["confidence_error"] += 1
        if status != "CONTRADICTED":
            counts["verifier_contradiction_miss"] += 1
    counts["planner_bad_action"] = 0
    return {name: counts[name] for name in (
        "domain_shift", "metric_ambiguity", "missing_modality", "candidate_ambiguity",
        "ranking_error", "confidence_error", "verifier_contradiction_miss", "planner_bad_action",
    )}


def _verify_m10c_artifacts(root: Path) -> dict:
    manifest = json.loads((root / "ml/models/m10c-v2/integrity-manifest.json").read_text())
    actual = {
        name: sha256_file(root / "ml/models/m10c-v2" / name)
        for name in manifest["model_artifacts"]
    }
    mismatches = {name: {"expected": manifest["model_artifacts"][name], "actual": actual[name]}
                  for name in actual if actual[name] != manifest["model_artifacts"][name]}
    return {"ok": not mismatches, "checked_files": len(actual), "mismatches": mismatches,
            "selected_model_sha256": actual["m10c-core-v2.json"]}


def run(root: Path, m10c_artifacts: Path, m9b_truth_free: Path, model_dir: Path) -> dict:
    started = time.monotonic()
    frozen = verify_frozen(root)
    m10c_integrity = _verify_m10c_artifacts(root)
    if not frozen["ok"] or not m10c_integrity["ok"]:
        raise ValueError("frozen M10A/M10B/M10C inputs changed")
    cases, rows, ids = load_rows(
        m10c_artifacts / "truth-free.jsonl",
        m10c_artifacts / "truth-free-seal.json",
        root / "external-data/rcaeval/cases.parquet",
    )
    case_by_id = {item["incident_id"]: item for item in cases}
    legacy = _legacy_vectors(m9b_truth_free)
    clean_rows = _sanitize_rows(rows, legacy)
    rows_by_incident = defaultdict(list)
    for row in clean_rows:
        rows_by_incident[row["incident_id"]].append(row)

    selected_columns = tuple(json.loads((root / "ml/models/m10c-v2/feature-schema.json").read_text())["selected_columns"])
    development_ids = sum((ids[name] for name in RE1), [])
    external_ids = sum((ids[name] for name in EXTERNAL), [])

    # Development predictions are system-out-of-fold for the frozen M10C architecture.
    development_rankings = oof_for_columns(rows, ids, selected_columns)
    metric_development, trace_development, _ = oof_experts(rows, ids)
    development_profiles = {}
    for held_out in RE1:
        train_ids = sum((ids[name] for name in RE1 if name != held_out), [])
        stats = fit_ood_stats(clean_rows, train_ids)
        development_profiles.update(_profiles_for_incidents(
            ids[held_out], development_rankings, rows_by_incident,
            metric_development, trace_development, stats,
        ))
    development_top1 = _labeled_top1(development_profiles, development_rankings, case_by_id)
    nested, nested_records = _nested_status_and_abstention(development_top1)
    frozen_policy = calibrate_status_policy(development_top1)
    frozen_acceptance = _select_acceptance(development_top1, frozen_policy)

    # Clean candidate-level OOF learned verifier and separate reranking challenger.
    development_candidates = _candidate_records(development_profiles, development_rankings, case_by_id)
    predictions_by_seed = {seed: {} for seed in SEEDS}
    oof_provenance = []
    for held_out in RE1:
        train = [item for item in development_candidates if item["dataset"] != held_out]
        test = [item for item in development_candidates if item["dataset"] == held_out]
        train_incidents = {item["incident_id"] for item in train}
        test_incidents = {item["incident_id"] for item in test}
        if train_incidents & test_incidents:
            raise ValueError("verifier OOF split leakage")
        for seed in SEEDS:
            model = _fit_learned(train, seed)
            predictions_by_seed[seed].update(_predict_learned(model, test))
        oof_provenance.append({
            "held_out": held_out, "train_incidents": len(train_incidents),
            "test_incidents": len(test_incidents), "disjoint": True,
        })
    per_seed_rankings = {seed: _rerank(development_rankings, values)
                         for seed, values in predictions_by_seed.items()}
    per_seed_metrics = [{"seed": seed, **extended_metrics(per_seed_rankings[seed])} for seed in SEEDS]
    ensemble_predictions = {
        key: float(np.mean([predictions_by_seed[seed][key] for seed in SEEDS]))
        for key in predictions_by_seed[SEEDS[0]]
    }
    development_reranked = _rerank(development_rankings, ensemble_predictions)
    dev_order = sorted(development_ids)
    development_paired = paired_bootstrap(
        _rank_values(development_reranked, dev_order),
        _rank_values(development_rankings, dev_order),
        resamples=10_000,
        seed=SEED,
    )

    # Freeze policy/hyperparameters before the known external 360 are opened.
    model_dir.mkdir(parents=True, exist_ok=True)
    save_json(model_dir / "status-policy.json", {
        "version": "m10d-verifier-v1", "fit_partition": "RE1 only",
        "status_policy": frozen_policy, "accepted_statuses": frozen_acceptance,
        "top_k": TOP_K, "learned_columns": list(LEARNED_COLUMNS),
        "external_used_for_selection": False,
    })
    final_models = []
    for seed in SEEDS:
        model = _fit_learned(development_candidates, seed)
        model.save_model(model_dir / f"reranker-seed-{seed}.json")
        final_models.append(model)

    core_model = xgb.Booster(); core_model.load_model(root / "ml/models/m10c-v2/m10c-core-v2.json")
    metric_model = xgb.Booster(); metric_model.load_model(root / "ml/models/m10c-v2/metric-expert.json")
    trace_model = xgb.Booster(); trace_model.load_model(root / "ml/models/m10c-v2/trace-topology-expert.json")
    rank_started = time.perf_counter()
    external_rankings = evaluate_model(core_model, rows, external_ids, selected_columns)[1]
    rank_seconds = time.perf_counter() - rank_started
    metric_external = evaluate_model(metric_model, rows, external_ids, METRIC_EXPERT_COLUMNS)[1]
    trace_external = evaluate_model(trace_model, rows, external_ids, TRACE_EXPERT_COLUMNS)[1]
    external_stats = fit_ood_stats(clean_rows, development_ids)
    verifier_started = time.perf_counter()
    external_profiles = _profiles_for_incidents(
        external_ids, external_rankings, rows_by_incident, metric_external, trace_external,
        external_stats, frozen_policy,
    )
    verifier_seconds = time.perf_counter() - verifier_started
    external_top1 = _labeled_top1(external_profiles, external_rankings, case_by_id)
    external_status = evaluate_statuses(external_top1, frozen_policy)
    external_abstention = evaluate_abstention(external_top1, frozen_policy, frozen_acceptance)
    external_candidates = _candidate_records(external_profiles, external_rankings, case_by_id)
    learned_started = time.perf_counter()
    external_predictions_by_seed = [_predict_learned(model, external_candidates) for model in final_models]
    learned_seconds = time.perf_counter() - learned_started
    external_predictions = {
        key: float(np.mean([values[key] for values in external_predictions_by_seed]))
        for key in external_predictions_by_seed[0]
    }
    external_reranked = _rerank(external_rankings, external_predictions)
    external_per_seed = [
        {"seed": seed, **extended_metrics(_rerank(external_rankings, predictions))}
        for seed, predictions in zip(SEEDS, external_predictions_by_seed, strict=True)
    ]
    external_order = sorted(external_ids)
    external_paired = paired_bootstrap(
        _rank_values(external_reranked, external_order),
        _rank_values(external_rankings, external_order),
        resamples=10_000,
        seed=SEED,
    )

    dev_status = nested["overall_status"]
    verifier_gates = {
        "verified_more_precise_than_base": dev_status["verified_cases"] > 0
            and dev_status["verified_precision"] > dev_status["base_accuracy"],
        "contradicted_enriches_errors": dev_status["contradicted_cases"] > 0
            and dev_status["contradicted_error_precision"] > 1 - dev_status["base_accuracy"],
        "both_decisive_statuses_nonempty": dev_status["verified_cases"] >= 5
            and dev_status["contradicted_cases"] >= 5,
        "synthetic_semantics": all(item["pass"] for item in _synthetic_semantic_stress().values()),
    }
    development_trace_rate = float(np.mean([
        row["coverage_has_traces"] for row in clean_rows if row["incident_id"] in set(development_ids)
    ]))
    if all(verifier_gates.values()):
        verifier_verdict = "PROMOTED"
    elif development_trace_rate == 0.0:
        # RE1 can calibrate metric evidence but contains no trace evidence.  The
        # known external set cannot be used to resolve this validation gap.
        verifier_verdict = "INCONCLUSIVE"
    else:
        verifier_verdict = "REJECTED"
    positive_development_ci = (
        development_paired["mrr"]["ci_low"] > 0
        or development_paired["ac_at_1"]["ci_low"] > 0
    )
    external_drop_ok = (
        extended_metrics(external_reranked)["ac_at_1"]
        >= extended_metrics(external_rankings)["ac_at_1"] - .01
    )
    rerank_verdict = "PROMOTED" if positive_development_ci and external_drop_ok else "REJECTED"
    case_studies = _case_studies(external_top1, rows_by_incident, frozen_policy)
    with (model_dir / "case-studies.jsonl").open("w", encoding="utf-8") as stream:
        for item in case_studies:
            stream.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")
    with (model_dir / "external-topk-evidence.jsonl").open("w", encoding="utf-8") as stream:
        for incident in sorted(external_profiles):
            stream.write(json.dumps({"incident_id": incident, "profiles": external_profiles[incident]},
                                    sort_keys=True, separators=(",", ":")) + "\n")

    model_bytes = sum(path.stat().st_size for path in model_dir.glob("reranker-seed-*.json"))
    result = {
        "version": "m10d-verifier-v1",
        "verdicts": {"VERIFIER": verifier_verdict, "VERIFIER_RERANK": rerank_verdict},
        "data_protocol": {
            "development": "RE1 nested system holdout plus synthetic semantic stress",
            "external": "post-M10C external evaluation, not pristine external model selection",
            "external_cases": len(external_ids), "external_used_for_selection": False,
            "forbidden_model_features": ["service", "system", "dataset", "fault", "root", "case semantics"],
        },
        "deterministic_verifier": {
            "components": list(COMPONENTS), "status_policy": frozen_policy,
            "nested_development": nested, "promotion_gates": verifier_gates,
            "development_trace_candidate_rate": development_trace_rate,
            "verdict_reason": (
                "RE1 has no trace-bearing candidates, so multi-source status transfer cannot be "
                "validated without using the already-known external 360 for selection."
                if verifier_verdict == "INCONCLUSIVE" else None
            ),
            "synthetic": _synthetic_semantic_stress(),
            "external_overall": external_status,
            "external_by_dataset": _by_dataset_status(external_top1, frozen_policy),
            "claim_scope": "evidence support only; no causal proof or conditional guarantee",
        },
        "verifier_abstention": {
            "frozen_accepted_statuses": frozen_acceptance,
            "nested_development": nested["overall_abstention"],
            "external": external_abstention,
        },
        "learned_reranker": {
            "model": "five-seed shallow XGBoost binary ensemble; Top-3 only",
            "oof_provenance": oof_provenance,
            "development_base": extended_metrics(development_rankings),
            "development_reranked": extended_metrics(development_reranked),
            "development_by_dataset_base": _by_dataset_rankings(development_rankings, ids, RE1),
            "development_by_dataset_reranked": _by_dataset_rankings(development_reranked, ids, RE1),
            "development_paired_bootstrap": development_paired,
            "development_seed_robustness": _seed_summary(per_seed_metrics),
            "external_base": extended_metrics(external_rankings),
            "external_reranked": extended_metrics(external_reranked),
            "external_by_dataset_base": _by_dataset_rankings(external_rankings, ids, EXTERNAL),
            "external_by_dataset_reranked": _by_dataset_rankings(external_reranked, ids, EXTERNAL),
            "external_paired_bootstrap": external_paired,
            "external_seed_robustness": _seed_summary(external_per_seed),
            "promotion_gate": {
                "development_ci_lower_positive": positive_development_ci,
                "external_ac_at_1_drop_at_most_1pp": external_drop_ok,
            },
        },
        "case_studies": case_studies,
        "failure_taxonomy": _failure_taxonomy(external_top1, external_rankings, external_profiles, frozen_policy),
        "performance": {
            "rank_inference_ms_per_incident": 1000 * rank_seconds / len(external_ids),
            "deterministic_verifier_ms_per_incident": 1000 * verifier_seconds / len(external_ids),
            "learned_verifier_ms_per_incident": 1000 * learned_seconds / len(external_ids),
            "learned_model_count": len(final_models), "learned_models_bytes": model_bytes,
        },
        "integrity": {"m10a_m10b": frozen, "m10c": m10c_integrity},
        "environment": {
            "python": platform.python_version(), "numpy": np.__version__,
            "xgboost": xgb.__version__, "bootstrap_resamples": 10_000,
            "bootstrap_seed": SEED, "learned_seeds": list(SEEDS),
        },
        "runtime_seconds": time.monotonic() - started,
    }
    save_json(model_dir / "evaluation.json", result)
    save_json(model_dir / "integrity-manifest.json", {
        "m10c_truth_free_sha256": sha256_file(m10c_artifacts / "truth-free.jsonl"),
        "m9b_truth_free_sha256": sha256_file(m9b_truth_free),
        "status_policy_sha256": sha256_file(model_dir / "status-policy.json"),
        "reranker_models": {path.name: sha256_file(path) for path in sorted(model_dir.glob("reranker-seed-*.json"))},
        "external_topk_evidence_sha256": sha256_file(model_dir / "external-topk-evidence.jsonl"),
        "case_studies_sha256": sha256_file(model_dir / "case-studies.jsonl"),
        "frozen_inputs": result["integrity"],
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--m10c-artifacts", type=Path, default=Path("artifacts/m10c/m10c-v2"))
    parser.add_argument("--m9b-truth-free", type=Path, default=Path("artifacts/m9b/m9b-v1/truth-free.jsonl"))
    parser.add_argument("--models", type=Path, default=Path("ml/models/m10d-verifier"))
    args = parser.parse_args()
    result = run(args.root.resolve(), args.m10c_artifacts.resolve(), args.m9b_truth_free.resolve(), args.models.resolve())
    print(json.dumps({"verdicts": result["verdicts"],
                      "development": result["learned_reranker"]["development_reranked"],
                      "external": result["learned_reranker"]["external_reranked"],
                      "runtime_seconds": result["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
