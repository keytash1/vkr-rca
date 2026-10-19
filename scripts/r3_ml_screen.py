"""Bounded offline development screening. Never writes frozen model directories."""
from pathlib import Path
from collections import Counter, defaultdict
import argparse
import hashlib
import json
import platform
import signal
import subprocess
import time

import numpy as np
import xgboost as xgb
from rca_ml.m12_adapter import canonical_features
from rca_ml.m12_evaluate import rank_candidates
from rca_ml.m13_features import FEATURES, RANKING_FEATURES, build_candidate_rows
from rca_ml.m13_runtime import M13Runtime
from rca_ml.m13_experiment import _fit, _predict
from rca_ml.m13_protocol import cluster_key, grouped_folds, rank_scores, ranking_metrics, truth_rank
from rca_ml.r3_temporal import TEMPORAL_FEATURES, temporal_features, temporal_heuristic

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (20261019, 20261020)
CONFIG = {"max_depth": 3, "eta": .08, "rounds": 24}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def dump(path, value):
    # Output directory is new and exclusively owned by this one experiment.
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def audit():
    run = ROOT / "external-data/m13/runs/development-v1"
    model = ROOT / "ml/models/m13"
    manifest = read(model / "corpus-manifest.json")
    assert sha(run / "telemetry-index.jsonl") == manifest["telemetry_index_sha256"]
    assert sha(run / "truth.jsonl") == manifest["truth_sha256"]
    index = [json.loads(line) for line in (run / "telemetry-index.jsonl").read_text().splitlines()]
    cases = [json.loads(line) for line in (run / "truth.jsonl").read_text().splitlines()]
    truth = {case["incident_id"]: dict(case, system="DeathStarBench-SocialNetwork") for case in cases}
    assert len(index) == len(truth) == 120
    assert all(case["valid_injection"] for case in cases)
    assert {i["incident_id"] for i in index} == set(truth)
    for item in index:
        assert item["incident_id"].startswith("m13-")
        assert sha(run / item["telemetry_path"]) == item["sha256"]
    groups = Counter(cluster_key(case) for case in truth.values())
    assert len(groups) == 60 and set(groups.values()) == {2}
    services = tuple(read(model / "system-manifest.json")["candidate_services"])
    healthy = read(run / "healthy/baseline.json")
    healthy_end = max(s["end_unix"] for s in healthy["segments"])
    observed = {"metrics_outside_window": 0, "spans_outside_window": 0, "empty_trace_windows": 0}
    for item in index:
        payload = read(run / item["telemetry_path"])
        assert healthy_end < payload["start_unix"] < payload["end_unix"]
        assert set(payload["candidate_services"]) == set(services)
        assert truth[item["incident_id"]]["root_service"] in services
        observed["metrics_outside_window"] += sum(not payload["start_unix"] <= p["timestamp"] <= payload["end_unix"] for p in payload["metrics"])
        observed["spans_outside_window"] += sum(not payload["start_unix"] <= p["start_time_us"] / 1e6 <= payload["end_unix"] for p in payload["traces"])
        observed["empty_trace_windows"] += int(not payload["traces"])
    seals = {}
    for directory in ("m13", "m11", "m10c-v2", "m12"):
        for file in sorted((ROOT / "ml/models" / directory).glob("*.json")):
            seals[str(file.relative_to(ROOT))] = sha(file)
    pretrained = read(ROOT / "ml/models/m11/freeze-manifest.json")
    assert pretrained["selection_data"] == ["RE1-OB", "RE1-SS", "RE1-TT"]
    counts = Counter()
    for directory in (ROOT / "external-data/rcaeval").iterdir():
        if directory.is_dir():
            counts[directory.name.split("_", 1)[0]] += 1
    protected = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / "reports").glob("*V5[25]*docx"))}
    return {"role": "USED_DEVELOPMENT_ONLY", "incidents": len(index), "clusters": len(groups),
            "repetitions": 2, "healthy_before_every_incident": True, "candidate_coverage": 1.0,
            "canonical_boundary_observations": observed, "pretrained_context_selection": pretrained["selection_data"],
            "rcaeval_directory_inventory_not_a_new_test": dict(counts),
            "index_sha256": sha(run / "telemetry-index.jsonl"), "truth_sha256": sha(run / "truth.jsonl"),
            "healthy_raw_sha256": sha(run / "healthy/baseline.json"), "frozen_seals": seals,
            "protected_reports": protected}, index, truth, services


def intervals(challenger, control, truth):
    keys = defaultdict(list)
    for name in sorted(truth):
        keys[cluster_key(truth[name])].append(name)
    result = {}
    for metric in ("mrr", "ac_at_1", "ac_at_3", "ac_at_5"):
        deltas = []
        for ids in keys.values():
            values = []
            for name in ids:
                ranks = [truth_rank(r[name], truth[name]["root_service"]) for r in (challenger, control)]
                score = [(0 if rank is None else 1 / rank) if metric == "mrr" else int(rank is not None and rank <= int(metric.split("_")[-1])) for rank in ranks]
                values.append(score[0] - score[1])
            deltas.append(float(np.mean(values)))
        delta = np.asarray(deltas)
        sampled = np.random.default_rng(SEEDS[0]).integers(0, len(delta), (2000, len(delta)))
        lo, hi = np.quantile(delta[sampled].mean(axis=1), [.025, .975])
        result[metric] = {"delta": float(delta.mean()), "ci95": [float(lo), float(hi)], "groups": len(keys), "resamples": 2000}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.parent != (ROOT / "docs/product-research").resolve() or not out.name.startswith("r3-ml-"):
        raise ValueError("output must be new docs/product-research/r3-ml-* directory")
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("20 minute experiment limit")))
    signal.alarm(1200)
    progress = {"stage": "audit", "fits_completed": 0, "status": "running"}
    dump(out / "progress.json", progress)
    inventory, index, truth, services = audit()
    dump(out / "audit.json", inventory)
    assignments = grouped_folds(list(truth.values()), folds=3, seed=SEEDS[0])
    splits = []
    for fold in range(3):
        test = sorted(i for i, value in assignments.items() if value == fold)
        train = sorted(set(truth) - set(test))
        assert not {cluster_key(truth[i]) for i in train} & {cluster_key(truth[i]) for i in test}
        splits.append({"fold": fold, "train": train, "test": test})
    registration = {"protocol_sha256": sha(ROOT / "docs/R3_ML_PROTOCOL.md"),
                    "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), ROOT / "ml/rca_ml/r3_temporal.py")},
                    "base_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    "python": platform.python_version(), "xgboost": xgb.__version__, "numpy": np.__version__,
                    "seeds": SEEDS, "config": CONFIG, "splits": splits, "max_fits": 12,
                    "label_role": "USED_DEVELOPMENT", "new_independent_test": False,
                    "preprocessing": "Fixed separate healthy calibration and frozen RE1-trained context; no validation fit"}
    dump(out / "registration.json", registration)
    print("Audit passed: 120 cases / 60 groups; registration saved before feature extraction", flush=True)
    baseline = read(ROOT / "ml/models/m13/healthy-baseline.json")
    legacy = read(ROOT / "ml/models/m13/legacy-metric-baseline.json")
    rows, metric_rankings, time_rankings = {}, {}, {}
    allowed = {"start_unix", "end_unix", "requests_per_second", "metrics", "traces", "traces_collected"}
    feature_start = time.monotonic()
    for number, item in enumerate(index, 1):
        name = item["incident_id"]
        payload = read(ROOT / "external-data/m13/runs/development-v1" / item["telemetry_path"])
        clean = {k: v for k, v in payload.items() if k in allowed}
        current = build_candidate_rows(clean, baseline, services)
        legacy_rows = canonical_features(clean["metrics"], legacy, services, baseline["expected_edges"])
        ranking = rank_candidates(name, legacy_rows, ROOT)["m11_top5"]
        M13Runtime._add_ranking_context(current, ranking)
        temporal = temporal_features(clean, baseline, services)
        shifts = {r["service"]: r["features"]["metric_max_shift"] for r in current}
        metric_rankings[name] = rank_scores(shifts)
        time_rankings[name] = temporal_heuristic(temporal, shifts)
        for row in current:
            row["features"].update(temporal[row["service"]])
            row["incident_id"] = name
        rows[name] = current
        if number % 30 == 0:
            print(f"Features: {number}/120", flush=True)
    feature_seconds = time.monotonic() - feature_start
    # The extractor never receives truth. Attach targets only after all features are fixed.
    dump(out / "truth-free-features.json", rows)
    for name, values in rows.items():
        for row in values:
            row["target"] = int(row["service"] == truth[name]["root_service"])
    predictions = {}
    seed_metrics = {}
    for variant, columns in (("refit_control", FEATURES + RANKING_FEATURES),
                             ("refit_temporal", FEATURES + RANKING_FEATURES + TEMPORAL_FEATURES)):
        variant_preds = []
        for seed in SEEDS:
            oof = {}
            for split in splits:
                model = _fit(rows, split["train"], columns, CONFIG, seed + split["fold"])
                oof.update(_predict(model, rows, split["test"], columns))
                model.save_model(out / f"{variant}-{seed}-fold{split['fold']}.json")
                progress.update(stage="screening", fits_completed=progress["fits_completed"] + 1)
                dump(out / "progress.json", progress)
                print(f"Fit {progress['fits_completed']}/12: {variant}, seed={seed}, fold={split['fold']}", flush=True)
            assert set(oof) == set(truth)
            dump(out / f"{variant}-{seed}-oof.json", oof)
            seed_metrics[f"{variant}-{seed}"] = ranking_metrics(oof, truth)
            variant_preds.append(oof)
        combined = {}
        for name in truth:
            scored = defaultdict(list)
            for prediction in variant_preds:
                for item in prediction[name]:
                    scored[item["service"]].append(item["score"])
            combined[name] = rank_scores({s: float(np.mean(v)) for s, v in scored.items()})
        predictions[variant] = combined
    predictions.update(metric_heuristic=metric_rankings, temporal_heuristic=time_rankings)
    metrics = {name: ranking_metrics(value, truth) for name, value in predictions.items()}
    comparisons = intervals(predictions["refit_temporal"], predictions["refit_control"], truth)
    slices = {}
    for field in ("fault_family", "root_service", "workload_regime"):
        slices[field] = {}
        for group in sorted({case[field] for case in truth.values()}):
            selected = {i: case for i, case in truth.items() if case[field] == group}
            slices[field][group] = {v: ranking_metrics(pred, selected) for v, pred in predictions.items()}
    a, b = metrics["refit_temporal"], metrics["refit_control"]
    gates = {"delta_mrr_at_least_02": comparisons["mrr"]["delta"] >= .02,
             "positive_cluster_ci": comparisons["mrr"]["ci95"][0] > 0,
             "ac3_noninferior": a["ac_at_3"] >= b["ac_at_3"] - .02,
             "ac5_noninferior": a["ac_at_5"] >= b["ac_at_5"] - .02,
             "fault_ac1_noninferior": all(v["refit_temporal"]["ac_at_1"] >= v["refit_control"]["ac_at_1"] - .10 - 1e-12 for v in slices["fault_family"].values())}
    for path, expected in inventory["frozen_seals"].items():
        assert sha(ROOT / path) == expected, path
    for path, expected in inventory["protected_reports"].items():
        assert sha(ROOT / path) == expected, path
    result = {"verdict": "NEEDS_FRESH_TEST" if all(gates.values()) else "REJECTED_FOR_PROMOTION",
              "scope": "Development screening only; no independent improvement claim",
              "metrics": metrics, "per_seed_metrics": seed_metrics, "paired_cluster_comparison": comparisons,
              "slices": slices, "gates": gates, "feature_extraction_seconds": feature_seconds,
              "total_seconds": time.monotonic() - started, "fits": progress["fits_completed"],
              "frozen_champion_comparison": "Not rescored on its own training set; matched OOF refit is the primary control",
              "product_modified": False, "historical_assets_and_reports_unchanged": True}
    dump(out / "predictions.json", predictions)
    dump(out / "results.json", result)
    progress.update(status="complete", stage="closed", verdict=result["verdict"])
    dump(out / "progress.json", progress)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    assert size <= 50 * 1024 * 1024
    signal.alarm(0)
    print(json.dumps({k: result[k] for k in ("verdict", "metrics", "paired_cluster_comparison", "gates", "total_seconds", "fits")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
