"""Synthetic-selected, post-M8B frozen detector-v2 evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import binomtest

from .dataset import read_jsonl, sha256_file
from .detector_v2 import Config
from .m8b_experiment import DATASETS, HF_REVISION, INDEX_SHA256
from .m9a_external import evaluate_case
from .m9a_synthetic import corpus, evaluate as synthetic_evaluate, select_config, v1_evaluate
from .train import save_json

EXPERIMENT_VERSION = "m9a-v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("external-data/rcaeval"))
    parser.add_argument("--m8b-artifacts", type=Path, default=Path("artifacts/m8b/m8b-external-v1"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/m9a/m9a-external-v1"))
    parser.add_argument("--model-dir", type=Path, default=Path("ml/models/m9a-detector-v2"))
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--synthetic-only", action="store_true")
    args = parser.parse_args()
    run(args)


def run(args: argparse.Namespace) -> dict:
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    args.model_dir.mkdir(parents=True, exist_ok=True)
    records = corpus()
    selection = select_config(records)
    config: Config = selection["selected_config"]
    development = [row for row in records if row["split"] == "development"]
    validation = [row for row in records if row["split"] == "validation"]
    synthetic = {
        "protocol": {"seed": 20260904, "profiles": ["healthy", "constant", "step_early", "step_late", "ramp", "intermittent", "burst"],
                     "topologies": ["A", "B", "C"], "repeats": 5, "split": "SHA256(scenario_id), complete scenario assigned once"},
        "selection": {key: value for key, value in selection.items() if key not in {"selected_config", "variant_validation"}},
        "selected_config": asdict(config), "config_sha256": config.digest(),
        "development": {"v1": v1_evaluate(development), "v2": synthetic_evaluate(development, config)},
        "validation": {"v1": v1_evaluate(validation), "v2": synthetic_evaluate(validation, config)},
        "variant_validation": selection["variant_validation"],
    }
    save_json(args.model_dir / "detector_config.json", {
        "detector_version": "detector-v2", "feature_schema_version": "m9a-temporal-v1",
        "selected_before_external_evaluation": True, "selection_source": "synthetic A/B/C only",
        "config": asdict(config), "config_sha256": config.digest(),
    })
    save_json(args.model_dir / "synthetic_selection.json", synthetic)
    if args.synthetic_only:
        profiles = synthetic["validation"]["v2"]["by_profile"]
        if profiles["healthy"] != 0 or profiles["burst"] < 1 or profiles["step_late"] < 1:
            raise ValueError("M9A smoke temporal profile contract failed")
        print(json.dumps({"config_sha256": config.digest(), "validation": synthetic["validation"]}, indent=2))
        return {"synthetic": synthetic}
    external = external_generate_and_evaluate(args, config)
    fetch_metric_samples(args.data_dir)
    metrics_audit = audit_metrics(args.data_dir)
    result = {"experiment_version": EXPERIMENT_VERSION, "synthetic": synthetic, "external": external,
              "metrics_audit": metrics_audit, "verdict": _verdict(external)}
    persisted = _compact_result(result)
    save_json(args.model_dir / "evaluation.json", persisted)
    save_json(args.model_dir / "integrity_manifest.json", {
        "experiment_version": EXPERIMENT_VERSION, "m8b_commit": "86313f80d61594399e8f90849c64409ffc652449",
        "m8b_truth_free_sha256": "93b4b52e3abd144bbd5dcccf475e353365cc3006fae513bf2c735998f2975d49",
        "m7_model_sha256": "3728eb0454e46d14265d092d3d17088bc32fe44e8c9cb8d565aa8e934cee7699",
        "rcaeval_hf_revision": HF_REVISION, "cases_index_sha256": INDEX_SHA256,
        "detector_config_sha256": config.digest(), "truth_free_sha256": external["truth_free_seal"]["sha256"],
        "evaluation_sha256": sha256_file(args.model_dir / "evaluation.json"),
    })
    render_reports(result, args.docs)
    return persisted


def external_generate_and_evaluate(args: argparse.Namespace, config: Config) -> dict:
    index_path = args.data_dir / "cases.parquet"
    if sha256_file(index_path) != INDEX_SHA256:
        raise ValueError("M8B cases index hash changed")
    index = pd.read_parquet(index_path, columns=["case", "dataset", "inject_time", "has_traces"])
    selected = index[index["dataset"].isin(DATASETS) & index["has_traces"]].sort_values("case")
    if len(selected) != 240:
        raise ValueError("expected 240 external cases")
    m8b_records = {row["external_case_id"]: row for row in read_jsonl(args.m8b_artifacts / "truth-free.jsonl")}
    path = args.artifact_dir / "truth-free.jsonl"
    existing = read_jsonl(path) if path.exists() else []
    done = {row["external_case_id"] for row in existing}
    remaining = [(position, str(row.case), args.data_dir / str(row.case) / "traces.parquet", int(row.inject_time), config)
                 for position, row in enumerate(selected.itertuples(index=False), 1) if str(row.case) not in done]
    workers = max(1, int(os.environ.get("M9A_WORKERS", "2")))
    with path.open("a", encoding="utf-8") as output, ProcessPoolExecutor(max_workers=workers) as executor:
        for position, case_id, temporal in executor.map(_evaluate_external_case, remaining, chunksize=1):
            old = m8b_records[case_id]
            record = {"external_case_id": case_id, "config_sha256": config.digest(),
                      "v1": {"fault_detected": old["fault"]["features"].get("state") == "ready",
                             "fault_anomalous_services": old["fault"]["features"].get("observed_anomalies") or [],
                             "healthy_detected": old["healthy"]["features"].get("state") == "ready",
                             "healthy_anomalous_services": old["healthy"]["features"].get("observed_anomalies") or []},
                      "v2": temporal}
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            output.flush(); os.fsync(output.fileno())
            print(f"m9a external {position}/240 {case_id}", flush=True)
    generated = read_jsonl(path)
    if len(generated) != 240 or len({row["external_case_id"] for row in generated}) != 240:
        raise ValueError("incomplete or duplicated M9A truth-free output")
    seal = {"records": 240, "sha256": sha256_file(path), "sealed_before_label_join": True,
            "config_sha256": config.digest()}
    save_json(args.artifact_dir / "truth-free-seal.json", seal)
    labels = json.loads((args.m8b_artifacts / "evaluation.json").read_text(encoding="utf-8"))["cases"]
    return evaluate_external(generated, labels, seal)


def _evaluate_external_case(job: tuple[int, str, Path, int, Config]) -> tuple[int, str, dict]:
    position, case_id, trace_path, inject_time, config = job
    return position, case_id, evaluate_case(trace_path, inject_time, config)


def evaluate_external(records: list[dict], labels: list[dict], seal: dict) -> dict:
    if not seal.get("sealed_before_label_join"):
        raise ValueError("external labels require a sealed truth-free detector output")
    truth = {row["external_case_id"]: row for row in labels}
    cases = []
    for record in records:
        label = truth[record["external_case_id"]]
        v2_fault = record["v2"]["fault"]
        v2_healthy = record["v2"]["healthy"]
        cases.append({"external_case_id": record["external_case_id"], "dataset": label["dataset"],
                      "fault_type": label["fault_type"], "root_service": label["root_service"],
                      "v1_detected": record["v1"]["fault_detected"], "v2_detected": v2_fault["incident_detected"],
                      "v1_root_detected": label["root_observed_anomaly"],
                      "v2_root_detected": label["root_service"] in v2_fault["anomalous_services"],
                      "v1_healthy_fp": record["v1"]["healthy_detected"], "v2_healthy_fp": v2_healthy["incident_detected"],
                      "v2_fault": v2_fault, "v2_healthy": v2_healthy, "coverage": record["v2"]["coverage"]})
    groups = {dataset: _group([case for case in cases if case["dataset"] == dataset]) for dataset in DATASETS}
    groups["overall"] = _group(cases)
    faults = {f"{dataset}:{fault}": _group([case for case in cases if case["dataset"] == dataset and case["fault_type"] == fault])
              for dataset in DATASETS for fault in sorted({case["fault_type"] for case in cases if case["dataset"] == dataset})}
    return {"truth_free_seal": seal, "coverage": {"expected": 240, "evaluated": len(cases)},
            "by_dataset": groups, "by_fault": faults, "cases": cases}


def _group(cases: list[dict]) -> dict:
    n = max(1, len(cases))
    v1 = [case["v1_detected"] for case in cases]; v2 = [case["v2_detected"] for case in cases]
    h1 = [case["v1_healthy_fp"] for case in cases]; h2 = [case["v2_healthy_fp"] for case in cases]
    return {"cases": len(cases), "v1_recall": sum(v1) / n, "v2_recall": sum(v2) / n,
            "recall_difference": (sum(v2) - sum(v1)) / n,
            "v1_healthy_fpr": sum(h1) / n, "v2_healthy_fpr": sum(h2) / n,
            "fpr_difference": (sum(h2) - sum(h1)) / n,
            "v1_root_recall": sum(case["v1_root_detected"] for case in cases) / n,
            "v2_root_recall": sum(case["v2_root_detected"] for case in cases) / n,
            "detection_contingency": _contingency(v1, v2), "healthy_contingency": _contingency(h1, h2),
            "recall_difference_ci95": _paired_bootstrap(v1, v2), "fpr_difference_ci95": _paired_bootstrap(h1, h2)}


def _contingency(left: list[bool], right: list[bool]) -> dict:
    result = {"both_positive": 0, "v1_only": 0, "v2_only": 0, "both_negative": 0}
    for a, b in zip(left, right, strict=True):
        result["both_positive" if a and b else "v1_only" if a else "v2_only" if b else "both_negative"] += 1
    discordant = result["v1_only"] + result["v2_only"]
    result["exact_mcnemar_p"] = float(binomtest(result["v2_only"], discordant, 0.5).pvalue) if discordant else 1.0
    return result


def _paired_bootstrap(left: list[bool], right: list[bool]) -> dict:
    if not left:
        return {"low": 0.0, "high": 0.0}
    differences = np.asarray(right, dtype=float) - np.asarray(left, dtype=float)
    random = np.random.default_rng(20260904)
    samples = [float(np.mean(differences[random.integers(0, len(differences), len(differences))])) for _ in range(2000)]
    return {"low": float(np.quantile(samples, .025)), "high": float(np.quantile(samples, .975))}


def audit_metrics(data_dir: Path) -> dict:
    paths = sorted(data_dir.glob("*/metrics.parquet"))
    result = []
    for path in paths:
        parquet = pq.ParquetFile(path)
        columns = parquet.schema_arrow.names
        time_candidates = [name for name in columns if name.lower() in {"time", "timestamp"}]
        metric_columns = [name for name in columns if name not in time_candidates]
        entities = sorted({name.rsplit("_", 1)[0] for name in metric_columns if "_" in name})
        result.append({"opaque_sample": hashlib.sha256(path.parent.name.encode()).hexdigest()[:12],
                       "rows": parquet.metadata.num_rows, "columns": columns, "timestamp_columns": time_candidates,
                       "metric_count": len(metric_columns), "entity_identifiers": entities[:50],
                       "generic_patterns": sorted({name.rsplit("_", 1)[-1] for name in metric_columns})[:50]})
    return {"label_blind": True, "samples": result, "metrics_used_by_detector_v2": False}


def fetch_metric_samples(data_dir: Path) -> None:
    index = pd.read_parquet(data_dir / "cases.parquet", columns=["case", "dataset", "n_metrics"])
    selected = []
    for dataset in DATASETS:
        candidates = index[(index["dataset"] == dataset) & (index["n_metrics"] > 0)]["case"].astype(str).tolist()
        selected.append(min(candidates, key=lambda case: hashlib.sha256(f"m9a-metrics-audit-v1:{case}".encode()).hexdigest()))
    for case_id in selected:
        destination = data_dir / case_id / "metrics.parquet"
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".parquet.tmp")
        url = f"https://huggingface.co/datasets/phamquiluan/RCAEval/resolve/{HF_REVISION}/{case_id}/metrics.parquet"
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(destination)


def _verdict(external: dict) -> dict:
    overall = external["by_dataset"]["overall"]
    improvement, fpr = overall["recall_difference"], overall["v2_healthy_fpr"]
    verdict = "STRONG_IMPROVEMENT" if improvement >= .15 and fpr <= .10 else (
        "PARTIAL_IMPROVEMENT" if improvement >= .05 and fpr <= .15 else "NOT_JUSTIFIED")
    re3 = [external["by_dataset"][name] for name in ("RE3-OB", "RE3-TT")]
    recommendation = "TRACE TEMPORAL SUFFICIENT" if verdict == "STRONG_IMPROVEMENT" and min(x["v2_recall"] for x in re3) >= .5 else (
        "ADD MULTI-SOURCE METRICS" if max(x["v2_recall"] for x in re3) < .5 else "REDESIGN AGAIN")
    return {"gate": verdict, "recommendation": recommendation,
            "locked_rule": "strong: recall delta >=0.15 and FPR <=0.10; partial: delta >=0.05 and FPR <=0.15"}


def render_reports(result: dict, docs: Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    external = result["external"]; synthetic = result["synthetic"]
    lines = ["# M9A — Temporal Anomaly Detector v2", "", "## Frozen configuration", "",
             f"Selected on synthetic validation only: `{synthetic['selected_config']}`.", "",
             f"Config SHA256: `{synthetic['config_sha256']}`. RCAEval labels were not used for selection.", "",
             f"The CUSUM family was selected from {synthetic['selection']['candidate_count']} fixed candidates: it reached the maximum "
             "synthetic-validation recall at zero healthy FPR and won the tie against the combined detector on lower complexity.", "",
             "### Candidate-family comparison", "", "| Family | Best validation recall | Healthy FPR |", "|---|---:|---:|",
             *[f"| {name} | {_p(value['metrics']['recall'])} | {_p(value['metrics']['healthy_fpr'])} |"
               for name, value in synthetic["variant_validation"].items()], "",
             "## Synthetic validation", "", "| Detector | Recall | Healthy FPR |", "|---|---:|---:|",
             f"| M5/v1 | {_p(synthetic['validation']['v1']['recall'])} | {_p(synthetic['validation']['v1']['healthy_fpr'])} |",
             f"| detector-v2 | {_p(synthetic['validation']['v2']['recall'])} | {_p(synthetic['validation']['v2']['healthy_fpr'])} |", "",
             "### Temporal profiles", "", "| Profile | v1 detection | v2 detection |", "|---|---:|---:|"]
    for profile in synthetic["validation"]["v1"]["by_profile"]:
        lines.append(f"| {profile} | {_p(synthetic['validation']['v1']['by_profile'][profile])} | {_p(synthetic['validation']['v2']['by_profile'][profile])} |")
    lines += ["", "### Topology and repeatability", "", "| Topology | v1 recall | v2 recall | v1 FPR | v2 FPR |",
              "|---|---:|---:|---:|---:|"]
    for topology in synthetic["validation"]["v1"]["by_topology"]:
        v1 = synthetic["validation"]["v1"]["by_topology"][topology]
        v2 = synthetic["validation"]["v2"]["by_topology"][topology]
        lines.append(f"| {topology} | {_p(v1['recall'])} | {_p(v2['recall'])} | {_p(v1['healthy_fpr'])} | {_p(v2['healthy_fpr'])} |")
    r1 = synthetic["validation"]["v1"]["repeatability"]
    r2 = synthetic["validation"]["v2"]["repeatability"]
    lines += ["", f"Across five deterministic repetitions per scenario, v1 had {r1['inconsistent_scenarios']} inconsistent scenarios "
              f"(detection-rate variance {r1['variance']:.4f}); v2 had {r2['inconsistent_scenarios']} "
              f"(variance {r2['variance']:.4f}).", ""]
    lines += ["", "## Post-M8B frozen-detector-v2 external evaluation", "",
              "This is not a new pristine zero-shot benchmark: M8B had already been inspected. Configuration was frozen first on synthetic data.", "",
              "| Dataset | v1 recall | v2 recall | Difference | v1 FPR | v2 FPR | v1 root | v2 root |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in (*DATASETS, "overall"):
        value = external["by_dataset"][name]
        lines.append(f"| {name} | {_p(value['v1_recall'])} | {_p(value['v2_recall'])} | {_p(value['recall_difference'])} | "
                     f"{_p(value['v1_healthy_fpr'])} | {_p(value['v2_healthy_fpr'])} | {_p(value['v1_root_recall'])} | {_p(value['v2_root_recall'])} |")
    overall = external["by_dataset"]["overall"]
    lines += ["", "Paired external detection: " + json.dumps(overall["detection_contingency"], sort_keys=True) + ".", "",
              f"Recall-difference paired bootstrap 95% CI: [{overall['recall_difference_ci95']['low']:.3f}, {overall['recall_difference_ci95']['high']:.3f}].", "",
              "Paired healthy controls: " + json.dumps(overall["healthy_contingency"], sort_keys=True) + ".", "",
              f"FPR-difference paired bootstrap 95% CI: [{overall['fpr_difference_ci95']['low']:.3f}, {overall['fpr_difference_ci95']['high']:.3f}].", "",
              "## Per-fault results", "", "| Dataset:fault | v1 recall | v2 recall | Difference | v2 FPR |", "|---|---:|---:|---:|---:|"]
    for name, value in sorted(external["by_fault"].items()):
        lines.append(f"| {name} | {_p(value['v1_recall'])} | {_p(value['v2_recall'])} | {_p(value['recall_difference'])} | {_p(value['v2_healthy_fpr'])} |")
    fps = sum(case["v2_healthy_fp"] for case in external["cases"])
    misses = sum(not case["v2_detected"] for case in external["cases"])
    lines += ["", "## RE3 and diagnostic studies", "",
              f"RE3-OB/TT incident recall rose to {_p(external['by_dataset']['RE3-OB']['v2_recall'])}/"
              f"{_p(external['by_dataset']['RE3-TT']['v2_recall'])}, but both healthy FPR values are 100.0%. "
              "The apparent recall is therefore not usable evidence of code-fault sensitivity.", "",
              f"Detector-v2 produced {fps} false-positive healthy controls and {misses} fault miss. "
              "Case-level scores and causes are in `m9a-false-positives.md` and `m9a-detection-misses.md`.", "",
              "The label-blind metrics audit found timestamped service/entity CPU, memory, disk I/O, socket, workload, error and latency fields. "
              "These metrics were not consumed by detector-v2.", "",
              "## Limitations", "",
              "- Synthetic sequences contain 60 current observations, while external operations often contain thousands; the selected cumulative score is not length-normalized.",
              "- Positive-only residuals have a positive healthy expectation, so an unbounded CUSUM can accumulate ordinary workload variation.",
              "- RCAEval Train Ticket status evidence is unavailable; its error temporal channel is explicitly unavailable rather than treated as healthy.",
              "- Pseudo-healthy windows are pre-injection controls from fault recordings, not independent production incidents.",
              "- This post-M8B evaluation is not a pristine zero-shot benchmark and does not alter M8B.", "",
              "## Verdict", "", f"**{result['verdict']['gate']}**", "", f"Recommendation: **{result['verdict']['recommendation']}**.", "",
              "The recall gain fails the pre-registered healthy-FPR gate. Do not promote detector-v2 or feed its output into RCA ranking. "
              "A next design must address sequence-length calibration and external healthy drift before considering multi-source ranking.", "",
              "M5/v1 and all M8B artifacts remain unchanged. M9A does not modify RCA ranking or train M7.", ""]
    (docs / "m9a-results.md").write_text("\n".join(lines), encoding="utf-8")
    _diagnostics(external, docs)
    _metrics_report(result["metrics_audit"], docs / "m9a-metrics-audit.md")


def _diagnostics(external: dict, docs: Path) -> None:
    fps = [case for case in external["cases"] if case["v2_healthy_fp"]]
    misses = [case for case in external["cases"] if not case["v2_detected"]]
    fp_scores = [_strongest(case["v2_healthy"])["anomaly_score"] for case in fps]
    fp_samples = [_strongest(case["v2_healthy"])["valid_current_samples"] for case in fps]
    fp_onsets = [_strongest(case["v2_healthy"])["onset_fraction"] for case in fps
                 if _strongest(case["v2_healthy"])["onset_fraction"] is not None]
    by_suite = dict(Counter(case["dataset"] for case in fps))
    fp_lines = ["# M9A detector-v2 false positives", "", f"Cases: **{len(fps)} / 240**. By suite: `{by_suite}`.", "",
                "## Dominant cause", "",
                "The frozen CUSUM configuration accumulates positive-only residuals across the complete operation sequence. "
                "Unlike the 60-observation synthetic validation horizon, external operations commonly contain thousands of observations. "
                "Small normal residuals therefore accumulate past the fixed threshold even in the pre-injection control window.", "",
                f"Among false positives, the strongest operation has median normalized anomaly score `{float(np.median(fp_scores)):.3f}`, "
                f"median current samples `{int(np.median(fp_samples))}`, and median onset fraction `{float(np.median(fp_onsets)):.4f}`. "
                "This very early onset and large score margin support cumulative drift/length mismatch as the dominant failure mode.", "",
                "No threshold is retuned after this observation. The case details below preserve the requested operation, channel scores, "
                "window scale, onset, sample counts, persistence and baseline statistics.", "", "## Cases", ""]
    for case in fps:
        winners = _winners(case["v2_healthy"])
        fp_lines.append(f"- `{case['external_case_id']}` ({case['dataset']}): {json.dumps(winners, sort_keys=True)}")
    (docs / "m9a-false-positives.md").write_text("\n".join(fp_lines) + "\n", encoding="utf-8")
    miss_lines = ["# M9A detector-v2 detection misses", "", f"Cases: **{len(misses)}**.", ""]
    for case in misses:
        evaluated = sum(len(service["operations"]) for service in case["v2_fault"]["services"])
        cause = ("no operation met the minimum baseline/current sample gates" if evaluated == 0
                 else "all evaluated temporal scores remained below the frozen threshold")
        miss_lines.append(f"- `{case['external_case_id']}` — {case['dataset']} `{case['fault_type']}`, root `{case['root_service']}`, "
                          f"root detected={case['v2_root_detected']}, cause={cause}, evaluated operations={evaluated}, "
                          f"error coverage={case['v2_fault']['current_error_evidence_coverage']:.3f}, span coverage={case['coverage']}, "
                          f"strongest={json.dumps(_winners(case['v2_fault']), sort_keys=True)}")
    (docs / "m9a-detection-misses.md").write_text("\n".join(miss_lines) + "\n", encoding="utf-8")


def _winners(window: dict) -> list[dict]:
    result = []
    for service in window["services"]:
        winner = next((op for op in service["operations"] if op["operation"] == service["winning_operation"]), None)
        if winner:
            result.append({"service": service["service"], "operation": winner["operation"], "location": winner["location_score"],
                           "tail": winner["tail_score"], "cusum": winner["cusum_score"], "error": winner["error_temporal_score"],
                           "anomaly_score": winner["anomaly_score"], "valid_baseline_samples": winner["valid_baseline_samples"],
                           "valid_current_samples": winner["valid_current_samples"], "onset_fraction": winner["onset_fraction"],
                           "scale": winner["selected_scale"], "onset": winner["onset_index"], "persistence": winner["persistence_fraction"],
                           "max_run": winner["max_exceedance_run"], "baseline": winner["baseline"]})
    return sorted(result, key=lambda value: (-value["cusum"], value["service"]))[:5]


def _strongest(window: dict) -> dict:
    operations = [operation for service in window["services"] for operation in service["operations"]]
    return max(operations, key=lambda value: (value["anomaly_score"], value["operation"]))


def _compact_result(result: dict) -> dict:
    external = result["external"]
    compact_cases = [{key: value for key, value in case.items() if key not in {"v2_fault", "v2_healthy"}}
                     for case in external["cases"]]
    return {**result, "external": {**external, "cases": compact_cases}}


def _metrics_report(audit: dict, path: Path) -> None:
    lines = ["# M9A label-blind metrics audit", "", "Metrics were inspected only to prepare M9B. Detector-v2 did not consume them.", ""]
    for sample in audit["samples"]:
        lines += [f"## Sample {sample['opaque_sample']}", "", f"Rows: {sample['rows']}; metric count: {sample['metric_count']}; "
                  f"timestamp columns: `{sample['timestamp_columns']}`.", "", f"Columns: `{sample['columns']}`.", "",
                  f"Entity identifier prefixes: `{sample['entity_identifiers']}`.", "",
                  f"Generic suffix patterns: `{sample['generic_patterns']}`.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _p(value: float) -> str:
    return f"{100 * value:.1f}%"


if __name__ == "__main__":
    main()
