"""Compatibility-first runner for pinned RCAEval metric/multi-source baselines."""

from __future__ import annotations

import importlib
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from .m8b_experiment import RCAEVAL_REVISION, normalize_root
from .metrics import rank_metrics

METRIC_DATASETS = ("RE2-OB", "RE2-SS", "RE2-TT", "RE3-OB", "RE3-SS", "RE3-TT")
TRACE_DATASETS = ("RE2-OB", "RE2-TT", "RE3-OB", "RE3-TT")
MULTISOURCE_INPUTS = ("logts.csv", "tracets_err.csv", "tracets_lat.csv")


def run(data_dir: Path, source: Path, index: pd.DataFrame) -> dict:
    if not source.exists():
        return {"status": "compatibility_failed", "rcaeval_revision": RCAEVAL_REVISION,
                "methods": {name: _missing_source(name) for name in ("baro", "mmbaro", "mmcirca", "mmrcd")}}
    sys.path.insert(0, str(source.resolve()))
    methods = {"baro": _run_baro(data_dir, index)}
    selected = index[index["dataset"].isin(TRACE_DATASETS) & index["has_traces"]].sort_values("case")
    smoke_case = str(selected.iloc[0]["case"])
    missing = {name: sum(not (data_dir / str(row.case) / name).exists()
                             for row in selected.itertuples(index=False))
               for name in MULTISOURCE_INPUTS}
    module_by_method = {"mmbaro": "baro", "mmcirca": "circa", "mmrcd": "mmrcd"}
    for name, module in module_by_method.items():
        importable, import_error = _import_status(module, name)
        status = "compatibility_failed_missing_upstream_inputs" if importable else "compatibility_failed_dependency_and_inputs"
        methods[name] = {
            "status": status,
            "cases_expected": len(selected), "cases_succeeded": 0,
            "documented_smoke_case": smoke_case, "entrypoint_importable": importable,
            "entrypoint_import_error": import_error,
            "smoke_stage": "blocked before invocation because required upstream-derived CSV inputs are absent",
            "failure_summary": {f"missing_{key}": value for key, value in missing.items()},
            "note": "Pinned Hugging Face cases expose raw metrics/logs/traces Parquet, but the pinned upstream "
                    "multi-source entrypoints require pre-derived logts.csv, tracets_err.csv, and tracets_lat.csv. "
                    "No upstream patch or locally invented conversion was used.",
        }
    return {"status": "completed_with_explicit_compatibility_failures",
            "rcaeval_revision": RCAEVAL_REVISION,
            "service_projection": "exact pinned RCAEval main.py split('_')[0], strip '-db', stable dedupe",
            "methods": methods}


def _run_baro(data_dir: Path, index: pd.DataFrame) -> dict:
    function = getattr(importlib.import_module("RCAEval.e2e.baro"), "baro")
    selected = index[index["dataset"].isin(METRIC_DATASETS) & (index["n_metrics"] > 0)].sort_values("case")
    cases, failures, runtimes = [], [], []
    for position, row in enumerate(selected.itertuples(index=False), 1):
        started = time.monotonic()
        try:
            frame = pd.read_parquet(data_dir / str(row.case) / "metrics.parquet")
            output = function(frame, inject_time=int(row.inject_time), dataset=str(row.dataset).lower())
            services = _project_services(output.get("ranks") or [])
            root = normalize_root(str(row.root_cause_service), str(row.dataset))
            rank = next((place for place, service in enumerate(services, 1) if service == root), 0)
            cases.append({"case": str(row.case), "dataset": str(row.dataset), "root": root,
                          "rank": rank, "service_candidates": len(services),
                          "native_candidates": len(output.get("ranks") or [])})
        except Exception as error:
            failures.append({"case": str(row.case), "error": f"{type(error).__name__}: {error}"})
        runtimes.append(time.monotonic() - started)
        if position % 25 == 0 or position == len(selected):
            print(f"official baro {position}/{len(selected)}", flush=True)
    overall = rank_metrics((value["rank"] for value in cases), total=len(selected))
    by_dataset = {dataset: {"cases": len(values), **rank_metrics((value["rank"] for value in values),
                                                                  total=sum(selected["dataset"] == dataset))}
                  for dataset in METRIC_DATASETS
                  if (values := [value for value in cases if value["dataset"] == dataset])}
    return {"status": "success" if not failures else "partial_failure",
            "cases_expected": len(selected), "cases_succeeded": len(cases),
            "metrics": {"overall": {"cases": len(selected), **overall}, "by_dataset": by_dataset},
            "runtime_seconds": {"total": sum(runtimes), "mean": sum(runtimes) / max(1, len(runtimes))},
            "failure_summary": dict(Counter(value["error"] for value in failures)),
            "failures": failures, "cases": cases,
            "note": "Unmodified pinned RCAEval BARO; unavailable projected roots count as misses."}


def _project_services(native: list) -> list[str]:
    services = []
    for value in native:
        service = str(value).split("_")[0].replace("-db", "")
        if service not in services:
            services.append(service)
    return services


def _import_status(module: str, name: str) -> tuple[bool, str | None]:
    try:
        getattr(importlib.import_module(f"RCAEval.e2e.{module}"), name)
        return True, None
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def _missing_source(name: str) -> dict:
    return {"status": "compatibility_failed_missing_source", "cases_expected": 0,
            "cases_succeeded": 0, "note": f"Pinned source unavailable for {name}."}
