#!/usr/bin/env python3
"""Seal the M12 protocol after data generation and before model prediction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from rca_ml.dataset import sha256_file  # noqa: E402


def main() -> None:
    output = ROOT / "ml/models/m12/freeze-manifest.json"
    if output.exists():
        raise SystemExit("M12 freeze already exists")
    preflight = json.loads((ROOT / "ml/models/m12/preflight.json").read_text())
    for name, expected in preflight["sha256"].items():
        actual = sha256_file(ROOT / name)
        if actual != expected:
            raise SystemExit(f"preflight hash mismatch: {name}: {actual} != {expected}")
    run_dir = ROOT / "external-data/m12/runs/locked-v1"
    required = [
        ROOT / "deploy/m12/compose.yml", ROOT / "deploy/m12/config.json",
        ROOT / "deploy/m12/prometheus.yml", ROOT / "deploy/m12/workload.json",
        ROOT / "deploy/m12/Dockerfile.hotel", ROOT / "deploy/m12/Dockerfile.exporter",
        ROOT / "deploy/m12/exporter/main.go", ROOT / "docs/m12-protocol.md",
        ROOT / "ml/rca_ml/m12_adapter.py", ROOT / "ml/rca_ml/m12_evaluate.py",
        ROOT / "ml/rca_ml/m12_report.py", ROOT / "ml/rca_ml/m12_shadow.py",
        ROOT / "scripts/m12/run.py", ROOT / "scripts/m12/workload.py",
        ROOT / "ml/models/m12/ood-stats.json",
        ROOT / "ml/models/m12/incident-plan.json", run_dir / "healthy/baseline.json",
        run_dir / "canary/validity.json", run_dir / "locked/telemetry-index.jsonl",
        run_dir / "locked/truth.sealed.jsonl", ROOT / "ml/models/m12/trace-audit.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"cannot freeze; missing: {missing}")
    canary = json.loads((run_dir / "canary/validity.json").read_text())
    if canary["rankings_generated"] or not all(item["valid"] for item in canary["results"]):
        raise SystemExit("canary gate failed")
    index = (run_dir / "locked/telemetry-index.jsonl").read_text().splitlines()
    if len(index) != 50:
        raise SystemExit(f"locked denominator must be 50, got {len(index)}")
    manifest = {
        "version": "m12-freeze-v1", "frozen_before_locked_predictions": True,
        "source_commit": "6ecb09706140f8730b5385c08f1386c654c3c526",
        "service_universe": ["frontend", "profile", "search", "geo", "rate", "recommendation", "user", "reservation"],
        "target_services": ["frontend", "search", "geo", "rate", "recommendation"],
        "fault_catalogue": ["cpu", "memory", "network_latency", "packet_loss", "service_unavailable"],
        "top_k": 5, "execution_seed": 20260906, "model_training_count": 0,
        "evaluation_metrics": ["candidate_universe_coverage", "AC@1", "AC@2", "AC@3", "AC@5", "AC@10", "MRR"],
        "bootstrap": {"incident_resamples": 10000, "cluster_resamples": 10000, "cluster_key": ["root_service", "fault_family"], "seed": 20260906},
        "locked_truth_sha256": sha256_file(run_dir / "locked/truth.sealed.jsonl"),
        "locked_telemetry_index_sha256": sha256_file(run_dir / "locked/telemetry-index.jsonl"),
        "files": {str(path.relative_to(ROOT)): sha256_file(path) for path in required if path.is_relative_to(ROOT)},
        "external_files": {str(path.relative_to(run_dir)): sha256_file(path) for path in required if not path.is_relative_to(ROOT)},
        "frozen_model_hashes": preflight["sha256"],
        "claim_gates": "docs/m12-protocol.md",
    }
    failed_freeze = ROOT / "ml/models/m12/freeze-manifest-attempt-1.json"
    failed_predictions = run_dir / "locked/sealed-predictions.json"
    if failed_freeze.exists():
        if not failed_predictions.exists():
            raise SystemExit("failed-attempt freeze exists without its sealed predictions")
        manifest["recovery_from_failed_attempt"] = {
            "reason": "denominator assertion attempted set(dict) and raised TypeError before metrics or verdicts",
            "failed_freeze_sha256": sha256_file(failed_freeze),
            "sealed_predictions_sha256": sha256_file(failed_predictions),
            "models_or_adapter_changed": False,
            "prediction_change_allowed": False,
        }
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"freeze_sha256": sha256_file(output), "locked_incidents": len(index)}, indent=2))


if __name__ == "__main__":
    main()
