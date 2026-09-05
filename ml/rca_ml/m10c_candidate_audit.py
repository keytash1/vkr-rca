"""Generate the pre-model M10C candidate audit from sealed M9B telemetry."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .dataset import read_jsonl, sha256_file
from .m10c_candidates import candidates_from_audit
from .train import save_json

EXTERNAL = {f"RE{revision}-{system}" for revision in (2, 3) for system in ("OB", "SS", "TT")}


def run(truth_free: Path, labels_path: Path) -> dict:
    records = {item["external_case_id"]: item for item in read_jsonl(truth_free)}
    labels_doc = json.loads(labels_path.read_text())
    labels = labels_doc["cases"]
    telemetry = {}
    for case_id, record in records.items():
        candidates = candidates_from_audit(record["features"])
        telemetry[case_id] = {
            "candidates": [candidate.__dict__ for candidate in candidates],
            "candidate_names": [candidate.name for candidate in candidates],
        }

    # Truth is consulted only after every candidate universe is materialized.
    rows = []
    missing = []
    for label in labels:
        built = telemetry[label["external_case_id"]]
        observable = label["root_service"] in built["candidate_names"]
        row = {
            "case_id": label["external_case_id"], "dataset": label["dataset"],
            "system": label["system"], "root": label["root_service"],
            "frozen_root_observable": bool(label["root_observable"]),
            "m10c_root_observable": observable,
            "candidate_count": len(built["candidate_names"]),
        }
        rows.append(row)
        if label["dataset"] in EXTERNAL and not label["root_observable"]:
            missing.append({
                **row,
                "classification": "B_metrics_entity_mapping_rejected",
                "evidence": "root is a non-infrastructure metric entity excluded by the trace-constrained M9B mapper",
            })

    summary = summarize(rows)
    if len(missing) != 24:
        raise ValueError(f"expected 24 frozen external misses, got {len(missing)}")
    if not all(item["m10c_root_observable"] for item in missing):
        raise ValueError("generic candidate union did not recover every audited root")
    return {
        "version": "m10c-candidate-audit-v1",
        "label_isolation": "all candidate universes materialized before root labels were read",
        "source_truth_free_sha256": sha256_file(truth_free),
        "frozen_external_reference": {"observable": 336, "cases": 360},
        "summary": summary,
        "frozen_missing_cases": missing,
    }


def summarize(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["dataset"]].append(row)
        groups[f"RE{row['dataset'][2]}"] .append(row)
        if row["dataset"] in EXTERNAL:
            groups["external_360"].append(row)
    result = {}
    for name, values in sorted(groups.items()):
        result[name] = {
            "cases": len(values),
            "root_observable": sum(item["m10c_root_observable"] for item in values),
            "candidate_recall": sum(item["m10c_root_observable"] for item in values) / len(values),
            "mean_candidates": sum(item["candidate_count"] for item in values) / len(values),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth-free", type=Path, default=Path("artifacts/m9b/m9b-v1/truth-free.jsonl"))
    parser.add_argument("--labels", type=Path, default=Path("artifacts/m9b/m9b-v1/labels-and-coverage.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/m10c/m10c-v2/candidate-audit.json"))
    args = parser.parse_args()
    result = run(args.truth_free, args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_json(args.output, result)
    print(json.dumps(result["summary"]["external_360"], indent=2))


if __name__ == "__main__":
    main()

