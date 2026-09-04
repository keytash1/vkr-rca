"""Run supported pinned RCAEval trace baselines without modifying upstream code."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

from .m8b_experiment import DATASETS, normalize_root
from .metrics import rank_metrics
from .train import save_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rcaeval-source", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("external-data/rcaeval"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/m8b/m8b-external-v1/official-baselines.json"))
    parser.add_argument("--method", choices=("tracerca",), default="tracerca")
    args = parser.parse_args()
    save_json(args.output, run(args))


def run(args: argparse.Namespace) -> dict:
    sys.path.insert(0, str(args.rcaeval_source))
    function = getattr(importlib.import_module(f"RCAEval.e2e.{args.method}"), args.method)
    index = pd.read_parquet(args.data_dir / "cases.parquet")
    selected = index[index["dataset"].isin(DATASETS) & index["has_traces"]].sort_values("case")
    ranks, cases, failures, runtimes = [], [], [], []
    for position, row in enumerate(selected.itertuples(index=False), 1):
        started = time.monotonic()
        try:
            frame = pd.read_parquet(args.data_dir / str(row.case) / "traces.parquet")
            output = function(frame, inject_time=int(row.inject_time) * 1_000_000, dataset=str(row.dataset).lower())
            native = output.get("ranks") or []
            # Exact coarse conversion used by pinned RCAEval main.py:516-527.
            services = []
            for value in native:
                service = str(value).split("_")[0].replace("-db", "")
                if service not in services:
                    services.append(service)
            root = normalize_root(str(row.root_cause_service), str(row.dataset))
            rank = next((index + 1 for index, service in enumerate(services) if service == root), 0)
            ranks.append(rank)
            cases.append({"case": str(row.case), "dataset": str(row.dataset), "root": root,
                          "rank": rank, "native_candidates": len(native), "service_candidates": len(services)})
        except Exception as error:  # upstream compatibility failures remain explicit
            failures.append({"case": str(row.case), "error": f"{type(error).__name__}: {error}"})
        runtimes.append(time.monotonic() - started)
        print(f"official {args.method} {position}/{len(selected)}", flush=True)
    return {
        "rcaeval_revision": "405c8fd24071af41ceb4b3aabb451e5e3e15d6c6",
        "method": args.method,
        "cases_expected": len(selected),
        "cases_succeeded": len(cases),
        "failures": failures,
        "metrics_over_succeeded": rank_metrics(ranks),
        "runtime_seconds": {"total": sum(runtimes), "mean": sum(runtimes) / max(1, len(runtimes))},
        "projection": "exact pinned RCAEval main.py coarse service conversion",
        "cases": cases,
    }


if __name__ == "__main__":
    main()
