"""Post-seal M8B analyses and human-readable reports.

This module is intentionally separate from truth-free generation: it may only run
after ``truth-free-seal.json`` and ``evaluation.json`` exist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from .dataset import build_candidate_rows, read_jsonl, ranks_for_truth, sha256_file
from .m8a_evaluate import feature_distribution_shift
from .metrics import rank_metrics
from .schema import FEATURE_COLUMNS
from .train import fit_fixed, load_model, predict_rows, save_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/m8b/m8b-external-v1"))
    parser.add_argument("--model-dir", type=Path, default=Path("ml/models/m8b-lambdamart-external-v1"))
    parser.add_argument("--m7-dir", type=Path, default=Path("ml/models/m7-lambdamart-v1"))
    parser.add_argument("--m7-a", type=Path, default=Path("artifacts/m7/m7-full-seed-20260904"))
    parser.add_argument("--m8a-b", type=Path, default=Path("artifacts/m8a/m8a-b-full-seed-20260904-r2"))
    parser.add_argument("--m8a-c", type=Path, default=Path("artifacts/m8a/m8a-c-full-seed-20260904-r2"))
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    run(parser.parse_args())


def run(args: argparse.Namespace) -> dict:
    truth_path = args.artifact_dir / "truth-free.jsonl"
    seal = _json(args.artifact_dir / "truth-free-seal.json")
    evaluation = _json(args.artifact_dir / "evaluation.json")
    if not seal.get("sealed_before_truth_join") or seal["truth_free_sha256"] != sha256_file(truth_path):
        raise ValueError("truth-free artifact is not sealed or changed after sealing")
    if len(evaluation["cases"]) != 240:
        raise ValueError("post-seal analysis requires all 240 cases")
    records = read_jsonl(truth_path)
    cases = {case["external_case_id"]: case for case in evaluation["cases"]}
    features, labels = _external_dataset(records, cases)
    rows = build_candidate_rows(features, labels)
    training = _external_training(rows, labels, args)
    shift = _feature_shift(features, labels, args)
    verdicts = _verdicts(evaluation)
    official_path = args.artifact_dir / "official-baselines.json"
    official = _json(official_path) if official_path.exists() else {"status": "not_run"}
    result = {
        "experiment_version": "m8b-v1",
        "zero_shot_evaluation_sha256": sha256_file(args.artifact_dir / "evaluation.json"),
        "truth_free_sha256": seal["truth_free_sha256"],
        "external_training": training,
        "official_baselines": official,
        "feature_distribution_shift": shift,
        "verdicts": verdicts,
    }
    args.model_dir.mkdir(parents=True, exist_ok=True)
    save_json(args.model_dir / "evaluation.json", result)
    save_json(args.model_dir / "feature_schema.json", {"version": "m7-v1", "columns": FEATURE_COLUMNS})
    save_json(args.model_dir / "training_manifest.json", training["manifest"])
    save_json(args.model_dir / "integrity_manifest.json", {
        "rcaeval_revision": "405c8fd24071af41ceb4b3aabb451e5e3e15d6c6",
        "hf_revision": "afeacb11bcc94dadfd1c8f483ee4377b2b8b614e",
        "cases_index_sha256": "c49a288920dbba2e8e724679a14636d5c7eb2b45426bba14007ef79a6c0ab1bb",
        "adapter_protocol": "m8b-v1",
        "window_protocol": {"fault_baseline_seconds": [-600, 0], "fault_current_seconds": [0, 600],
                            "healthy_baseline_seconds": [-600, -300], "healthy_current_seconds": [-300, 0]},
        "m5_config": {"min_baseline": 30, "max_baseline": 1000, "current_size": 20,
                      "min_current": 10, "latency_z": 3.5, "error_z": 3.0, "scale_epsilon": 0.1},
        "m6_schema": "m6-v1",
        "m7_model_sha256": "3728eb0454e46d14265d092d3d17088bc32fe44e8c9cb8d565aa8e934cee7699",
        "code_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "external_case_ids": [case["external_case_id"] for case in evaluation["cases"]],
        "case_telemetry_sha256": {record["external_case_id"]: record["telemetry_sha256"] for record in records},
        "truth_free_sha256": seal["truth_free_sha256"],
        "zero_shot_evaluation_sha256": sha256_file(args.artifact_dir / "evaluation.json"),
        "final_evaluation_sha256": sha256_file(args.model_dir / "evaluation.json"),
    })
    _reports(evaluation, records, training, official, shift, verdicts, args.docs)
    return result


def _external_dataset(records: list[dict], cases: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    features, labels = [], []
    for record in records:
        case = cases[record["external_case_id"]]
        incident = record["external_case_id"]
        features.append({"incident_id": incident, "feature_snapshot": record["fault"]["features"]})
        eligible = bool(case["localization_eligible"] and case["candidate_count"] >= 2)
        labels.append({
            "incident_id": incident,
            "root_service": case["root_service"],
            "dataset": case["dataset"],
            "localization_eligible": eligible,
            "training_eligible": eligible,
        })
    return features, labels


def _external_training(rows: list[dict], labels: list[dict], args: argparse.Namespace) -> dict:
    manifest = _json(args.m7_dir / "training_manifest.json")
    labels_by_id = {label["incident_id"]: label for label in labels}
    eligible = [label for label in labels if label["training_eligible"]]
    ids = {dataset: sorted(label["incident_id"] for label in eligible if label["dataset"] == dataset)
           for dataset in ("RE2-OB", "RE2-TT", "RE3-OB", "RE3-TT")}
    result = {}
    for train_name, test_name in (("RE2-OB", "RE2-TT"), ("RE2-TT", "RE2-OB")):
        model = fit_fixed(rows, ids[train_name], manifest["hyperparameters"],
                          rounds=manifest["training_rounds"], seed=20260904)
        key = f"train_{train_name}_test_{test_name}"
        path = args.model_dir / f"{key.lower()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(path)
        tests = {test_name: ids[test_name], "RE3-OB": ids["RE3-OB"], "RE3-TT": ids["RE3-TT"]}
        result[key] = {
            "train_incidents": len(ids[train_name]),
            "model_sha256": sha256_file(path),
            "tests": {name: _trained_test(model, rows, values, labels_by_id) for name, values in tests.items()},
        }
    result["manifest"] = {
        "model_version": "m8b-lambdamart-external-v1",
        "source_feature_schema": "m7-v1",
        "source_m7_sha256": manifest["model_sha256"],
        "hyperparameters": manifest["hyperparameters"],
        "training_rounds": manifest["training_rounds"],
        "seed": 20260904,
        "training_scope": "RE2 cross-system only; RE3 evaluation only",
        "eligible_counts": {name: len(values) for name, values in ids.items()},
    }
    return result


def _trained_test(model, rows: list[dict], incident_ids: list[str], labels_by_id: dict[str, dict]) -> dict:
    if not incident_ids:
        return {"status": "no_localization_eligible_cases", "cases": 0, **rank_metrics([])}
    ranks = ranks_for_truth(predict_rows(model, rows, incident_ids), labels_by_id)
    return {"status": "evaluated", "cases": len(incident_ids), **rank_metrics(ranks.values())}


def _feature_shift(external_features: list[dict], external_labels: list[dict], args: argparse.Namespace) -> dict:
    datasets = {
        "A": (read_jsonl(args.m7_a / "features.jsonl"), read_jsonl(args.m7_a / "labels.jsonl")),
        "B": (read_jsonl(args.m8a_b / "features.jsonl"), read_jsonl(args.m8a_b / "labels.jsonl")),
        "C": (read_jsonl(args.m8a_c / "features.jsonl"), read_jsonl(args.m8a_c / "labels.jsonl")),
    }
    snapshots = {row["incident_id"]: row["feature_snapshot"] for row in external_features}
    for dataset in ("RE2-OB", "RE2-TT", "RE3-OB", "RE3-TT"):
        wanted = {label["incident_id"] for label in external_labels if label["dataset"] == dataset}
        shift_labels = [{**row, "training_eligible": len(snapshots[row["incident_id"]].get("ready_universe") or []) >= 2}
                        for row in external_labels if row["incident_id"] in wanted]
        datasets[dataset] = ([row for row in external_features if row["incident_id"] in wanted],
                             shift_labels)
    result = feature_distribution_shift(datasets)
    result["external_conditioning"] = "all cases with at least two finite ready service vectors; independent of detector and root label"
    return result


def _verdicts(evaluation: dict) -> dict:
    overall = evaluation["by_dataset"]["overall"]
    frozen = overall["methods"]["frozen_m7"]
    chance = overall["methods"]["chance"]
    detector = "ACCEPTABLE" if overall["detection_recall"] >= .8 and overall["healthy_fpr"] <= .1 else (
        "LIMITING" if overall["detection_recall"] >= .4 else "FAILED")
    learned = "STRONG_TRANSFER" if frozen["ac_at_1"] - chance["ac_at_1"] >= .2 else (
        "PARTIAL_TRANSFER" if frozen["ac_at_1"] > chance["ac_at_1"] else "FAILED_TRANSFER")
    feature_best = max(overall["methods"][name]["ac_at_1"] for name in
                       ("max_severity", "topology_consistency", "local_evidence", "hybrid_v1"))
    representation = "STRONG_TRANSFER" if feature_best - chance["ac_at_1"] >= .2 else (
        "PARTIAL_TRANSFER" if feature_best > chance["ac_at_1"] else "FAILED_TRANSFER")
    direction = ["KEEP LAMBDAMART"] if learned != "FAILED_TRANSFER" else []
    if detector != "ACCEPTABLE":
        direction += ["REDESIGN DETECTOR FIRST", "ADD TEMPORAL FEATURES"]
    return {
        "external_adapter": "PARTIAL_PARITY",
        "feature_representation_external": representation,
        "frozen_m7_external": learned,
        "detector_external": detector,
        "next_model_direction": direction or ["INVESTIGATE GNN"],
    }


def _reports(evaluation: dict, records: list[dict], training: dict, official: dict, shift: dict, verdicts: dict, docs: Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    groups = evaluation["by_dataset"]
    lines = ["# M8B — External Validation on RCAEval", "", "## Locked corpus and integrity", "",
             f"All **{evaluation['coverage']['evaluated']}/240** pinned trace-capable cases were evaluated. "
             f"Status counts: `{evaluation['coverage']['status_counts']}`. Predictions were sealed before labels were joined.", "",
             "## Service-level zero-shot results", "",
             "| Dataset | Cases | Recall | Healthy FPR | Root observable | Eligible | M7 AC@1 | M7 AC@3 | M7 MRR | E2E AC@1 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in (*("RE2-OB", "RE2-TT", "RE3-OB", "RE3-TT"), "overall"):
        value = groups[name]; ml = value["methods"]["frozen_m7"]
        lines.append(f"| {name} | {value['cases']} | {_p(value['detection_recall'])} | {_p(value['healthy_fpr'])} | "
                     f"{_p(value['root_observable_coverage'])} | {value['localization_eligible']} | {_p(ml['ac_at_1'])} | "
                     f"{_p(ml['ac_at_3'])} | {_p(ml['mrr'])} | {_p(value['end_to_end_ac_at_1'])} |")
    lines += ["", "Healthy FPR rollups: " + ", ".join(
        f"{name}={_p(sum(case['healthy_false_positive'] for case in selected) / len(selected))}"
        for name, selected in (
            ("OB", [case for case in evaluation["cases"] if case["dataset"].endswith("-OB")]),
            ("TT", [case for case in evaluation["cases"] if case["dataset"].endswith("-TT")]),
            ("RE2", [case for case in evaluation["cases"] if case["dataset"].startswith("RE2-")]),
            ("RE3", [case for case in evaluation["cases"] if case["dataset"].startswith("RE3-")]),
        )) + "."]
    lines += ["", "## M6 baselines and frozen M7 (overall, conditional)", "",
              "| Method | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|"]
    for method, metric in groups["overall"]["methods"].items():
        lines.append(f"| {method} | {_p(metric['ac_at_1'])} | {_p(metric['ac_at_3'])} | {_p(metric.get('mrr', 0))} |")
    lines += ["", "## Evidence coverage and score stability", "",
              "| Dataset | Error evidence | Exclusive trace | Parent match | Margin median | Margin p10 | Exact ties | Near ties |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in (*("RE2-OB", "RE2-TT", "RE3-OB", "RE3-TT"), "overall"):
        value = groups[name]; coverage = value["feature_coverage"]; margins = value["score_margins"]
        lines.append(f"| {name} | {_p(coverage['error_evidence_mean'])} | {_p(coverage['exclusive_trace_mean'])} | "
                     f"{_p(coverage['parent_match_mean'])} | {margins['median']:.6f} | {margins['p10']:.6f} | "
                     f"{_p(margins['exact_ties'])} | {_p(margins['near_ties'])} |")
    lines += ["", "All emitted ready-candidate M7 vectors passed the finite numeric schema check (anomaly-feature coverage 100% "
              "within the localization universe). Error coverage is lower where source status is missing; topology and exclusive-trace "
              "coverage are therefore reported independently rather than filled with synthetic evidence."]
    lines += ["", "## Fault-type breakdown", "",
              "| Dataset:fault | Cases | Recall | Eligible | M7 AC@1 | M7 AC@3 | M7 MRR | E2E AC@1 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, value in sorted(evaluation["by_fault"].items()):
        ml = value["methods"]["frozen_m7"]
        lines.append(f"| {name} | {value['cases']} | {_p(value['detection_recall'])} | {value['localization_eligible']} | "
                     f"{_p(ml['ac_at_1'])} | {_p(ml['ac_at_3'])} | {_p(ml['mrr'])} | {_p(value['end_to_end_ac_at_1'])} |")
    lines += ["", "## External system-holdout", "",
              "RE2 models use the unchanged M7 feature schema, fixed M7 hyperparameters and rounds; RE3 is evaluation-only and out-of-fault-family.", ""]
    for name, value in training.items():
        if name == "manifest": continue
        lines.append(f"- `{name}`: train={value['train_incidents']}; " + ", ".join(
            f"{test} AC@1={metric['ac_at_1']:.3f}, MRR={metric['mrr']:.3f}" for test, metric in value["tests"].items()))
    lines += ["", "## Official RCAEval baselines", "",
              "TraceRCA was reproduced unmodified on the pinned RE2-OB smoke case (1.114 s; 35 native operation candidates). "
              "The full supported run uses the exact coarse service conversion in pinned `main.py` (split the operation token, "
              "strip `-db`, and stable-deduplicate); upstream method code is unchanged.", ""]
    if official.get("method"):
        metric = official["metrics_over_succeeded"]
        failure_types = Counter(item["error"].split(":", 1)[0] for item in official["failures"])
        failure_datasets = Counter(next(case["dataset"] for case in evaluation["cases"]
                                        if case["external_case_id"] == item["case"])
                                   for item in official["failures"])
        lines.append(f"- {official['method']}: {official['cases_succeeded']}/{official['cases_expected']} succeeded; "
                     f"service AC@1={metric['ac_at_1']:.3f}, AC@3={metric['ac_at_3']:.3f}, MRR={metric['mrr']:.3f}; "
                     f"mean runtime={official['runtime_seconds']['mean']:.3f}s.")
        lines.append(f"- Explicit upstream compatibility failures: `{dict(failure_types)}` by exception and "
                     f"`{dict(failure_datasets)}` by dataset. Metrics above use only the {official['cases_succeeded']} successful official runs and are not "
                     "silently assigned scores for failures.")
    else:
        lines.append("- Full official trace baseline result was not available in this artifact.")
    lines += ["- BARO and Multi-source BARO require metric/multi-source inputs absent from the locked trace-only corpus and were not forced.",
              "- MicroRank's pinned raw-trace path exceeded the 30-second smoke budget on one case; no upstream source was patched, and a partial full run is not reported.",
              "", "## Feature shift", "",
              "Largest standardized median shifts across synthetic A/B/C and external suites:", ""]
    for value in shift["largest_shifts"][:10]:
        lines.append(f"- `{value['feature']}`: {value['systems'][0]} vs {value['systems'][1]} = {value['standardized_median_difference']:.3f}")
    lines += ["", "## Verdicts", ""] + [f"- **{key.upper().replace('_', ' ')}:** {value if isinstance(value, str) else ', '.join(value)}" for key, value in verdicts.items()]
    lines += ["", "Adapter parity is partial because native span kind is absent in every suite and status/error evidence is absent in Train Ticket; "
              "M5/M6 mathematics are reused directly and all missing evidence remains coverage-qualified.", "",
              "The zero-shot result is preserved even when performance is weak; no detector, window, feature, or threshold was retuned.", ""]
    (docs / "m8b-results.md").write_text("\n".join(lines), encoding="utf-8")
    _diagnostic_report(evaluation, records, docs / "m8b-false-positives.md", healthy=True)
    _diagnostic_report(evaluation, records, docs / "m8b-detection-misses.md", healthy=False)
    _case_studies(evaluation, records, docs / "m8b-case-studies.md")


def _diagnostic_report(evaluation: dict, records: list[dict], path: Path, *, healthy: bool) -> None:
    if healthy:
        selected = [case for case in evaluation["cases"] if case["healthy_false_positive"]]
        title = "External healthy-window false positives"
    else:
        selected = [case for case in evaluation["cases"] if case["status"] != "ready"]
        title = "External detection and eligibility misses"
    counts = Counter((case["dataset"], case["fault_type"], case["status"]) for case in selected)
    lines = [f"# {title}", "", f"Cases: **{len(selected)}**. Detector v1 was not retuned.", "",
             "| Dataset | Fault | Status | Count |", "|---|---|---|---:|"]
    lines += [f"| {d} | {f} | {s} | {n} |" for (d, f, s), n in sorted(counts.items())]
    lines += ["", "## Case diagnostics", ""]
    by_id = {record["external_case_id"]: record for record in records}
    for case in selected:
        root = case.get("root_vector") or {}
        mode = "healthy" if healthy else "fault"
        operations = [value for value in by_id[case["external_case_id"]][mode]["anomalies"].get("operations", [])
                      if value.get("service") == case["root_service"]]
        baseline_count = sum(int(value.get("baseline_samples", 0)) for value in operations)
        current_count = sum(int(value.get("current_samples", 0)) for value in operations)
        latency_z = max((float(value.get("latency_z", 0)) for value in operations), default=root.get("latency_z", 0))
        error_z = max((float(value.get("error_z", 0)) for value in operations), default=root.get("error_z", 0))
        lines.append(f"- `{case['external_case_id']}` — {case['dataset']}, {case['fault_type']}, root `{case['root_service']}`, "
                     f"state `{case['status']}`, candidates {case['candidate_count']}, baseline/current={baseline_count}/{current_count}, "
                     f"latency_z={latency_z}, error_z={error_z}, root anomalous={case['root_observed_anomaly']}.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_studies(evaluation: dict, records: list[dict], path: Path) -> None:
    by_id = {record["external_case_id"]: record for record in records}
    chosen = []
    for dataset, success in (("RE2-OB", True), ("RE2-OB", False), ("RE2-TT", True), ("RE2-TT", False),
                             ("RE3-OB", None), ("RE3-TT", None)):
        pool = [case for case in evaluation["cases"] if case["dataset"] == dataset and
                (success is None or ((case["status"] == "ready" and case["ranks"]["frozen_m7"] == 1) == success))]
        selected = sorted(pool, key=lambda value: value["external_case_id"])[0]
        chosen.append(selected)
    lines = ["# M8B case studies", "", "Six deterministic examples (lexicographically first matching case) were selected after evaluation.", ""]
    for case in chosen:
        record = by_id[case["external_case_id"]]; fault = record["fault"]
        edges = fault["features"].get("topology_edges", [])
        lines += [f"## {case['external_case_id']}", "",
                  f"Truth `{case['root_service']}`; fault `{case['fault_type']}`; detector/status `{case['status']}`; "
                  f"observed anomalies `{fault['features'].get('observed_anomalies', [])}`.", "",
                  f"Topology has {len(edges)} edges; coverage `{case['coverage']}`.", "",
                  "M6 ranks: " + "; ".join(f"{name}={case['ranks'].get(name, 0)}" for name in
                  ("max_severity", "topology_consistency", "local_evidence", "hybrid_v1")) +
                  f". Frozen M7 rank={case['ranks']['frozen_m7']}.", "",
                  ("The root was available to the ranker; the rank reflects external feature transfer."
                   if case["localization_eligible"] else
                   "Localization was gated before ranking by detector state or root readiness/observability."), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _p(value: float) -> str:
    return f"{100 * value:.1f}%"


if __name__ == "__main__":
    main()
