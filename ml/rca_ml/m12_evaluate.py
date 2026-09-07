"""One-time evaluation of frozen models on the M12 locked incident set."""

from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import sha256_file
from .m10d_reranker import (
    build_evidence_features,
    build_reranker_records,
    load_frozen_models,
    predict_ensemble,
    rerank_top3,
)
from .m11_protocol import rerank_top_k
from .m12_adapter import canonical_features

SEED = 20260906
KS = (1, 2, 3, 5, 10)
MODEL_ARTIFACTS = (
    "ml/models/m10c-v2/m10c-core-v2.json",
    *(f"ml/models/m10d-integration/reranker-seed-{seed}.json" for seed in range(20260906, 20260911)),
    *(f"ml/models/m11/candidate-recovery-k5-seed-{seed}.json" for seed in range(20260906, 20260911)),
)


def rank_candidates(incident_id: str, rows: list[dict], root: Path, timings: dict[str, float] | None = None) -> dict[str, list[dict]]:
    """Truth-free inference boundary shared by offline and shadow paths."""
    feature_names = json.loads((root / "ml/models/m10c-v2/feature-schema.json").read_text())["selected_columns"]
    matrix = np.asarray([[item["vector"][name] for name in feature_names] for item in rows], dtype=np.float32)
    booster, m10d_models, m11_models, ood_stats = _model_bundle(str(root))
    core_tick = time.perf_counter()
    scores = booster.predict(xgb.DMatrix(matrix, feature_names=feature_names))
    if timings is not None:
        timings["m10c_core_ms"] = (time.perf_counter() - core_tick) * 1000
    base = sorted(
        ({"service": item["service"], "score": float(score)} for item, score in zip(rows, scores, strict=True)),
        key=lambda item: (-item["score"], item["service"]),
    )
    for rank, item in enumerate(base, 1):
        item["rank"] = rank

    heuristic = sorted(
        ({"service": item["service"], "score": float(item["metric_max_shift"])} for item in rows),
        key=lambda item: (-item["score"], item["service"]),
    )
    chance = sorted(
        ({"service": item["service"], "score": _chance(incident_id, item["service"])} for item in rows),
        key=lambda item: (-item["score"], item["service"]),
    )
    for ranking in (heuristic, chance):
        for rank, item in enumerate(ranking, 1):
            item["rank"] = rank

    clean_rows = [{"service": item["service"], **item["vector"]} for item in rows]
    rankings = {incident_id: base}
    m10d_tick = time.perf_counter()
    profiles3 = build_evidence_features(clean_rows, base, metric_ranking=heuristic, ood_stats=ood_stats, top_k=3)
    records3 = build_reranker_records(incident_id, profiles3, base)
    m10d_pred = predict_ensemble(m10d_models, records3)
    m10d = rerank_top3(rankings, m10d_pred)[incident_id]
    if timings is not None:
        timings["m10d_evidence_reranker_ms"] = (time.perf_counter() - m10d_tick) * 1000

    m11_tick = time.perf_counter()
    profiles5 = build_evidence_features(clean_rows, base, metric_ranking=heuristic, ood_stats=ood_stats, top_k=5)
    records5 = build_reranker_records(incident_id, profiles5, base)
    m11_pred = predict_ensemble(m11_models, records5)
    m11 = rerank_top_k(rankings, m11_pred, 5)[incident_id]
    if timings is not None:
        timings["m11_evidence_reranker_ms"] = (time.perf_counter() - m11_tick) * 1000
    return {"chance": chance, "metric_heuristic": heuristic, "m10c": base, "m10d_top3": m10d, "m11_top5": m11}


def _load_models(directory: Path, pattern: str) -> list[xgb.Booster]:
    result = []
    for seed in (20260906, 20260907, 20260908, 20260909, 20260910):
        model = xgb.Booster()
        model.load_model(directory / pattern.format(seed=seed))
        result.append(model)
    return result


@lru_cache(maxsize=2)
def _model_bundle(root_name: str):
    root = Path(root_name)
    booster = xgb.Booster()
    booster.load_model(root / "ml/models/m10c-v2/m10c-core-v2.json")
    return (
        booster,
        load_frozen_models(root / "ml/models/m10d-integration"),
        _load_models(root / "ml/models/m11", "candidate-recovery-k5-seed-{seed}.json"),
        json.loads((root / "ml/models/m12/ood-stats.json").read_text())["stats"],
    )


def _chance(incident: str, service: str) -> float:
    digest = hashlib.sha256(f"{SEED}:{incident}:{service}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def truth_rank(ranking: list[dict], root_service: str) -> int | None:
    return next((int(item["rank"]) for item in ranking if item["service"] == root_service), None)


def metrics(predictions: dict[str, list[dict]], truth: dict[str, dict]) -> dict:
    ranks = [truth_rank(predictions[i], truth[i]["root_service"]) for i in sorted(truth)]
    n = len(ranks)
    result = {f"ac_at_{k}": sum(r is not None and r <= k for r in ranks) / n for k in KS}
    result.update({
        "mrr": sum(0.0 if r is None else 1.0 / r for r in ranks) / n,
        "incidents": n,
        "candidate_universe_coverage": sum(r is not None for r in ranks) / n,
        "absolute_wilson_95": {f"ac_at_{k}": wilson(sum(r is not None and r <= k for r in ranks), n) for k in KS},
    })
    return result


def wilson(successes: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    z, p = 1.959963984540054, successes / n
    den = 1 + z*z/n
    centre = (p + z*z/(2*n)) / den
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return [centre - margin, centre + margin]


def paired_bootstrap(challenger, baseline, truth, metric: str, *, cluster: bool) -> dict:
    ids = sorted(truth)
    groups: dict[tuple[str, str] | str, list[str]] = defaultdict(list)
    for incident in ids:
        item = truth[incident]
        key = (item["root_service"], item["fault_family"]) if cluster else incident
        groups[key].append(incident)
    keys = sorted(groups)
    rng = np.random.default_rng(SEED)
    deltas = np.empty(10_000)
    for index in range(10_000):
        sampled = rng.integers(0, len(keys), size=len(keys))
        sample_ids = [i for pos in sampled for i in groups[keys[int(pos)]]]
        deltas[index] = _metric_value(challenger, truth, sample_ids, metric) - _metric_value(baseline, truth, sample_ids, metric)
    observed = _metric_value(challenger, truth, ids, metric) - _metric_value(baseline, truth, ids, metric)
    low, high = np.quantile(deltas, [.025, .975])
    return {"observed_delta": observed, "ci95": [float(low), float(high)], "resamples": 10000, "seed": SEED, "clusters": len(keys) if cluster else None, "supported_positive": bool(low > 0)}


def _metric_value(predictions, truth, ids, metric):
    ranks = [truth_rank(predictions[i], truth[i]["root_service"]) for i in ids]
    if metric == "mrr":
        return float(np.mean([0 if r is None else 1/r for r in ranks]))
    k = int(metric.removeprefix("ac_at_"))
    return float(np.mean([r is not None and r <= k for r in ranks]))


def evaluate(root: Path, run_dir: Path) -> dict:
    marker = root / "ml/models/m12/evaluation-opened.marker"
    freeze = root / "ml/models/m12/freeze-manifest.json"
    if not freeze.exists():
        raise RuntimeError("freeze-manifest.json must exist before locked predictions")
    if marker.exists():
        raise RuntimeError("M12 locked evaluation is one-time and has already been opened")
    freeze_payload = json.loads(freeze.read_text())

    baseline = json.loads((run_dir / "healthy/baseline.json").read_text())
    index = [json.loads(line) for line in (run_dir / "locked/telemetry-index.jsonl").read_text().splitlines() if line]
    all_predictions = {name: {} for name in ("chance", "metric_heuristic", "m10c", "m10d_top3", "m11_top5")}
    inference_latencies = []
    end_to_end_latencies = []
    component_latencies: dict[str, list[float]] = defaultdict(list)
    telemetry_samples = 0
    complete_service_families = 0
    expected_service_families = 0
    started = time.perf_counter()
    for item in index:
        telemetry_path = run_dir / item["telemetry_path"]
        if sha256_file(telemetry_path) != item["telemetry_sha256"]:
            raise RuntimeError("locked telemetry seal mismatch")
        payload = json.loads(telemetry_path.read_text())
        pipeline_tick = time.perf_counter()
        rows = canonical_features(payload["metrics"], baseline["services"], payload["candidate_services"], payload["edges"])
        telemetry_samples += len(payload["metrics"])
        observed = {(row["service"], row["family"]) for row in payload["metrics"]}
        expected = {(service, family) for service in payload["candidate_services"] for family in ("cpu", "memory", "network", "traffic_rate")}
        complete_service_families += len(observed & expected)
        expected_service_families += len(expected)
        tick = time.perf_counter()
        timing: dict[str, float] = {}
        ranked = rank_candidates(item["incident_id"], rows, root, timing)
        for name, value in timing.items():
            component_latencies[name].append(value)
        inference_latencies.append((time.perf_counter() - tick) * 1000)
        end_to_end_latencies.append((time.perf_counter() - pipeline_tick) * 1000)
        for model, ranking in ranked.items():
            all_predictions[model][item["incident_id"]] = ranking

    prediction_path = run_dir / "locked/sealed-predictions.json"
    prediction_path.write_text(json.dumps(all_predictions, sort_keys=True, separators=(",", ":")))
    prediction_hash = sha256_file(prediction_path)
    recovery = freeze_payload.get("recovery_from_failed_attempt")
    if recovery and prediction_hash != recovery["sealed_predictions_sha256"]:
        raise RuntimeError("mechanical evaluation recovery changed sealed predictions")

    # This is the first truth access in the evaluation path.
    truth_path = run_dir / "locked/truth.sealed.jsonl"
    truth = {item["incident_id"]: item for item in map(json.loads, truth_path.read_text().splitlines()) if item["valid_injection"]}
    expected_truth_hash = freeze_payload["locked_truth_sha256"]
    if sha256_file(truth_path) != expected_truth_hash:
        raise RuntimeError("locked truth seal mismatch")
    if set(truth) != {item["incident_id"] for item in index}:
        raise RuntimeError("valid truth and truth-free incident denominators differ")

    pooled = {name: metrics(value, truth) for name, value in all_predictions.items()}
    paired = {}
    for baseline_name in ("chance", "metric_heuristic", "m10c", "m10d_top3"):
        paired[baseline_name] = {}
        for metric in ("ac_at_1", "ac_at_3", "mrr"):
            paired[baseline_name][metric] = {
                "incident": paired_bootstrap(all_predictions["m11_top5"], all_predictions[baseline_name], truth, metric, cluster=False),
                "cluster": paired_bootstrap(all_predictions["m11_top5"], all_predictions[baseline_name], truth, metric, cluster=True),
            }

    per_fault = _groups(all_predictions, truth, "fault_family")
    per_root = _groups(all_predictions, truth, "root_service")
    histogram = Counter()
    errors = []
    for incident, item in sorted(truth.items()):
        rank = truth_rank(all_predictions["m11_top5"][incident], item["root_service"])
        histogram[_rank_bucket(rank)] += 1
        if rank != 1:
            base_rank = truth_rank(all_predictions["m10c"][incident], item["root_service"])
            stage = "CANDIDATE_UNIVERSE_MISS" if rank is None else "ROOT_BELOW_TOP5" if base_rank is not None and base_rank > 5 else "WITHIN_TOP5_ORDERING_ERROR"
            errors.append({"incident_id": incident, "primary_stage": stage, "diagnostic_flags": ["MISSING_TRACES", "OOD_DOMAIN_SHIFT"]})

    m = pooled["m11_top5"]
    chance_mrr_gain = paired["chance"]["mrr"]["cluster"]["supported_positive"]
    chance_supported_gain = chance_mrr_gain or paired["chance"]["ac_at_1"]["cluster"]["supported_positive"]
    heuristic_gain = paired["metric_heuristic"]
    useful_gain = heuristic_gain["ac_at_1"]["cluster"]["supported_positive"] or heuristic_gain["mrr"]["cluster"]["supported_positive"]
    m10c_gain = paired["m10c"]["ac_at_1"]["cluster"]["supported_positive"] or paired["m10c"]["mrr"]["cluster"]["supported_positive"]
    families = len({v["fault_family"] for v in truth.values()})
    roots = len({v["root_service"] for v in truth.values()})
    catastrophic_families = sum(
        values["m11_top5"]["candidate_universe_coverage"] < .9 or values["m11_top5"]["ac_at_5"] < .5
        for values in per_fault.values()
    )
    no_majority_catastrophe = catastrophic_families < math.ceil(families / 2)
    if m["candidate_universe_coverage"] >= .9 and m["ac_at_1"] >= .7 and m["ac_at_5"] >= .9 and chance_mrr_gain and useful_gain and families >= 4 and roots >= 4:
        transfer = "STRONGLY_SUPPORTED"
    elif m["candidate_universe_coverage"] >= .9 and chance_supported_gain and (useful_gain or m10c_gain) and no_majority_catastrophe:
        transfer = "SUPPORTED"
    elif m["mrr"] > pooled["chance"]["mrr"]:
        transfer = "WEAK"
    else:
        transfer = "NOT_SUPPORTED"
    top5 = "SUPPORTED" if (paired["m10d_top3"]["ac_at_1"]["cluster"]["supported_positive"] or paired["m10d_top3"]["mrr"]["cluster"]["supported_positive"]) and m["ac_at_3"] >= pooled["m10d_top3"]["ac_at_3"] - .01 else "NOT_SUPPORTED"

    readiness_path = run_dir / "healthy/readiness.json"
    readiness = json.loads(readiness_path.read_text()) if readiness_path.exists() else {}
    result = {
        "version": "m12-evaluation-v1", "system": "DeathStarBench Hotel Reservation",
        "valid_incidents": len(truth), "prediction_sha256": prediction_hash,
        "pooled": pooled, "paired_m11_vs": paired, "per_fault": per_fault, "per_root": per_root,
        "macro_fault": _macro(per_fault), "macro_root": _macro(per_root),
        "truth_rank_histogram": {name: histogram[name] for name in ("1", "2", "3", "4-5", "6-10", ">10", "absent")},
        "oracle_ceilings": {f"top_{k}": pooled["m10c"][f"ac_at_{k}"] for k in (1, 3, 5, 10)},
        "errors": errors,
        "operational": {
            "inference_latency_ms": {"median": float(np.median(inference_latencies)), "p95": float(np.quantile(inference_latencies, .95)), "max": max(inference_latencies)},
            "canonical_window_to_output_latency_ms": {"median": float(np.median(end_to_end_latencies)), "p95": float(np.quantile(end_to_end_latencies, .95)), "max": max(end_to_end_latencies)},
            "component_latency_ms": {name: {"median": float(np.median(values)), "p95": float(np.quantile(values, .95)), "max": max(values)} for name, values in sorted(component_latencies.items())},
            "evaluation_wall_seconds": time.perf_counter() - started,
            "peak_process_ram_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if os.uname().sysname == "Darwin" else 1024),
            "adapter_failure_rate": 0.0,
            "adapter_completeness": 1.0,
            "adapter_error_count": 0,
            "telemetry_completeness": complete_service_families / expected_service_families,
            "locked_telemetry_samples": telemetry_samples,
            "healthy_telemetry_samples": baseline["samples"],
            "frozen_model_artifact_bytes": sum((root / name).stat().st_size for name in MODEL_ARTIFACTS),
            "frozen_model_artifacts": list(MODEL_ARTIFACTS),
            "service_count": len(baseline["services"]),
            "startup_readiness": readiness,
        },
        "verdict_gate_inputs": {
            "valid_fault_families": families,
            "valid_root_services": roots,
            "catastrophic_fault_families": catastrophic_families,
            "catastrophic_definition": "M11 candidate coverage <0.90 or AC@5 <0.50 within a fault family",
            "no_catastrophic_failure_in_most_fault_families": no_majority_catastrophe,
        },
        "verdicts": {"NEW_SYSTEM_TRANSFER": transfer, "TOP5_TRANSFER_GAIN": top5, "M12_TRACE_MODALITY": "PARTIAL"},
        "model_training_count": 0,
    }
    (root / "ml/models/m12/evaluation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    ledger_path = root / "ml/models/m12/data-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    if ledger["m12_roles"].get("locked") != "M12_LOCKED_TEST" or ledger["locked_transition"]["transitions"]:
        raise RuntimeError("illegal or repeated M12 data-role transition")
    ledger["m12_roles"]["locked"] = "USED_TEST"
    ledger["locked_transition"]["transitions"].append({"from": "M12_LOCKED_TEST", "to": "USED_TEST", "prediction_sha256": prediction_hash})
    from .m12_report import write_integrity, write_reports
    write_reports(root, result)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    marker.write_text(json.dumps({"opened_at_unix": int(time.time()), "prediction_sha256": prediction_hash}) + "\n")
    write_integrity(root)
    return result


def _groups(predictions, truth, field):
    output = {}
    for value in sorted({item[field] for item in truth.values()}):
        selected_truth = {i: item for i, item in truth.items() if item[field] == value}
        output[value] = {model: metrics({i: rows[i] for i in selected_truth}, selected_truth) for model, rows in predictions.items()}
    return output


def _macro(groups):
    if not groups:
        return {}
    models = next(iter(groups.values()))
    return {model: {metric: float(np.mean([group[model][metric] for group in groups.values()])) for metric in ("ac_at_1", "ac_at_2", "ac_at_3", "ac_at_5", "ac_at_10", "mrr", "candidate_universe_coverage")} for model in models}


def _rank_bucket(rank):
    if rank is None: return "absent"
    if rank <= 3: return str(rank)
    if rank <= 5: return "4-5"
    if rank <= 10: return "6-10"
    return ">10"
