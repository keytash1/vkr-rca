"""Predeclared masked OOF diagnostic using saved models; zero new fits."""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import time

import numpy as np
import xgboost as xgb
from rca_ml.m13_features import FEATURES, RANKING_FEATURES, build_candidate_rows
from rca_ml.m13_protocol import ranking_metrics, rank_scores
from rca_ml.m13_experiment import _predict
from rca_ml.r3_dependency_overlap import OVERLAP_FEATURES, summarize_overlap, overlap_features
from r3_dependency_overlap import OUT, ROOT, RUN, read, sha, save, check_registration, compare, SEEDS


def main():
    started = time.monotonic()
    reg = read(OUT / "registration.json")
    check_registration(reg)
    assert read(OUT / "results.json")["fits"] == 12
    splits = read(OUT / "splits.json")
    healthy = read(ROOT / "ml/models/m13/healthy-baseline.json")
    summaries = read(OUT / "support.json")["healthy_summary"]
    original = read(OUT / "truth-free-matched-features.json")["overlap"]
    index = [json.loads(line) for line in (RUN / "telemetry-index.jsonl").read_text().splitlines()]
    truths = [json.loads(line) for line in (RUN / "truth.jsonl").read_text().splitlines()]
    truth = {v["incident_id"]: dict(v, system="DeathStarBench-SocialNetwork") for v in truths}
    paths = list(OUT.glob("control-*-*.json")) + list(OUT.glob("overlap-*-*.json"))
    # Include only trained fold assets, not OOF result files.
    paths = [p for p in paths if p.stem.rsplit("-", 1)[-1] in {"0", "1", "2"}]
    assert len(paths) == 12
    save("masked-v2-registration.json", {"source_sha256": sha(Path(__file__)), "protocol_sha256": sha(ROOT / "docs/R3_DEPENDENCY_OVERLAP_PROTOCOL.md"),
         "models": {p.name: sha(p) for p in paths}, "fits": 0, "modes": ["empty_observed", "source_unavailable"],
         "purpose": "diagnostic noninferiority only; no parameter selection"})
    columns = FEATURES + RANKING_FEATURES + OVERLAP_FEATURES
    masked_rows, baseline_equal = {}, 0
    for mode in ("empty_observed", "source_unavailable"):
        rows = {}
        for item in index:
            path = RUN / item["telemetry_path"]
            assert sha(path) == item["sha256"]
            payload = read(path); name = item["incident_id"]
            clean = {k: payload[k] for k in ("start_unix", "end_unix", "requests_per_second", "metrics", "traces")}
            clean["traces_collected"] = payload.get("traces_collected", True)
            services = tuple(sorted(v["service"] for v in original[name]))
            current = build_candidate_rows(clean, healthy, services)
            prior = {v["service"]: v["features"] for v in original[name]}
            # Reused context has only resource-metric inputs and frozen healthy edges,
            # independent of the incident traces. Verify the other 59 full features.
            for row in current:
                assert all(np.float32(row["features"][c]) == np.float32(prior[row["service"]][c]) for c in FEATURES)
            baseline_equal += 1
            clean["traces"] = []
            clean["traces_collected"] = mode == "empty_observed"
            current = build_candidate_rows(clean, healthy, services)
            empty = summarize_overlap([], services, clean["start_unix"] * 1e6, clean["end_unix"] * 1e6)
            extra = overlap_features(empty, summaries)
            for row in current:
                row["incident_id"] = name
                row["features"].update({c: prior[row["service"]][c] for c in RANKING_FEATURES})
                row["features"].update(extra[row["service"]])
            rows[name] = current
        masked_rows[mode] = rows
    save("truth-free-masked-v2-features.json", masked_rows)
    all_predictions, metrics, comparisons = {}, {}, {}
    for mode, rows in masked_rows.items():
        variants = {}
        for variant in ("control", "overlap"):
            if variant == "control":
                data = json.loads(json.dumps(rows))
                for candidates in data.values():
                    for row in candidates:
                        row["features"].update(dict.fromkeys(OVERLAP_FEATURES, 0.0))
            else:
                data = rows
            by_seed = []
            for seed in SEEDS:
                oof = {}
                for split in splits:
                    model = xgb.Booster()
                    model.load_model(OUT / f"{variant}-{seed}-{split['fold']}.json")
                    oof.update(_predict(model, data, split["test"], columns))
                by_seed.append(oof)
            combined = {}
            for name in truth:
                scores = defaultdict(list)
                for pred in by_seed:
                    for row in pred[name]:
                        scores[row["service"]].append(row["score"])
                combined[name] = rank_scores({s: float(np.mean(v)) for s, v in scores.items()})
            variants[variant] = combined
        all_predictions[mode] = variants
        metrics[mode] = {v: ranking_metrics(p, truth) for v, p in variants.items()}
        comparisons[mode] = compare(variants["overlap"], variants["control"], truth)
    check_registration(reg)
    save("masked-v2-predictions.json", all_predictions)
    result = {"metrics": metrics, "paired_cluster_comparison": comparisons, "fits": 0,
              "full_feature_reextraction_equal": baseline_equal, "resource_only_context_reused": True,
              "seconds": time.monotonic() - started, "scope": "same USED_DEVELOPMENT incidents, not independent tests"}
    save("masked-v2-results.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
