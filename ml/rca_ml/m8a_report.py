"""Render the M8A scientific report and diagnostic appendices."""

from __future__ import annotations

import json
from pathlib import Path


def render_results(
    path: str | Path,
    *,
    m7_manifest: dict,
    manifests: dict[str, dict],
    zero_shot: dict[str, dict],
    system_holdout: dict,
    feature_shift: dict,
    verdicts: dict,
) -> None:
    lines = [
        "# Milestone 8A results: Cross-Topology Generalization",
        "",
        "M8A evaluates the frozen M7 model on controlled unseen graph structures. RCAEval, GNNs, temporal features and detector retuning are outside this milestone.",
        "",
        "## Frozen M7 baseline",
        "",
        f"- Model: `{m7_manifest['model_version']}`",
        f"- SHA256: `{m7_manifest['model_sha256']}`",
        f"- Feature schema: `{m7_manifest['ml_feature_schema']}`",
        f"- Frozen parameters: `{json.dumps(m7_manifest['hyperparameters'], sort_keys=True)}`",
        f"- Training rounds: {m7_manifest['training_rounds']}",
        "",
        "The frozen model was trained only on Topology A (`gateway -> orders -> payment`). B and C were never used for model selection or M7 fitting.",
        "",
        "## Benchmark systems",
        "",
    ]
    for system in ("B", "C"):
        topology = manifests[system]["topology"]
        lines.extend(
            [
                f"### Topology {system}: {topology['name']}",
                "",
                f"- Services: {', '.join(topology['services'])}",
                f"- Entry: {topology['entry_service']}",
                "- Edges: " + ", ".join(f"{source} -> {target}" for source, target in topology["edges"]),
                f"- Dataset run: `{manifests[system]['run_id']}`",
                f"- Zero-shot faults: {manifests[system]['zero_shot_fault_incidents']}",
                f"- Healthy controls: {manifests[system]['zero_shot_healthy_controls']}",
                f"- Baseline operations: {len(manifests[system]['baseline'].get('operations', []))}",
                "",
            ]
        )
    lines.extend(["## Zero-shot results", ""])
    for system in ("B", "C"):
        result = zero_shot[system]
        counts = result["counts"]
        detection = result["detection"]
        lines.extend(
            [
                f"### Topology {system}",
                "",
                f"- Frozen model status: **{result['transfer_status']}**",
                f"- Detection recall: {detection['recall']:.4f} ({counts['detected_fault_incidents']}/{counts['zero_shot_fault_incidents']})",
                f"- Healthy FPR: {detection['healthy_false_positive_rate']:.4f}",
                f"- Root-ready coverage: {detection['root_ready_coverage']:.4f}",
                f"- Localization eligible: {counts['localization_eligible']}",
                f"- Non-trivial common subset: {counts['nontrivial_eligible']}",
                f"- End-to-end AC@1: {result['end_to_end_ac_at_1']:.4f}",
                f"- Unexpected-branch anomaly rate: {result['branch_isolation']['rate']:.4f}",
                "",
                "| Method | AC@1 | AC@3 | MRR |",
                "|---|---:|---:|---:|",
            ]
        )
        for method, metrics in result["conditional_nontrivial_metrics"].items():
            lines.append(f"| {method} | {metrics['ac_at_1']:.4f} | {metrics['ac_at_3']:.4f} | {metrics['mrr']:.4f} |")
        paired = result["paired_vs_hybrid_95_ci"]
        lines.extend(
            [
                "",
                f"Paired frozen-LambdaMART minus hybrid: ΔAC@1={paired['ac_at_1']['difference']:.4f} "
                f"95% CI [{paired['ac_at_1']['ci_low']:.4f}, {paired['ac_at_1']['ci_high']:.4f}]; "
                f"ΔMRR={paired['mrr']['difference']:.4f} "
                f"95% CI [{paired['mrr']['ci_low']:.4f}, {paired['mrr']['ci_high']:.4f}].",
                "",
                "Ranking margin (an uncalibrated stability measure, not confidence):",
                "",
                f"- median: {result['score_margins']['median']:.8f}",
                f"- p10: {result['score_margins']['p10']:.8f}",
                f"- exact zero fraction: {result['score_margins']['fraction_equal_zero']:.4f}",
                f"- below epsilon fraction: {result['score_margins']['fraction_below_epsilon']:.4f}",
                "",
            ]
        )
    lines.extend(["## Temporal stress", ""])
    for system in ("B", "C"):
        lines.extend(
            [
                f"### Topology {system}",
                "",
                "| Profile | Incidents | Detection | Conditional AC@1 | AC@3 | MRR | End-to-end AC@1 |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for profile, value in zero_shot[system]["temporal_stress"].items():
            metrics = value["conditional_metrics"]
            lines.append(
                f"| {profile} | {value['incidents']} | {value['detection_recall']:.4f} | "
                f"{metrics['ac_at_1']:.4f} | {metrics['ac_at_3']:.4f} | {metrics['mrr']:.4f} | "
                f"{value['end_to_end_ac_at_1']:.4f} |"
            )
        lines.append("")
    lines.extend(["## Repeated-run stability", ""])
    for system in ("B", "C"):
        value = zero_shot[system]["repeated_run_stability"]
        lines.extend(
            [
                f"- Topology {system}: {value['fixed_scenarios']} fixed scenarios, {value['runs']} runs; "
                f"mean Top-1 consistency={value['mean_top1_consistency_rate']:.4f}; "
                f"mean truth-rank variance={value['mean_truth_rank_variance']:.4f}.",
            ]
        )
    lines.extend(
        [
            "",
            "Per-scenario ranks and variability of exclusive duration, latency-z and topology-f1 are retained in the checked-in evaluation JSON.",
            "",
            "## Detection misses and healthy false positives",
            "",
        ]
    )
    for system in ("B", "C"):
        result = zero_shot[system]
        lines.extend(
            [
                f"- Topology {system} miss classes: `{json.dumps(result['detection_misses']['counts_by_reason'], sort_keys=True)}`",
                f"- Topology {system} false-positive cases: {len(result['false_positives'])}",
            ]
        )
    lines.extend(["", "Full operation-level diagnostics are in `docs/m8a-false-positives.md` and the evaluation JSON.", ""])
    lines.extend(
        [
            "## System-holdout matrix",
            "",
            "The `m8a-lambdamart-cross-v1` folds reuse M7 hyperparameters and one training round. No held-out topology is used for tuning.",
            "",
            "| Held out | Train systems | Train incidents | Test incidents | Frozen AC@1 | Cross AC@1 | Cross MRR |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for system, value in system_holdout.items():
        lines.append(
            f"| {system} | {'+'.join(value['train_systems'])} | {value['train_incidents']} | {value['test_incidents']} | "
            f"{value['frozen_m7_metrics']['ac_at_1']:.4f} | {value['cross_model_metrics']['ac_at_1']:.4f} | "
            f"{value['cross_model_metrics']['mrr']:.4f} |"
        )
    lines.extend(["", "## Feature distribution shift", ""])
    lines.append("Statistics are conditioned on non-trivial localization-eligible candidate rows.")
    lines.extend(["", "| Feature | Strongest pair | Standardized median difference |", "|---|---|---:|"])
    for value in feature_shift["largest_shifts"]:
        lines.append(
            f"| {value['feature']} | {' vs '.join(value['systems'])} | {value['standardized_median_difference']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Verdicts",
            "",
            f"- FEATURE REPRESENTATION: **{verdicts['feature_representation']}**",
            f"- M7 LAMBDAMART: **{verdicts['m7_lambdamart']}**",
            "",
            verdicts["rationale"],
            "",
            "## Limitations",
            "",
            "1. All systems are controlled synthetic Go services with the same OTel instrumentation and fault injector.",
            "2. B/C are structurally unseen, but this is not an external telemetry domain.",
            "3. Faults remain single-root and limited to latency/error.",
            "4. M5 thresholds are frozen; detector quality bounds end-to-end localization.",
            "5. Temporal profiles are evaluated with aggregate M7 features; no temporal features were added.",
            "6. `ml_score` and score margin are not probabilities or confidence estimates.",
            "7. System-holdout models reuse the one-round M7 configuration and are not tuned for B/C.",
            "8. RCAEval remains mandatory M8B work and was not downloaded or adapted here.",
            "",
            "M8B was not started.",
        ]
    )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_false_positives(path: str | Path, evaluations: dict[str, dict]) -> None:
    lines = [
        "# M8A healthy false-positive diagnostics",
        "",
        "M5 thresholds are frozen at latency-z 3.5 and error-z 3.0. This report diagnoses false positives without retuning on test outcomes.",
        "",
    ]
    for system in ("B", "C"):
        cases = evaluations[system]["false_positives"]
        lines.extend([f"## Topology {system}", "", f"False-positive controls: {len(cases)}", ""])
        for case in cases:
            lines.extend(
                [
                    f"### {case['incident_id']}",
                    "",
                    f"Observed anomalies: {', '.join(case['observed_anomalies']) or 'none'}",
                    "",
                    "| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |",
                    "|---|---|---:|---:|---:|---:|---|---|",
                ]
            )
            for operation in case["operations"]:
                lines.append(
                    f"| {operation['service']} | {operation['operation']} | {operation['current_samples']} | "
                    f"{operation['baseline_samples']} | {_number(operation['latency_z'])} | {_number(operation['error_z'])} | "
                    f"{operation['latency_anomalous']} | {operation['error_anomalous']} |"
                )
            lines.append("")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _number(value: object) -> str:
    return f"{float(value or 0):.6f}"
