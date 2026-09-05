"""Generated M10A research-freeze reports."""

from __future__ import annotations

from pathlib import Path


def render_all(result: dict, m9b: dict, docs: Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    render_results(result, docs / "m10a-results.md")
    render_claims(result, m9b, docs / "thesis-claims.md")
    render_history(result, m9b, docs / "final-research-summary.md")


def render_results(result: dict, path: Path) -> None:
    fusion = result["fusion"]
    delta = fusion["paired_all_minus_metrics"]
    lines = ["# M10A — Research Freeze & Claim Validation", "",
             "M10A introduces no new model, feature, telemetry source, threshold, or runtime behavior. "
             "It validates the immutable M9B research core with fixed denominators and deterministic statistics.", "",
             "## Matched multimodal fusion claim", "",
             "| Scope | Cases | All AC@1 | Metrics AC@1 | ΔAC@1 (95% CI) | ΔMRR (95% CI) | Inference |",
             "|---|---:|---:|---:|---:|---:|---|"]
    lines.append(f"| Overall | {fusion['cases']} | {_p(fusion['all_modalities']['ac_at_1'])} | "
                 f"{_p(fusion['metrics_only']['ac_at_1'])} | {_delta(delta, 'ac_at_1')} | "
                 f"{_delta(delta, 'mrr')} | paired bootstrap |")
    for dataset, value in fusion["by_dataset"].items():
        paired = value["paired_all_minus_metrics"]
        lines.append(f"| {dataset} | {value['cases']} | {_p(value['all_modalities']['ac_at_1'])} | "
                     f"{_p(value['metrics_only']['ac_at_1'])} | {_delta(paired, 'ac_at_1')} | "
                     f"{_delta(paired, 'mrr')} | {value['inference']} |")
    ac1_supported = delta["ac_at_1"]["ci_low"] > 0
    mrr_supported = delta["mrr"]["ci_low"] > 0
    fusion_decision = "SUPPORTED" if ac1_supported and mrr_supported else "PARTIALLY SUPPORTED / METRIC-DEPENDENT"
    lines += ["", f"Fusion conclusion: **{fusion_decision}**. "
              f"The AC@1 gain is {'statistically supported' if ac1_supported else 'not statistically stable because its interval touches zero'}, "
              f"while the MRR gain is {'statistically supported' if mrr_supported else 'not statistically stable'}. "
              "The point estimates remain reported. RE3-OB is descriptive only (`n=6`), and the suite rows show that the gain is domain-dependent.", "",
              "## Metric model denominators", "",
              "| Dataset | Conditional cases | Conditional AC@1 | Full cases | Missing-root failures | Full AC@1 | Full AC@3 | Full MRR |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    conditional = result["metric_denominators"]["conditional_root_observable"]
    full = result["metric_denominators"]["full_360"]
    for dataset, value in full["by_dataset"].items():
        cond = conditional["by_dataset"][dataset]
        lines.append(f"| {dataset} | {cond['cases']} | {_p(cond['ac_at_1'])} | {value['cases']} | "
                     f"{value['missing_failures']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    cond = conditional["overall"]; value = full["overall"]
    lines.append(f"| Overall | {cond['cases']} | {_p(cond['ac_at_1'])} | {value['cases']} | "
                 f"{value['missing_failures']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |")
    lines += ["", "Conditional and full-denominator results are intentionally separate. An unobservable root is a rank-zero failure in the 360-case result.", "",
              "## Fair BARO comparison", ""]
    audit = result["baro_comparison"]["audit"]
    lines += [f"- Comparable: `{audit['comparable']}`.", f"- Same incident IDs: `{audit['same_incident_ids']}`.",
              f"- Same root labels: `{audit['same_root_labels']}`.",
              f"- Granularity: M9B `{audit['m9b_granularity']}`; BARO `{audit['baro_granularity']}`.",
              f"- {audit['candidate_universe_note']}", ""]
    comparison = result["baro_comparison"]["comparison"]
    if comparison:
        paired = comparison["paired_m9b_minus_baro"]
        lines += ["| Method | Cases | AC@1 | AC@3 | MRR |", "|---|---:|---:|---:|---:|",
                  _metric_row("M9B metric LambdaMART", comparison["m9b_metric"]),
                  _metric_row("Pinned BARO", comparison["baro"]), "",
                  f"Paired M9B−BARO: ΔAC@1 {_delta(paired, 'ac_at_1')}; ΔMRR {_delta(paired, 'mrr')}.", ""]
    else:
        lines += ["A direct comparison was rejected by the granularity/denominator audit.", ""]
    lines += ["## Robustness to learner randomness", "",
              "Five deterministic XGBoost seeds reuse the frozen folds, hyperparameters, rounds, and feature schemas.", ""]
    for title, value in (("RE1 metric system holdouts", result["robustness"]["metric_re1_system_holdout"]),
                         ("RE2 multi-source cross-system folds", result["robustness"]["multisource_re2_cross_system"])):
        lines += [f"### {title}", "", "| Fold | AC@1 mean±std | min–max | 95% CI mean | MRR mean±std | min–max | 95% CI mean |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for name, fold in value["by_fold"].items():
            lines.append(_stability_row(name, fold["ac_at_1"], fold["mrr"]))
        lines += ["", "Across-fold mean per seed:", "",
                  "| Scope | AC@1 mean±std | min–max | 95% CI mean | MRR mean±std | min–max | 95% CI mean |",
                  "|---|---:|---:|---:|---:|---:|---:|",
                  _stability_row("Overall", value["overall_ac_at_1"], value["overall_mrr"]), ""]
    lines += ["## Feature-group stability", "",
              "Importance is normalized XGBoost total gain. `cross_family` contains metric availability and aggregate/percentile summary features. "
              "Importance is predictive, not causal responsibility.", ""]
    for category, value in result["feature_group_stability"].items():
        lines += [f"### {category}", "", "| Group | Mean share | Min | Max | Present | Status |",
                  "|---|---:|---:|---:|---:|---|"]
        for group, stats in value["summary"].items():
            lines.append(f"| {group} | {_p(stats['mean_share'])} | {_p(stats['min_share'])} | "
                         f"{_p(stats['max_share'])} | {_p(stats['present_fraction'])} | {stats['status']} |")
        lines.append("")
    lines += ["## Research freeze decision", "",
              "The M9B implementation and conclusions contain no discovered mathematical or implementation error. "
              "The final research architecture is frozen. No GNN, causal method, log modality, detector-v3, feature family, or new ranker is started in M10A.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def render_claims(result: dict, m9b: dict, path: Path) -> None:
    support = result["supporting_claim_statistics"]
    fusion = result["fusion"]
    metric_trace = support["metric_vs_trace_216"]
    heuristic = support["learned_metric_vs_max_shift_336"]
    code = support["code_fault_metric_vs_trace_36"]
    full = result["metric_denominators"]["full_360"]["overall"]
    claims = [
        {
            "claim": "Metric evidence substantially improves localization over trace-only evidence",
            "hypothesis": "Metric LambdaMART has higher incident-level AC@1 and MRR than trace-only soft_hybrid_v1.",
            "status": "SUPPORTED", "dataset": "RE2-OB, RE2-TT, RE3-OB, and RE3-TT.",
            "protocol": "Frozen M9B metric model and unchanged trace baseline rank identical incidents.",
            "denominator": "216 externally triggered, root-observable cases.",
            "baseline": "Unchanged M7 soft_hybrid_v1 trace ranking.", "metric": "AC@1 and MRR.",
            "result": f"Metric AC@1 {_p(metric_trace['metric']['ac_at_1'])} vs trace {_p(metric_trace['trace']['ac_at_1'])}.",
            "ci": f"Paired ΔAC@1 {_delta(metric_trace['paired'], 'ac_at_1')}; ΔMRR {_delta(metric_trace['paired'], 'mrr')}.",
            "limitation": "This supports the metric-evidence claim, not a claim that traces alone caused the full improvement.",
        },
        {
            "claim": "Full multimodal fusion improves metrics-only under matched cross-system training",
            "hypothesis": "All-modality LambdaMART has higher AC@1 and MRR than metrics-only under the same folds and training recipe.",
            "status": "PARTIALLY SUPPORTED / METRIC-DEPENDENT",
            "dataset": "RE2-OB, RE2-TT, RE3-OB, and RE3-TT.",
            "protocol": "Frozen RE2 cross-system folds; identical candidates, parameters, rounds, and rows.",
            "denominator": "216 matched externally triggered, root-observable cases; per-suite results are also reported.",
            "baseline": "Metrics-only LambdaMART retrained under the frozen all-modality protocol.", "metric": "AC@1 and MRR.",
            "result": f"All-modality AC@1 {_p(fusion['all_modalities']['ac_at_1'])} vs metrics-only {_p(fusion['metrics_only']['ac_at_1'])}.",
            "ci": f"Paired ΔAC@1 {_delta(fusion['paired_all_minus_metrics'], 'ac_at_1')}; "
                  f"ΔMRR {_delta(fusion['paired_all_minus_metrics'], 'mrr')}.",
            "limitation": "The AC@1 CI touches zero, so its gain is not statistically stable; MRR is supported. "
                          "The aggregate gain is driven by RE2-TT, and RE3-OB has only six descriptive incidents.",
        },
        {
            "claim": "The service-invariant representation transfers across systems",
            "hypothesis": "Identity-free metric and multimodal rankers retain useful accuracy on held-out systems.",
            "status": "SUPPORTED WITH COVERAGE QUALIFICATION", "dataset": "Synthetic RE1 plus external RE2/RE3 suites.",
            "protocol": "RE1 system holdouts and frozen external evaluation with service/system/case/root/fault identity forbidden.",
            "denominator": "RE1 fold-specific held-out cases; 336 observable and 360 full-denominator external metric cases.",
            "baseline": "No single competing baseline; the test is performance under held-out-system and external transfer.",
            "metric": "AC@1 and MRR per fold, conditional external, and full external denominator.",
            "result": "RE1 held-out AC@1 is 51.2%, 93.6%, and 78.9%; conditional external AC@1 is 81.8%.",
            "ci": "Seed-robustness CIs are reported in docs/m10a-results.md; no single pooled transfer-delta CI applies.",
            "limitation": f"Full-denominator external AC@1 is {_p(full['ac_at_1'])}; RE3-OB root observability is 6/30.",
        },
        {
            "claim": "Learning-to-Rank outperforms the simple metric heuristic",
            "hypothesis": "Metric LambdaMART has higher AC@1 and MRR than metric_max_shift on matched cases.",
            "status": "SUPPORTED", "dataset": "All RE2/RE3 metric suites.",
            "protocol": "Frozen RE1-trained metric LambdaMART versus deterministic metric_max_shift.",
            "denominator": "336 identical root-observable external cases.", "baseline": "metric_max_shift heuristic.",
            "metric": "AC@1 and MRR.",
            "result": f"Learned AC@1 {_p(heuristic['learned']['ac_at_1'])} vs heuristic {_p(heuristic['heuristic']['ac_at_1'])}.",
            "ci": f"Paired ΔAC@1 {_delta(heuristic['paired'], 'ac_at_1')}; ΔMRR {_delta(heuristic['paired'], 'mrr')}.",
            "limitation": "The learned score is not a calibrated probability.",
        },
        {
            "claim": "Adding metrics improves observable code-fault localization",
            "hypothesis": "Metric LambdaMART has higher AC@1 and MRR than trace-only ranking on RE3 code faults.",
            "status": "SUPPORTED WITH COVERAGE QUALIFICATION", "dataset": "RE3-OB and RE3-TT.",
            "protocol": "Frozen metric LambdaMART versus unchanged soft_hybrid_v1 on identical observable incidents.",
            "denominator": "36 root-observable code-fault cases.", "baseline": "Unchanged M7 soft_hybrid_v1 trace ranking.",
            "metric": "AC@1 and MRR.",
            "result": f"Metric AC@1 {_p(code['metric']['ac_at_1'])} vs trace {_p(code['trace']['ac_at_1'])}.",
            "ci": f"Paired ΔAC@1 {_delta(code['paired'], 'ac_at_1')}; ΔMRR {_delta(code['paired'], 'mrr')}.",
            "limitation": "Only 6/30 RE3-OB roots are observable; the result does not cover all RE3-OB incidents.",
        },
        {
            "claim": "Hard anomaly gating limits autonomous end-to-end RCA",
            "hypothesis": "Autonomous M5-gated end-to-end accuracy is materially lower than externally triggered localization.",
            "status": "SUPPORTED AS A DESCRIPTIVE SYSTEM RESULT", "dataset": "RCAEval RE2/RE3 trace-capable suites.",
            "protocol": "Frozen M5/v1 detector followed by RCA, shown alongside externally triggered M9B localization.",
            "denominator": "Autonomous detection/end-to-end: 240 cases; triggered metric comparison: 216 observable cases.",
            "baseline": "Externally triggered M9B metric LambdaMART is the reference mode.",
            "metric": "Detection recall, healthy FPR, end-to-end AC@1, and triggered conditional AC@1.",
            "result": f"M5 recall {_p(m9b['multisource_study']['autonomous_m5_trigger']['detection_recall'])}, autonomous AC@1 "
                      f"{_p(m9b['multisource_study']['autonomous_m5_trigger']['end_to_end_ac_at_1'])}, triggered AC@1 "
                      f"{_p(m9b['multisource_study']['baselines']['m9b_metric_lambdamart']['ac_at_1'])}.",
            "ci": "Not applicable: denominators and conditioning differ, so no paired effect CI is claimed.",
            "limitation": "This is a descriptive system comparison, not a paired causal estimate.",
        },
        {
            "claim": "Trace-only temporal CUSUM transfers across domains",
            "hypothesis": "Synthetic-selected detector-v2 improves external recall while satisfying the preregistered healthy-FPR gate.",
            "status": "REJECTED", "dataset": "Synthetic A/B/C validation followed by 240 RCAEval incidents and 240 paired controls.",
            "protocol": "Detector-v2 was selected on synthetic data and frozen before external evaluation.",
            "denominator": "240 external fault cases and 240 paired pseudo-healthy controls.",
            "baseline": "Frozen M5/v1 detector plus the preregistered external acceptance gate.",
            "metric": "Detection recall and healthy false-positive rate.",
            "result": "External recall reached 99.6%, but healthy FPR also reached 99.6%; verdict NOT_JUSTIFIED.",
            "ci": "M9A paired recall-difference CI [0.404, 0.529]; FPR-difference CI [0.887, 0.958].",
            "limitation": "Sequence-length and domain calibration failed; detector-v2 is excluded from the final method.",
        },
    ]
    lines = ["# Thesis claim registry", "",
             "This registry is the allowed wording for the final thesis. Every claim states its protocol, denominator, result, and limitation.", ""]
    for number, claim in enumerate(claims, 1):
        lines += [f"## Claim {number}", "", f"- **CLAIM:** {claim['claim']}.",
                  f"- **HYPOTHESIS:** {claim['hypothesis']}", f"- **STATUS:** {claim['status']}.",
                  f"- **DATASET:** {claim['dataset']}", f"- **PROTOCOL:** {claim['protocol']}",
                  f"- **DENOMINATOR:** {claim['denominator']}", f"- **BASELINE:** {claim['baseline']}",
                  f"- **METRIC:** {claim['metric']}", f"- **RESULT:** {claim['result']}",
                  f"- **95% CI:** {claim['ci']}", f"- **LIMITATION:** {claim['limitation']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def render_history(result: dict, m9b: dict, path: Path) -> None:
    fusion = result["fusion"]
    rows = [
        ("M5", "Can robust baseline statistics detect service anomalies?", "Implemented median/MAD latency and two-proportion error detection.", "Retain as secondary autonomous trigger; external recall remains limiting."),
        ("M6", "Can trace topology and local evidence explain an incident?", "Implemented deterministic max-severity, topology, local-evidence, and hybrid rankings over hard-gated candidates.", "Retain as explainable historical baselines; remove hard gate from final primary mode."),
        ("M7", "Can service-invariant Learning-to-Rank improve RCA?", "Same-system test AC@1 92.7%; truth isolation, permutation, root holdout, and SHAP checks passed.", "Promising first learned ranker; external transfer still unproven."),
        ("M8A", "Does the representation transfer to unseen synthetic topologies?", "Frozen M7 AC@1 93.8%/94.0% on Topologies B/C; system-holdout remained strong.", "Accept synthetic cross-topology transfer; require external benchmark."),
        ("M8B", "Does trace-only RCA transfer to RCAEval?", "M5 recall 52.9%; frozen M7 conditional AC@1 17.3%; detector and trace-domain shift limited the pipeline.", "Partial external transfer; investigate detection and missing modalities."),
        ("M9A", "Can a trace-only temporal CUSUM repair detection?", "Synthetic recall 100% at 0% FPR, but external recall/FPR both 99.6%.", "REJECT detector-v2; preserve the negative result."),
        ("M9B", "Do robust metrics and multimodal soft evidence improve localization?",
         f"Metric LambdaMART AC@1 80.1%; all-modality AC@1 70.4%; matched fusion delta {_p(fusion['paired_all_minus_metrics']['ac_at_1']['difference'])}.",
         "Accept M9B as final research core, coverage-qualified."),
    ]
    lines = ["# Final RCA research summary", "", "## Milestone history", "",
             "| Milestone | Hypothesis | Result | Decision |", "|---|---|---|---|"]
    for milestone, hypothesis, outcome, decision in rows:
        lines.append(f"| {milestone} | {hypothesis} | {outcome} | {decision} |")
    lines += ["", "## Final frozen research architecture", "", "```text",
              "Incident trigger", "      ↓", "Metrics + distributed traces", "      ↓",
              "Automatically reconstructed topology", "      ↓",
              "Robust statistical and fixed-time temporal feature extraction", "      ↓",
              "Service-invariant diagnostic representation", "      ↓",
              "LambdaMART Learning-to-Rank", "      ↓", "Top-K root-cause services", "      ↓",
              "Machine-readable evidence and predictive explanation", "```", "",
              "Primary mode is externally triggered root-cause localization. Secondary mode is frozen M5/v1 detection followed by RCA. "
              "M9A detector-v2 is rejected and excluded.", "", "## Final limitations", "",
              "1. Primary localization requires an external incident trigger.",
              "2. Output and truth are evaluated at service-level granularity.",
              "3. Unobservable roots cannot be localized and are failures in full-denominator reporting.",
              "4. Validation combines controlled synthetic systems and the RCAEval benchmark; it is not unrestricted production evidence.",
              "5. Infrastructure/database entities are outside the current service candidate universe.",
              "6. Logs are not used.", "7. Ranking scores are not calibrated probabilities.",
              "8. Gain importance and TreeSHAP are predictive, not causal.",
              "9. Simultaneous multi-root incidents are not evaluated.",
              "10. Frozen M5/v1 remains the limiting component in autonomous mode.", "",
              "## Freeze", "", "The research method is frozen after M10A. No GNN, causal model, log modality, detector-v3, or new ranker is justified by the current evidence. The next allowed milestone is demo/productization, not a new research method.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _metric_row(name: str, value: dict) -> str:
    return f"| {name} | {value['cases']} | {_p(value['ac_at_1'])} | {_p(value['ac_at_3'])} | {_p(value['mrr'])} |"


def _delta(paired: dict, metric: str) -> str:
    value = paired[metric]
    return f"{value['difference']:+.3f} [{value['ci_low']:+.3f}, {value['ci_high']:+.3f}]"


def _stability_row(name: str, ac1: dict, mrr: dict) -> str:
    return (f"| {name} | {ac1['mean']:.3f}±{ac1['std']:.3f} | {ac1['min']:.3f}–{ac1['max']:.3f} | "
            f"[{ac1['ci_low']:.3f}, {ac1['ci_high']:.3f}] | {mrr['mean']:.3f}±{mrr['std']:.3f} | "
            f"{mrr['min']:.3f}–{mrr['max']:.3f} | [{mrr['ci_low']:.3f}, {mrr['ci_high']:.3f}] |")


def _p(value: float) -> str:
    return f"{100 * value:.1f}%"
