"""Registered role-free overlap support and matched OOF research only."""
from collections import defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import signal
import subprocess
import time

import numpy as np
from rca_ml.r3_dependency_overlap import OVERLAP_FEATURES, summarize_overlap, overlap_features
from rca_ml.m13_features import FEATURES, RANKING_FEATURES
from rca_ml.m13_experiment import _fit, _predict
from rca_ml.m13_protocol import grouped_folds, cluster_key, ranking_metrics, rank_scores, truth_rank

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/product-research/r3-dependency-overlap-v2"
RUN = ROOT / "external-data/m13/runs/development-v1"
SEEDS = (20261020, 20261021)
CONFIG = {"max_depth": 3, "eta": .08, "rounds": 24}
CACHE = ROOT / "docs/product-research/r3-ml-temporal-v1/truth-free-features.json"
PROTOCOL = ROOT / "docs/R3_DEPENDENCY_OVERLAP_PROTOCOL.md"
SOURCE = ROOT / "ml/rca_ml/r3_dependency_overlap.py"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    with (OUT / name).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def seals():
    paths = []
    for directory in ("m13", "m14", "m11", "m10c-v2", "m12"):
        paths.extend((ROOT / "ml/models" / directory).glob("*.json"))
    paths.extend((ROOT / "reports").glob("*.docx"))
    paths.append(ROOT / "ml/rca_ml/m13_trace.py")
    paths.append(ROOT / "ml/rca_ml/m13_features.py")
    return {str(p): sha(p) for p in sorted(paths)}


def check_registration(reg):
    assert reg["protocol_sha256"] == sha(PROTOCOL), "protocol drift"
    assert reg["source_sha256"] == sha(SOURCE), "extractor drift"
    assert reg["runner_sha256"] == sha(Path(__file__)), "runner drift"
    for p, expected in reg["protected_files"].items():
        assert sha(Path(p)) == expected, p
    assert reg["product_head"] == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT.parent / "rca-workbench", text=True).strip()


def support():
    OUT.mkdir(exist_ok=False)
    manifest = read(ROOT / "ml/models/m13/corpus-manifest.json")
    assert sha(RUN / "telemetry-index.jsonl") == manifest["telemetry_index_sha256"]
    index = [json.loads(line) for line in (RUN / "telemetry-index.jsonl").read_text().splitlines()]
    assert len(index) == 120
    healthy = read(RUN / "healthy/baseline.json")
    services = tuple(read(ROOT / "ml/models/m13/system-manifest.json")["candidate_services"])
    assert len(FEATURES + RANKING_FEATURES) == 62 and len(OVERLAP_FEATURES) == 9
    reg = {"role": "USED_DEVELOPMENT_NOT_INDEPENDENT_TEST", "seeds": SEEDS,
           "config": CONFIG, "protocol_sha256": sha(PROTOCOL), "source_sha256": sha(SOURCE),
           "runner_sha256": sha(Path(__file__)), "cache_sha256": sha(CACHE),
           "index_sha256": sha(RUN / "telemetry-index.jsonl"),
           "healthy_sha256": sha(RUN / "healthy/baseline.json"),
           "protected_files": seals(), "product_head": subprocess.check_output(
               ["git", "rev-parse", "HEAD"], cwd=ROOT.parent / "rca-workbench", text=True).strip(),
           "support_before_any_targets_or_fits": True, "max_fits": 12,
           "columns": list(FEATURES + RANKING_FEATURES + OVERLAP_FEATURES)}
    save("registration.json", reg)
    a = min(s["start_unix"] for s in healthy["segments"]) * 1e6
    b = max(s["end_unix"] for s in healthy["segments"]) * 1e6
    normal = summarize_overlap(healthy["traces"], services, a, b)
    summaries, features, records = {}, {}, []
    for item in index:
        path = RUN / item["telemetry_path"]
        assert sha(path) == item["sha256"], "input capture drift"
        incident = read(path)
        name = item["incident_id"]
        assert name.startswith("m13-")
        current = summarize_overlap(incident["traces"], services,
                                    incident["start_unix"] * 1e6, incident["end_unix"] * 1e6)
        summaries[name] = current
        features[name] = overlap_features(current, normal)
        supported = [s for s in services if current[s]["entries"] > 0 and normal[s]["entries"] >= 5]
        records.append({"incident_id": name, "observed_services": len(supported),
                        "positive_overlap": any(any(v > 0 for v in row["ratios"]) for row in current.values()),
                        "entries": sum(row["entries"] for row in current.values()),
                        "clipped_boundaries": sum(row["clipped_boundaries"] for row in current.values())})
    supported_healthy = [s for s, r in normal.items() if r["entries"] >= 5 and any(v > 0 for v in r["ratios"])]
    qualified = sum(r["positive_overlap"] and r["observed_services"] >= 2 for r in records)
    gate = len(supported_healthy) >= 2 and qualified >= 60
    support_result = {"gate": gate, "qualified_windows": qualified,
                      "healthy_services_with_overlap": supported_healthy,
                      "healthy_summary": normal, "cases": records, "fits": 0,
                      "limits": "Observed temporal overlap is not blocking, exclusive CPU or causal proof"}
    save("truth-free-summaries.json", summaries)
    save("truth-free-overlap-features.json", features)
    save("support.json", support_result)
    check_registration(reg)
    print(json.dumps({"gate": gate, "healthy_services_with_overlap": supported_healthy,
                      "qualified_windows": qualified, "fits": 0}), flush=True)


def compare(challenger, control, truth):
    groups = defaultdict(list)
    for name, item in truth.items():
        groups[cluster_key(item)].append(name)
    out = {}
    for metric in ("mrr", "ac_at_1", "ac_at_3", "ac_at_5"):
        values = []
        for ids in groups.values():
            delta = []
            for name in ids:
                ranks = [truth_rank(p[name], truth[name]["root_service"]) for p in (challenger, control)]
                scores = [(0.0 if r is None else 1 / r) if metric == "mrr" else
                          float(r is not None and r <= int(metric[-1])) for r in ranks]
                delta.append(scores[0] - scores[1])
            values.append(np.mean(delta))
        d = np.array(values)
        sample = np.random.default_rng(SEEDS[0]).integers(0, len(d), size=(2000, len(d)))
        out[metric] = {"delta": float(d.mean()), "ci95": np.quantile(d[sample].mean(axis=1), [.025, .975]).tolist(),
                       "groups": len(d), "resamples": 2000}
    return out


def screen():
    started = time.monotonic()
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("screen limit")))
    signal.alarm(1200)
    reg, supp = read(OUT / "registration.json"), read(OUT / "support.json")
    check_registration(reg)
    if not supp["gate"]:
        raise ValueError("support gate failed: no fitting permitted")
    assert sha(CACHE) == reg["cache_sha256"]
    manifest = read(ROOT / "ml/models/m13/corpus-manifest.json")
    assert sha(RUN / "truth.jsonl") == manifest["truth_sha256"]
    truth = {r["incident_id"]: dict(r, system="DeathStarBench-SocialNetwork") for r in
             [json.loads(line) for line in (RUN / "truth.jsonl").read_text().splitlines()]}
    base, extra = read(CACHE), read(OUT / "truth-free-overlap-features.json")
    assert set(truth) == set(base) == set(extra)
    assert len({cluster_key(r) for r in truth.values()}) == 60
    folds = grouped_folds(list(truth.values()), folds=3, seed=SEEDS[0])
    splits = [{"fold": k, "train": sorted(i for i in truth if folds[i] != k),
               "test": sorted(i for i in truth if folds[i] == k)} for k in range(3)]
    for split in splits:
        assert not {cluster_key(truth[i]) for i in split["train"]} & {cluster_key(truth[i]) for i in split["test"]}
    save("splits.json", splits)
    rows = {}
    columns = FEATURES + RANKING_FEATURES + OVERLAP_FEATURES
    for variant in ("control", "overlap"):
        rows[variant] = {}
        for name, candidates in base.items():
            rows[variant][name] = []
            for old in candidates:
                assert set(old) == {"service", "features", "incident_id"}
                f = {c: float(old["features"][c]) for c in FEATURES + RANKING_FEATURES}
                f.update(extra[name][old["service"]] if variant == "overlap" else dict.fromkeys(OVERLAP_FEATURES, 0.0))
                rows[variant][name].append({"incident_id": name, "service": old["service"], "features": f})
    save("truth-free-matched-features.json", rows)
    # Target is joined only after all feature vectors and denominator are fixed.
    for data in rows.values():
        for name, candidates in data.items():
            for row in candidates:
                row["target"] = int(row["service"] == truth[name]["root_service"])
    predictions, per_seed, count = {}, {}, 0
    for variant, data in rows.items():
        all_seed = []
        for seed in SEEDS:
            oof = {}
            for split in splits:
                model = _fit(data, split["train"], columns, CONFIG, seed + split["fold"])
                oof.update(_predict(model, data, split["test"], columns))
                model.save_model(OUT / f"{variant}-{seed}-{split['fold']}.json")
                count += 1
                print(f"fit {count}/12 {variant} seed {seed} fold {split['fold']}", flush=True)
            assert set(oof) == set(truth)
            save(f"{variant}-{seed}-oof.json", oof)
            per_seed[f"{variant}-{seed}"] = ranking_metrics(oof, truth)
            all_seed.append(oof)
        predictions[variant] = {}
        for name in truth:
            scores = defaultdict(list)
            for pred in all_seed:
                for row in pred[name]:
                    scores[row["service"]].append(row["score"])
            predictions[variant][name] = rank_scores({s: float(np.mean(v)) for s, v in scores.items()})
    metrics = {v: ranking_metrics(pred, truth) for v, pred in predictions.items()}
    intervals = compare(predictions["overlap"], predictions["control"], truth)
    slices = {}
    for family in sorted({r["fault_family"] for r in truth.values()}):
        ids = {i: r for i, r in truth.items() if r["fault_family"] == family}
        slices[family] = {v: ranking_metrics(pred, ids) for v, pred in predictions.items()}
    a, b = metrics["overlap"], metrics["control"]
    gates = {"delta_mrr": intervals["mrr"]["delta"] >= .02,
             "positive_ci": intervals["mrr"]["ci95"][0] > 0,
             "ac3_guard": a["ac_at_3"] >= b["ac_at_3"] - .02,
             "ac5_guard": a["ac_at_5"] >= b["ac_at_5"] - .02,
             "family_guard": all(r["overlap"]["ac_at_1"] >= r["control"]["ac_at_1"] - .10 - 1e-12 for r in slices.values())}
    check_registration(reg)
    result = {"verdict": "NEEDS_FRESH_TEST" if all(gates.values()) else "REJECTED_FOR_PROMOTION",
              "metrics": metrics, "per_seed_metrics": per_seed, "paired_cluster_comparison": intervals,
              "fault_family_slices": slices, "gates": gates, "fits": count,
              "masked_oof": "NOT_RUN_REQUIRES_FULL_REEXTRACTION_NOT_ZEROING_ONLY_NEW_COLUMNS",
              "scope": "USED_DEVELOPMENT_FIXED_CONTEXT_GROUPED_SCREENING_NOT_TRANSFER_PROOF",
              "product_modified": False, "protected_files_unchanged": True,
              "seconds": time.monotonic() - started}
    save("predictions.json", predictions)
    save("results.json", result)
    signal.alarm(0)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("support", "screen"))
    args = parser.parse_args()
    {"support": support, "screen": screen}[args.phase]()
