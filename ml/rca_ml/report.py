"""Render the checked-in scientific M7 result report."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .schema import FEATURE_COLUMNS, FEATURE_GROUPS


def render_report(
    path: str | Path,
    *,
    dataset_manifest: dict,
    labels: list[dict],
    assignments: dict[str, str],
    training: dict,
    evaluation: dict,
    live_results: list[dict],
) -> None:
    fault_labels = [label for label in labels if label["incident_type"] == "fault"]
    split_counts = Counter(assignments.values())
    lines = [
        "# Milestone 7 results: Dataset + Learning-to-Rank v1",
        "",
        "This report records the first learned RCA experiment. It is a same-system research result, not evidence of arbitrary cross-system generalization.",
        "",
        "## Reproducibility",
        "",
        f"- Dataset run: {dataset_manifest['run_id']}",
        f"- Source Git commit: {dataset_manifest['git_commit']}",
        f"- Dataset schema: {dataset_manifest['dataset_schema_version']}",
        f"- Source feature schema: {dataset_manifest['m6_feature_schema_version']}",
        f"- Random seed: {dataset_manifest['random_seed']}",
        f"- Python: {dataset_manifest['python']['version']}",
        f"- XGBoost: {dataset_manifest['python']['packages']['xgboost']}",
        f"- NumPy: {dataset_manifest['python']['packages']['numpy']}",
        f"- Features SHA256: {dataset_manifest['sha256']['features.jsonl']}",
        f"- Labels SHA256: {dataset_manifest['sha256']['labels.jsonl']}",
        "",
        "The raw features.jsonl and labels.jsonl were written independently. Root service, fault type, and intensity exist only in labels. The join occurred by incident_id after truth-free M6 feature extraction.",
        "",
        "Collector isolation uses a drain interval, a current-window reset, and a poll proving every operation has zero current samples before the next incident.",
        "",
        "## Dataset",
        "",
        f"- Fault incidents: {evaluation['counts']['fault_incidents']}",
        f"- Healthy controls: {evaluation['counts']['healthy_controls']}",
        f"- Split incidents: train={split_counts['train']}, validation={split_counts['validation']}, test={split_counts['test']}",
        f"- Detection recall: {_pct(evaluation['detection']['recall'])}",
        f"- Root-ready coverage: {_pct(evaluation['detection']['root_ready_coverage'])}",
        f"- Training eligibility: {_pct(evaluation['detection']['training_eligibility_rate'])}",
        f"- Healthy false-positive rate: {_pct(evaluation['detection']['healthy_false_positive_rate'])}",
        f"- Localization eligible: {evaluation['counts']['localization_eligible']}",
        f"- Non-trivial training eligible: {evaluation['counts']['training_eligible']}",
        f"- Trivial one-service groups: {evaluation['counts']['trivial_groups']}",
        "",
        "Fault intensity distribution:",
        "",
        "| Root | Fault | Count | Min | Median | Max |",
        "|---|---|---:|---:|---:|---:|",
    ]
    grouped = defaultdict(list)
    for label in fault_labels:
        grouped[(label["root_service"], label["fault_type"])].append(float(label["fault_value"]))
    for key in sorted(grouped):
        values = grouped[key]
        lines.append(
            f"| {key[0]} | {key[1]} | {len(values)} | {min(values):.6g} | "
            f"{statistics.median(values):.6g} | {max(values):.6g} |"
        )
    lines.extend(
        [
            "",
            "## Numeric feature schema",
            "",
            "The model uses an explicit ordered whitelist. Service and operation names, identifiers, scenario metadata, fault data, M6 rank positions, and truth are not model inputs.",
            "",
            "~~~text",
            *FEATURE_COLUMNS,
            "~~~",
            "",
            "Feature groups:",
            "",
        ]
    )
    for group, columns in FEATURE_GROUPS.items():
        lines.append(f"- {group.upper()}: {', '.join(columns)}")
    lines.extend(
        [
            "",
            "## Model selection",
            "",
            "LambdaMART uses XGBoost rank:ndcg, hist, binary relevance, incident query groups, top-k pair construction with three pairs per sample, and deterministic seeds. Test labels were not used for selection or fitting.",
            "",
            f"- Search candidates: {len(training['search'])}",
            f"- Selected parameters: {json.dumps(training['selected_hyperparameters'], sort_keys=True)}",
            f"- Best iteration: {training['best_iteration']}",
            f"- Final rounds on train + validation: {training['training_rounds']}",
            f"- Best validation metrics: {json.dumps(training['best_validation_metrics'], sort_keys=True)}",
            "",
            "## Non-trivial test comparison",
            "",
            f"All methods below use the same {evaluation['counts']['test_nontrivial_incidents']} incidents.",
            "",
            "| Method | AC@1 | AC@3 | MRR | NDCG@1 | NDCG@3 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    order = ("chance", "max_severity", "topology_consistency", "local_evidence", "hybrid_v1", "m7_lambdamart")
    for method in order:
        metric = evaluation["test_nontrivial_metrics"][method]
        lines.append(
            f"| {method} | {metric['ac_at_1']:.4f} | {metric['ac_at_3']:.4f} | "
            f"{metric['mrr']:.4f} | {metric['ndcg_at_1']:.4f} | {metric['ndcg_at_3']:.4f} |"
        )
    all_metrics = evaluation["test_all_localization_metrics"]
    lines.extend(
        [
            "",
            "## Conditional and end-to-end quality",
            "",
            f"- Test localization subset, including trivial groups: n={evaluation['counts']['test_localization_incidents']}, "
            f"AC@1={all_metrics['ac_at_1']:.4f}, MRR={all_metrics['mrr']:.4f}.",
            f"- Test non-trivial localization subset: n={evaluation['counts']['test_nontrivial_incidents']}.",
            f"- End-to-end AC@1 over every injected fault incident: {evaluation['end_to_end_ac_at_1']:.4f}.",
            "",
            "## Paired bootstrap",
            "",
            "The unit is one test incident. Intervals are deterministic 95% bootstrap CIs over 2000 paired resamples; no statistical-significance claim is made.",
            "",
            "| Baseline | Delta AC@1 | 95% CI | Delta MRR | 95% CI |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for baseline, value in evaluation["paired_bootstrap_95_ci"].items():
        ac1 = value["ac_at_1"]
        mrr = value["mrr"]
        lines.append(
            f"| {baseline} | {ac1['difference']:.4f} | [{ac1['ci_low']:.4f}, {ac1['ci_high']:.4f}] | "
            f"{mrr['difference']:.4f} | [{mrr['ci_low']:.4f}, {mrr['ci_high']:.4f}] |"
        )
    permutation = evaluation["label_permutation"]
    lines.extend(
        [
            "",
            "## Leakage sanity checks",
            "",
            f"- Real-label AC@1: {permutation['real_label_ac_at_1']:.4f}",
            f"- Permuted-label AC@1: {permutation['permuted_label_ac_at_1']:.4f}",
            f"- Chance AC@1: {permutation['chance_ac_at_1']:.4f}",
            f"- Permutation sanity passed: {str(permutation['leakage_sanity_passed']).lower()}",
            "- Schema tests prove the feature whitelist does not intersect forbidden metadata.",
            "- Candidate service renaming leaves the numeric matrix unchanged; only an exact-score lexical tie may change presentation order.",
            "",
            "## Leave-one-root-out",
            "",
            "These folds hold out root identity inside the same topology. They are not cross-topology validation.",
            "",
            "| Held-out root | Test incidents | Detection coverage | AC@1 | MRR |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for root, value in evaluation["root_holdout"].items():
        lines.append(
            f"| {root} | {value['test_incidents']} | {value['detection_coverage']:.4f} | "
            f"{value['metrics']['ac_at_1']:.4f} | {value['metrics']['mrr']:.4f} |"
        )
    importance = sorted(evaluation["feature_importance_gain"].items(), key=lambda item: (-item[1], item[0]))
    lines.extend(
        [
            "",
            "## Gain importance",
            "",
            "Gain importance describes this fitted tree ensemble; it is not causal attribution.",
            "",
            "| Feature | Gain |",
            "|---|---:|",
        ]
    )
    for feature, value in importance[:12]:
        lines.append(f"| {feature} | {value:.6g} |")
    lines.extend(["", "## Per-incident examples", ""])
    for example in evaluation["prediction_examples"]:
        ranking = ", ".join(f"{item['rank']}. {item['service']} ({item['ml_score']:.5g})" for item in example["ranking"])
        contributions = ", ".join(
            f"{item['feature']}={item['contribution']:.5g}" for item in example["root_top_pred_contributions"][:5]
        )
        lines.extend(
            [
                f"### {example['root_service']} {example['fault_type']} - {example['incident_id']}",
                "",
                f"- Ranking: {ranking}",
                f"- Largest root-row TreeSHAP contributions: {contributions}",
                "- TreeSHAP explains model score, not causality.",
                "",
            ]
        )
    lines.extend(["## Live deterministic scenarios", "", "| Scenario | Truth rank | Ranking |", "|---|---:|---|"])
    for result in live_results:
        ranking = ", ".join(f"{item['rank']}. {item['service']}" for item in result["ranking"])
        lines.append(f"| {result['scenario']} | {result['truth_rank']} | {ranking} |")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "1. All training telemetry comes from one three-service topology.",
            "2. Repeated observations from one system do not prove cross-system transfer.",
            "3. Faults are synthetic and single-root.",
            "4. Only latency and error fault families are represented.",
            "5. ml_score is a ranking score, not a probability or calibrated confidence.",
            "6. XGBoost gain and TreeSHAP are not causal attribution.",
            "7. M5 detection quality upper-bounds end-to-end localization.",
            "8. Trace instrumentation completeness affects exclusive-duration features.",
            "9. Cross-topology and external benchmark evaluation are mandatory M8 work.",
            "",
            "## Candidate decision",
            "",
            f"**LEARNED MODEL CANDIDATE STATUS: {evaluation['learned_model_candidate_status']}**",
            "",
            "M8 was not started.",
        ]
    )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"
