"""Locked, resumable M8B external zero-shot experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from .dataset import feature_rows, sha256_file
from .m8b_adapter import PROTOCOL_VERSION, run_adapter
from .metrics import rank_metrics
from .predict import predict_snapshot
from .train import load_model

RCAEVAL_REVISION = "405c8fd24071af41ceb4b3aabb451e5e3e15d6c6"
HF_REVISION = "afeacb11bcc94dadfd1c8f483ee4377b2b8b614e"
INDEX_SHA256 = "c49a288920dbba2e8e724679a14636d5c7eb2b45426bba14007ef79a6c0ab1bb"
MODEL_SHA256 = "3728eb0454e46d14265d092d3d17088bc32fe44e8c9cb8d565aa8e934cee7699"
DATASETS = ("RE2-OB", "RE2-TT", "RE3-OB", "RE3-TT")
BASE_URL = f"https://huggingface.co/datasets/phamquiluan/RCAEval/resolve/{HF_REVISION}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("external-data/rcaeval"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/m8b/m8b-external-v1"))
    parser.add_argument("--binary", type=Path, default=Path("/tmp/vkr-rca-m8b-offline-rca"))
    parser.add_argument("--model", type=Path, default=Path("ml/models/m7-lambdamart-v1/model.json"))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    run(args)


def run(args) -> dict:
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    index_path = args.data_dir / "cases.parquet"
    _download(f"{BASE_URL}/cases.parquet", index_path)
    if sha256_file(index_path) != INDEX_SHA256:
        raise ValueError("pinned RCAEval index hash mismatch")
    if sha256_file(args.model) != MODEL_SHA256:
        raise ValueError("frozen M7 model hash mismatch")
    generation_index = pd.read_parquet(
        index_path, columns=["case", "dataset", "inject_time", "has_traces", "n_traces"]
    )
    selected = generation_index[
        generation_index["dataset"].isin(DATASETS) & generation_index["has_traces"]
    ].sort_values("case")
    if len(selected) != 240:
        raise ValueError(f"expected 240 trace-capable cases, got {len(selected)}")
    if args.limit:
        selected = selected.head(args.limit)
    manifest_path = args.artifact_dir / "generation-manifest.json"
    manifest = _generation_manifest(selected)
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("existing run uses a different locked manifest")
    _write_json(manifest_path, manifest)

    truth_free_path = args.artifact_dir / "truth-free.jsonl"
    existing = _read_jsonl(truth_free_path)
    completed = {record["external_case_id"] for record in existing}
    model = load_model(args.model)
    with truth_free_path.open("a", encoding="utf-8") as output:
        for position, row in enumerate(selected.itertuples(index=False), 1):
            case_id = str(row.case)
            if case_id in completed:
                continue
            case_dir = args.data_dir / case_id
            trace_path = case_dir / "traces.parquet"
            _download(f"{BASE_URL}/{case_id}/traces.parquet", trace_path)
            telemetry_sha = sha256_file(trace_path)
            fault = run_adapter(
                trace_path,
                external_case_id=case_id,
                inject_unix=int(row.inject_time),
                mode="fault",
                binary=args.binary,
            )
            healthy = run_adapter(
                trace_path,
                external_case_id=case_id,
                inject_unix=int(row.inject_time),
                mode="healthy",
                binary=args.binary,
            )
            record = {
                "external_case_id": case_id,
                "dataset": str(row.dataset),
                "telemetry_sha256": telemetry_sha,
                "source_trace_rows": int(row.n_traces),
                "fault": fault,
                "healthy": healthy,
                "frozen_m7": predict_snapshot(model, fault["features"]),
            }
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            output.flush()
            os.fsync(output.fileno())
            print(f"generated {position}/{len(selected)} {case_id}", flush=True)
    records = _read_jsonl(truth_free_path)
    if len(records) != len(selected):
        raise ValueError(f"truth-free output incomplete: {len(records)}/{len(selected)}")
    seal = {
        "protocol_version": PROTOCOL_VERSION,
        "records": len(records),
        "truth_free_sha256": sha256_file(truth_free_path),
        "sealed_before_truth_join": True,
    }
    _write_json(args.artifact_dir / "truth-free-seal.json", seal)
    labels_index = pd.read_parquet(index_path)
    evaluation = evaluate(records, labels_index, seal)
    _write_json(args.artifact_dir / "evaluation.json", evaluation)
    return evaluation


def evaluate(records: list[dict], index: pd.DataFrame, seal: dict) -> dict:
    truth = {str(row.case): row for row in index.itertuples(index=False)}
    cases = []
    for record in records:
        label = truth[record["external_case_id"]]
        fault = record["fault"]
        features = fault["features"]
        root_raw = str(label.root_cause_service)
        root = normalize_root(root_raw, str(label.dataset))
        services = {value["service"] for value in features.get("services", [])}
        ready = set(features.get("ready_universe") or [])
        observed = set(features.get("observed_anomalies") or [])
        detected = features.get("state") == "ready"
        root_observable = root in services
        root_ready = root in ready
        if not root_observable:
            status = "root_not_observable"
        elif features.get("state") == "insufficient_current_data":
            operation_states = {value["state"] for value in fault["anomalies"].get("operations", [])}
            status = "insufficient_baseline" if operation_states == {"insufficient_baseline"} else "insufficient_current"
        elif not detected:
            status = "detection_miss"
        else:
            status = "ready"
        rankings = {name: value for name, value in fault["rca"]["rankings"].items()}
        rankings["frozen_m7"] = record["frozen_m7"]["ranking"]
        ranks = {name: _rank(value, root) for name, value in rankings.items()}
        ml_scores = [float(value["ml_score"]) for value in rankings["frozen_m7"]]
        root_vector = next((value for value in features.get("services", []) if value["service"] == root), None)
        cases.append(
            {
                "external_case_id": record["external_case_id"],
                "dataset": str(label.dataset),
                "suite": str(label.suite),
                "system": str(label.system),
                "fault_type": str(label.fault),
                "root_raw": root_raw,
                "root_service": root,
                "status": status,
                "detected": detected,
                "root_observable": root_observable,
                "root_ready": root_ready,
                "root_observed_anomaly": root in observed,
                "localization_eligible": detected and root_ready,
                "ranks": ranks,
                "score_margin": ml_scores[0] - ml_scores[1] if len(ml_scores) >= 2 else 0.0,
                "candidate_count": len(ready),
                "coverage": fault["coverage"],
                "healthy_false_positive": record["healthy"]["features"].get("state") == "ready",
                "root_vector": root_vector,
            }
        )
    groups = {dataset: summarize([case for case in cases if case["dataset"] == dataset]) for dataset in DATASETS}
    groups["overall"] = summarize(cases)
    fault_groups = {
        f"{dataset}:{fault}": summarize([case for case in cases if case["dataset"] == dataset and case["fault_type"] == fault])
        for dataset in DATASETS
        for fault in sorted({case["fault_type"] for case in cases if case["dataset"] == dataset})
    }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "source": {"rcaeval_revision": RCAEVAL_REVISION, "hf_revision": HF_REVISION},
        "truth_free_seal": seal,
        "coverage": {"expected": 240, "evaluated": len(cases), "status_counts": dict(Counter(case["status"] for case in cases))},
        "by_dataset": groups,
        "by_fault": fault_groups,
        "cases": cases,
    }


def summarize(cases: list[dict]) -> dict:
    eligible = [case for case in cases if case["localization_eligible"]]
    methods = ("chance", "max_severity", "topology_consistency", "local_evidence", "hybrid_v1", "frozen_m7")
    metrics = {}
    for method in methods:
        if method == "chance":
            ranks = []
        else:
            ranks = [case["ranks"].get(method, 0) for case in eligible]
        metrics[method] = rank_metrics(ranks, total=len(eligible)) if method != "chance" else {
            "ac_at_1": sum((1 / case["candidate_count"] if case["candidate_count"] else 0) for case in eligible) / max(1, len(eligible)),
            "ac_at_3": sum((min(3, case["candidate_count"]) / case["candidate_count"] if case["candidate_count"] else 0) for case in eligible) / max(1, len(eligible)),
            "mrr": sum((sum(1 / rank for rank in range(1, case["candidate_count"] + 1)) / case["candidate_count"]
                        if case["candidate_count"] else 0) for case in eligible) / max(1, len(eligible)),
            "ndcg_at_1": sum((1 / case["candidate_count"] if case["candidate_count"] else 0) for case in eligible) / max(1, len(eligible)),
            "ndcg_at_3": sum((sum(1 / math.log2(rank + 1) for rank in range(1, min(3, case["candidate_count"]) + 1))
                              / case["candidate_count"] if case["candidate_count"] else 0) for case in eligible) / max(1, len(eligible)),
        }
    end_to_end = sum(case["detected"] and case["root_ready"] and case["ranks"].get("frozen_m7") == 1 for case in cases) / max(1, len(cases))
    margins = sorted(case["score_margin"] for case in eligible)
    return {
        "cases": len(cases),
        "status_counts": dict(Counter(case["status"] for case in cases)),
        "detection_recall": sum(case["detected"] for case in cases) / max(1, len(cases)),
        "root_observable_coverage": sum(case["root_observable"] for case in cases) / max(1, len(cases)),
        "localization_eligible": len(eligible),
        "healthy_fpr": sum(case["healthy_false_positive"] for case in cases) / max(1, len(cases)),
        "end_to_end_ac_at_1": end_to_end,
        "methods": metrics,
        "feature_coverage": {
            "error_evidence_mean": _mean(case["coverage"]["error_evidence_coverage"] for case in cases),
            "exclusive_trace_mean": _mean(case["coverage"]["exclusive_trace_coverage"] for case in cases),
            "parent_match_mean": _mean(case["coverage"]["parent_match_rate"] for case in cases),
        },
        "score_margins": {
            "median": _percentile(margins, 0.5),
            "p10": _percentile(margins, 0.1),
            "exact_ties": sum(value == 0 for value in margins) / max(1, len(margins)),
            "near_ties": sum(value < 1e-6 for value in margins) / max(1, len(margins)),
        },
    }


def normalize_root(value: str, dataset: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if dataset.endswith("-OB") and normalized == "frontend":
        return "frontendservice"
    return normalized


def _rank(ranking: list[dict], root: str) -> int:
    return next((int(value["rank"]) for value in ranking if value["service"] == root), 0)


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    return values[round((len(values) - 1) * fraction)]


def _generation_manifest(selected: pd.DataFrame) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "rcaeval_revision": RCAEVAL_REVISION,
        "hf_revision": HF_REVISION,
        "index_sha256": INDEX_SHA256,
        "frozen_m7_sha256": MODEL_SHA256,
        "external_case_ids": selected["case"].astype(str).tolist(),
    }


def _download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "vkr-rca-m8b/1"})
            with urllib.request.urlopen(request, timeout=120) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            os.replace(temporary, destination)
            return
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
