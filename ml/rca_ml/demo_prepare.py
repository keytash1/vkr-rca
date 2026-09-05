"""Prepare the deterministic, offline M10B RCAEval replay cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .dataset import read_jsonl, sha256_file
from .demo_predict import predict_prepared
from .m8b_adapter import audit_schema, run_adapter
from .m8b_experiment import BASE_URL, HF_REVISION, INDEX_SHA256, RCAEVAL_REVISION, _download, normalize_root
from .m9b_features import extract_case_features
from .train import save_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--data-dir", type=Path, default=Path("external-data/rcaeval"))
    parser.add_argument("--output", type=Path, default=Path("demo-data"))
    parser.add_argument("--binary", type=Path, default=Path("/tmp/vkr-rca-demo-offline-rca"))
    args = parser.parse_args()
    result = prepare(args.root, args.data_dir, args.output, args.binary)
    print(json.dumps(result, indent=2, sort_keys=True))


def prepare(root: Path, data_dir: Path, output: Path, binary: Path) -> dict:
    freeze = verify_frozen(root)
    selection_path = root / "demo/cases.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    validate_selection(selection)
    data_dir.mkdir(parents=True, exist_ok=True)
    index_path = data_dir / "cases.parquet"
    _download(f"{BASE_URL}/cases.parquet", index_path)
    if sha256_file(index_path) != INDEX_SHA256:
        raise ValueError("pinned RCAEval cases index hash mismatch")

    public_index = pd.read_parquet(
        index_path,
        columns=["case", "dataset", "system", "inject_time", "has_traces", "n_traces", "n_metrics"],
    )
    public_rows = {str(row.case): row for row in public_index.itertuples(index=False)}
    selected_ids = [value["id"] for value in selection["cases"]]
    if any(case_id not in public_rows for case_id in selected_ids):
        raise ValueError("showcase case missing from pinned RCAEval index")

    sealed_records = optional_sealed_records(root)
    prepared_entries = []
    for spec in selection["cases"]:
        case_id = spec["id"]
        row = public_rows[case_id]
        if str(row.dataset) != spec["dataset"] or not bool(row.has_traces) or int(row.n_metrics) <= 0:
            raise ValueError(f"showcase metadata mismatch for {case_id}")
        case_dir = data_dir / case_id
        metric_path = case_dir / "metrics.parquet"
        trace_path = case_dir / "traces.parquet"
        _download(f"{BASE_URL}/{case_id}/metrics.parquet", metric_path)
        _download(f"{BASE_URL}/{case_id}/traces.parquet", trace_path)
        trace_audit = audit_schema(trace_path)
        fault = run_adapter(
            trace_path,
            external_case_id=case_id,
            inject_unix=int(row.inject_time),
            mode="fault",
            binary=binary,
        )
        features = extract_case_features(metric_path, int(row.inject_time), fault["features"])
        if features.get("schema_version") != "m9b-v1":
            raise ValueError(f"unexpected feature schema for {case_id}")
        if case_id in sealed_records and features != sealed_records[case_id]["features"]:
            raise ValueError(f"prepared features differ from sealed M9B features for {case_id}")

        prepared = {
            "version": "m10b-prepared-case-v1",
            "external_case_id": case_id,
            "dataset": str(row.dataset),
            "system": spec["system"],
            "incident_timestamp": int(row.inject_time),
            "source": {
                "rcaeval_commit": RCAEVAL_REVISION,
                "hf_revision": HF_REVISION,
                "index_sha256": INDEX_SHA256,
                "metrics_sha256": sha256_file(metric_path),
                "traces_sha256": sha256_file(trace_path),
                "trace_rows": trace_audit["rows"],
            },
            "features": features,
        }
        case_output = output / "cases" / case_id
        input_path = case_output / "input.json"
        prediction_path = case_output / "prediction.json"
        save_json(input_path, prepared)
        prediction = predict_prepared(prepared, root)
        if prediction["model"]["route"] != spec["model_route"]:
            raise ValueError(f"frozen model routing mismatch for {case_id}")
        if prediction["ranking"][0]["service"] != spec["expected_top1"]:
            raise ValueError(f"frozen Top-1 mismatch for {case_id}")
        save_json(prediction_path, prediction)
        prepared_entries.append({
            "id": case_id,
            "title": spec["title"],
            "dataset": str(row.dataset),
            "system": spec["system"],
            "incident_timestamp": int(row.inject_time),
            "candidate_count": prediction["candidate_count"],
            "telemetry": prediction["telemetry"],
            "model": prediction["model"],
            "prediction_sha256": sha256_file(prediction_path),
        })

    # Labels are loaded only after every truth-free input and prediction is persisted.
    label_index = pd.read_parquet(index_path)
    labels = {str(row.case): row for row in label_index.itertuples(index=False)}
    outcomes = {"success": 0, "miss": 0}
    for spec in selection["cases"]:
        case_id = spec["id"]
        label = labels[case_id]
        prediction = json.loads((output / "cases" / case_id / "prediction.json").read_text(encoding="utf-8"))
        root_service = normalize_root(str(label.root_cause_service), str(label.dataset))
        actual_rank = next((value["rank"] for value in prediction["ranking"] if value["service"] == root_service), 0)
        if actual_rank != spec["expected_actual_rank"]:
            raise ValueError(f"frozen actual-rank mismatch for {case_id}: {actual_rank}")
        correct = actual_rank == 1
        outcomes["success" if correct else "miss"] += 1
        truth = {
            "external_case_id": case_id,
            "root_service": root_service,
            "fault_family": str(label.fault),
            "actual_rank": actual_rank,
            "top1_correct": correct,
            "predicted_top1": prediction["ranking"][0]["service"],
        }
        save_json(output / "cases" / case_id / "truth.json", truth)

    public_manifest = {
        "version": selection["version"],
        "source": {"rcaeval_commit": RCAEVAL_REVISION, "hf_revision": HF_REVISION, "index_sha256": INDEX_SHA256},
        "cases": prepared_entries,
        "truth_isolation": "prediction inputs and outputs are persisted before labels are loaded",
    }
    manifest_path = output / "manifest.json"
    save_json(manifest_path, public_manifest)
    integrity = {
        "version": "m10b-demo-cache-v1",
        "selection_sha256": sha256_file(selection_path),
        "manifest_sha256": sha256_file(manifest_path),
        "frozen_research": freeze,
        "case_count": len(prepared_entries),
        "outcomes": outcomes,
        "prediction_sha256": {value["id"]: value["prediction_sha256"] for value in prepared_entries},
    }
    save_json(output / "integrity.json", integrity)
    return integrity


def verify_frozen(root: Path) -> dict:
    manifest = json.loads((root / "demo/frozen-research.json").read_text(encoding="utf-8"))
    mismatches = []
    for relative, expected in manifest["files"].items():
        path = root / relative
        actual = sha256_file(path) if path.is_file() else "missing"
        if actual != expected:
            mismatches.append({"path": relative, "expected": expected, "actual": actual})
    if mismatches:
        raise ValueError(f"frozen research artifact mismatch: {mismatches}")
    return {"status": "identical", "files": len(manifest["files"]), "freeze_commit": manifest["freeze_commit"]}


def validate_selection(selection: dict) -> None:
    if selection.get("rcaeval_commit") != RCAEVAL_REVISION or selection.get("hf_revision") != HF_REVISION:
        raise ValueError("showcase source pin mismatch")
    if selection.get("cases_index_sha256") != INDEX_SHA256:
        raise ValueError("showcase index pin mismatch")
    cases = selection.get("cases", [])
    ids = [value.get("id") for value in cases]
    if len(cases) < 8 or len(ids) != len(set(ids)):
        raise ValueError("showcase needs at least eight unique cases")
    misses = sum(int(value.get("expected_actual_rank", 0)) != 1 for value in cases)
    if misses < 2:
        raise ValueError("showcase must include at least two frozen misses")


def optional_sealed_records(root: Path) -> dict[str, dict]:
    path = root / "artifacts/m9b/m9b-v1/truth-free.jsonl"
    seal_path = root / "artifacts/m9b/m9b-v1/truth-free-seal.json"
    if not path.is_file() or not seal_path.is_file():
        return {}
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if sha256_file(path) != seal.get("sha256") or not seal.get("sealed_before_label_join"):
        raise ValueError("local M9B truth-free cache is not sealed")
    return {record["external_case_id"]: record for record in read_jsonl(path)}


if __name__ == "__main__":
    main()
