#!/usr/bin/env python3
"""Derive frozen RE1-only preprocessing state before any M12 predictions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

from rca_ml.m10c_experiment import RE1, load_rows  # noqa: E402
from rca_ml.m10d_integration_experiment import _legacy_vectors, _sanitize_rows  # noqa: E402
from rca_ml.m10d_reranker import fit_ood_stats  # noqa: E402


def main() -> None:
    _, rows, ids = load_rows(
        ROOT / "artifacts/m10c/m10c-v2/truth-free.jsonl",
        ROOT / "artifacts/m10c/m10c-v2/truth-free-seal.json",
        ROOT / "external-data/rcaeval/cases.parquet",
    )
    clean = _sanitize_rows(rows, _legacy_vectors(ROOT / "artifacts/m9b/m9b-v1/truth-free.jsonl"))
    development_ids = sorted(sum((ids[name] for name in RE1), []))
    output = {
        "version": "m12-frozen-re1-ood-v1",
        "source_roles": ["DEVELOPMENT_EXISTING"],
        "source_datasets": list(RE1),
        "development_incidents": len(development_ids),
        "m12_incidents": 0,
        "stats": fit_ood_stats(clean, development_ids),
    }
    (ROOT / "ml/models/m12/ood-stats.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
