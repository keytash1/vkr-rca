"""Generated M9B reports."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import xgboost as xgb

from .m9b_model import contributions
from .m9b_schema import FEATURE_COLUMNS_M9B


def render_all(result: dict, cases: list[dict], rows: list[dict], docs: Path, model_dir: Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    _adapter_audit(result, docs / "m9b-metrics-adapter-audit.md")
    _results(result, docs / "m9b-results.md")
    _ablation(result, docs / "m9b-ablation.md")
    _case_studies(result, cases, rows, model_dir, docs / "m9b-case-studies.md")
    _official(result.get("official_baselines", {}), docs / "m9b-official-baselines.md")


def _adapter_audit(result: dict, path: Path) -> None:
    coverage = result["coverage"]
    adapter = coverage["metric_adapter"]
    lines = ["# M9B metrics adapter audit", "",
             "This audit is computed over all 735 pinned metric cases without using root/fault labels during feature extraction.", "",
             "## Time-series integrity", "",
             f"- Median cadence distribution: `{adapter['cadence_seconds']}`.",
             f"- Duplicate timestamps: `{adapter['duplicate_timestamps']}`.",
             f"- Missing timestamps: `{adapter['missing_timestamps']}`.",
             f"- NaN metric values: `{adapter['nan_values']}`.",
             f"- Infinite metric values: `{adapter['inf_values']}`.",
             f"- Unknown metric columns: `{adapter['unknown_columns']}`.", "",
             "## Mapping and candidate coverage", "",
             "| Dataset | Cases | Root observable | Triggered eligible | Mean candidates | Entity match | Unmatched infrastructure |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for dataset, value in coverage["by_dataset"].items():
        lines.append(f"| {dataset} | {value['cases']} | {value['root_observable']} | {value['triggered_eligible']} | "
                     f"{value['mean_candidates']:.1f} | {_p(value['metric_entity_match_ratio'])} | {value['unmatched_infrastructure']} |")
    lines += ["", "Metric-only datasets treat each normalized non-infrastructure metric entity as an observed service. "
              "Trace-capable datasets require a unique deterministic match to an observed trace service. Database/cache entities remain unmatched; labels never repair mappings.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _results(result: dict, path: Path) -> None:
    metric = result["metric_study"]
    multi = result["multisource_study"]
    lines = ["# M9B — Multi-source Soft-Evidence RCA v2", "",
             "M9B separates incident detection from localization. The primary table is externally triggered and has no hard anomaly gate. "
             "M5/v1 is retained only in the secondary autonomous table; rejected M9A detector-v2 is not used.", "",
             "## RE1 metric model system holdout", "",
             "| Fold | Train cases | Test | Cases | AC@1 | AC@3 | MRR |", "|---|---:|---|---:|---:|---:|---:|"]
    for name, value in metric["system_holdout"].items():
        test = value["test"]
        lines.append(f"| {name} | {value['train_cases']} | {value['test_dataset']} | {test['cases']} | "
                     f"{_p(test['ac_at_1'])} | {_p(test['ac_at_3'])} | {_p(test['mrr'])} |")
    lines += ["", f"Frozen metric hyperparameters: `{metric['frozen_hyperparameters']}`, rounds `{metric['training_rounds']}`. "
              f"Final RE1 cases: `{metric['final_training_cases']}`; model SHA256 `{metric['model_sha256']}`.", "",
              "## Frozen metric-only RE2/RE3 evaluation", "",
              "| Dataset | Cases | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|---:|"]
    for dataset, value in metric["external"]["by_dataset"].items():
        lines.append(f"| {dataset} | {value['cases']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    overall_metric = metric["external"]["overall"]
    lines.append(f"| overall | {overall_metric['cases']} | {_p(overall_metric['ac_at_1'])} | {_p(overall_metric['ac_at_3'])} | {_p(overall_metric['mrr'])} |")
    lines += ["", "## Triggered trace-capable evaluation", "",
              "| Method | Cases | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|---:|"]
    for name, value in multi["baselines"].items():
        lines.append(f"| {name} | {value['cases']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    learned = multi["triggered"]["overall"]
    lines.append(f"| m9b_multisource_lambdamart | {learned['cases']} | {_p(learned['ac_at_1'])} | {_p(learned['ac_at_3'])} | {_p(learned['mrr'])} |")
    historical = multi["autonomous_m5_trigger"]
    lines += ["", "Historical M6/M7 figures below use the older hard-gated eligible subset and are references, "
              "not direct comparisons with the all-candidate triggered table:", "",
              "| Historical method | Eligible cases | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|---:|"]
    for name, value in historical["historical_m6_m7_methods"].items():
        if name != "chance":
            lines.append(f"| {name} | {historical['historical_localization_eligible']} | {_p(value['ac_at_1'])} | "
                         f"{_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    lines += ["", "### Per suite", "", "| Dataset | Cases | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|---:|"]
    for dataset, value in multi["triggered"]["by_dataset"].items():
        lines.append(f"| {dataset} | {value['cases']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    paired = multi["paired_vs_best_trace"]
    lines += ["", f"Best M9B method: `{multi['best_m9b']}`. Best trace-only baseline: `{multi['best_trace_only']}`.", "",
              f"Paired ΔAC@1 `{paired['ac_at_1']['difference']:.3f}`, 95% CI "
              f"`[{paired['ac_at_1']['ci_low']:.3f}, {paired['ac_at_1']['ci_high']:.3f}]`; "
              f"ΔMRR `{paired['mrr']['difference']:.3f}`, 95% CI "
              f"`[{paired['mrr']['ci_low']:.3f}, {paired['mrr']['ci_high']:.3f}]`.", "",
              "## Secondary autonomous M5/v1 mode", "",
              "| Detector | Cases | Detection recall | Healthy FPR | End-to-end AC@1 |", "|---|---:|---:|---:|---:|"]
    auto = multi["autonomous_m5_trigger"]
    lines.append(f"| {auto['detector']} | {auto['cases']} | {_p(auto['detection_recall'])} | {_p(auto['healthy_fpr'])} | {_p(auto['end_to_end_ac_at_1'])} |")
    verdict = result["verdict"]
    modality = multi["modality_ablation"]
    modality_delta = modality["all"]["ac_at_1"] - modality["metrics_only"]["ac_at_1"]
    lines += ["", "## Verdict", "", f"**{verdict['gate']}** using `{verdict['best_m9b']}`.", "",
              f"Code-fault coverage: **{verdict['code_fault_coverage']}**.", "",
              f"Recommendation: **{verdict['recommendation']}**.", "",
              f"The RE1-trained metric ranker is the strongest individual M9B method. Under the matched RE2 cross-system "
              f"training protocol, however, all modalities improve AC@1 over its metrics-only ablation by "
              f"`{modality_delta:.3f}`; this supports retaining the multi-source architecture while expanding "
              "cross-system training coverage, without escalating to GNN/causal/log models yet.", "",
              "M9A remains `NOT_JUSTIFIED`: its trace-only CUSUM failed because of sequence-length/domain calibration and is not part of M9B.", "",
              "## Limitations", "",
              "- This is a post-M8B benchmark; only RE1 model selection is isolated from the previously inspected RE2/RE3 outcomes.",
              "- Metric-only services are deterministic telemetry entities, while infrastructure/database entities are intentionally excluded from service-level ranking.",
              "- Trigger timestamps are supplied externally; primary localization metrics do not measure incident detection.",
              "- TreeSHAP/prediction contributions explain model score association, not causal responsibility.",
              "- Official methods with incompatible upstream inputs/runtimes remain explicit rather than patched or silently approximated.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _ablation(result: dict, path: Path) -> None:
    metric = result["metric_study"]["feature_group_ablation"]
    modality = result["multisource_study"]["modality_ablation"]
    lines = ["# M9B ablation study", "", "## Modality ablation on identical cross-system/out-of-fault test cases", "",
             "Each subset is retrained on the corresponding RE2 training fold with unchanged fold hyperparameters.", "",
             "| Modalities | Columns | Cases | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|---:|---:|"]
    for name, value in modality.items():
        lines.append(f"| {name} | {value['columns']} | {value['cases']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    lines += ["", "## Metric one-group-drop ablation", "",
              "Each variant is retrained on all root-observable RE1 cases and evaluated on the same frozen 360-case RE2/RE3 corpus (336 root-observable cases).", "",
              "| Removed group | Cases | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|---:|"]
    for name, value in metric.items():
        lines.append(f"| {name} | {value['cases']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_studies(result: dict, cases: list[dict], rows: list[dict], model_dir: Path, path: Path) -> None:
    multi = result["multisource_study"]
    rankings = multi["triggered"]["rankings"]
    wanted = (("RE2 CPU success", ("cpu",), True, "RE2"),
              ("RE2 CPU failure", ("cpu",), False, "RE2"),
              ("RE2 DISK success", ("disk",), True, "RE2"),
              ("RE2 DISK failure", ("disk",), False, "RE2"),
              ("RE2 MEM", ("mem",), None, "RE2"),
              ("RE2 DELAY", ("delay",), None, "RE2"),
              ("RE2 SOCKET/LOSS", ("socket", "loss"), None, "RE2"),
              ("RE3 success", (), True, "RE3"),
              ("RE3 failure", (), False, "RE3"))
    chosen = []
    used = set()
    for title, faults, success, suite in wanted:
        pool = [case for case in cases if case["dataset"] in (f"{suite}-OB", f"{suite}-TT")
                and case["triggered_eligible"] and (not faults or case["fault"] in faults)
                and case["external_case_id"] not in used]
        if success is not None:
            pool = [case for case in pool if (_rank(rankings.get(case["external_case_id"], [])) == 1) == success]
        if pool:
            selected = sorted(pool, key=lambda value: value["external_case_id"])[0]
            chosen.append({**selected, "case_study_category": title})
            used.add(selected["external_case_id"])
    by_incident = {incident: [row for row in rows if row["incident_id"] == incident]
                   for incident in {case["external_case_id"] for case in chosen}}
    lines = ["# M9B case studies and score explanations", "",
             "Cases are deterministic lexicographic examples. Contributions are predictive TreeSHAP values and are not causal explanations.", "",
             "## Model gain importance", ""]
    for fold in ("train_RE2-OB_test_TT", "train_RE2-TT_test_OB"):
        importance_model = xgb.Booster()
        importance_model.load_model(model_dir / "multisource-folds" / f"{fold}.json")
        gains = sorted(importance_model.get_score(importance_type="gain").items(), key=lambda value: -value[1])[:15]
        lines.append(f"- `{fold}`: `{[(name, round(value, 4)) for name, value in gains]}`")
    lines.append("")
    for case in chosen:
        incident = case["external_case_id"]
        ranking = rankings[incident]
        root_row = next(row for row in by_incident[incident] if row["label"] == 1)
        fold = ("train_RE2-TT_test_OB" if case["dataset"].endswith("-OB") else "train_RE2-OB_test_TT")
        model = xgb.Booster(); model.load_model(model_dir / "multisource-folds" / f"{fold}.json")
        shap = next(value for value in contributions(model, by_incident[incident], incident, FEATURE_COLUMNS_M9B) if value["truth"])
        metric = sorted(((family, root_row[f"metric_{family}_max_shift"]) for family in
                         ("cpu", "memory", "disk_io", "socket", "workload", "error", "latency_p50", "latency_p90")),
                        key=lambda value: -value[1])[:3]
        outcome = "success" if _rank(ranking) == 1 else "miss"
        why = (f"This is a {outcome}: the strongest root metric families were {metric[:2]}, while the highest-absolute "
               f"model contribution was `{shap['top_contributions'][0]['feature']}`. "
               + ("Their joint score put the truth first."
                  if outcome == "success" else f"The learned cross-system score instead preferred `{ranking[0]['service']}`."))
        lines += [f"## {case['case_study_category']}: {incident}", "", f"Suite `{case['dataset']}`, fault `{case['fault']}`, truth `{case['root_service']}`, "
                  f"rank `{_rank(ranking)}` of `{case['candidate_count']}`.", "",
                  f"Top ranking: `{[(value['service'], round(value['score'], 4)) for value in ranking[:5]]}`.", "",
                  f"Root metric evidence: `{metric}`; trace latency/error `{root_row['trace_latency_z_log1p']:.3f}/"
                  f"{root_row['trace_error_z_log1p']:.3f}`; topology F1 `{root_row['trace_topology_f1']:.3f}`.", "",
                  f"Root top contributions: `{shap['top_contributions']}`.", "", why, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _official(official: dict, path: Path) -> None:
    lines = ["# M9B official RCAEval baselines", "",
             "Pinned upstream source was used without patches. Service projection is reported only where the pinned evaluator defines it.", ""]
    if official.get("status") == "not_run" or not official:
        lines.append("Official baseline runner has not produced an artifact.")
    else:
        for name, value in official.get("methods", {}).items():
            lines += [f"## {name}", "", f"Status: `{value.get('status')}`.", "",
                      f"Expected/succeeded: `{value.get('cases_expected', 0)}/{value.get('cases_succeeded', 0)}`.", ""]
            if value.get("metrics"):
                lines.append(f"Service metrics: `{value['metrics']}`.")
                lines.append("")
            if value.get("failure_summary"):
                lines.append(f"Compatibility failures: `{value['failure_summary']}`.")
                lines.append("")
            if value.get("smoke_stage"):
                lines.append(f"Smoke stage: `{value['smoke_stage']}`.")
                lines.append("")
            if value.get("entrypoint_import_error"):
                lines.append(f"Entrypoint import failure: `{value['entrypoint_import_error']}`.")
                lines.append("")
            if value.get("note"):
                lines.append(value["note"])
                lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _rank(ranking: list[dict]) -> int:
    return next((value["rank"] for value in ranking if value.get("label") == 1), 0)


def _p(value: float) -> str:
    return f"{100 * value:.1f}%"
