#!/usr/bin/env python3
"""Render already-opened M14 evidence; never collect, rank, train or retune."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "ml/models/m14"
RUN = ROOT / "external-data/m14/runs/locked-v1"
METRICS = ("ac_at_1", "ac_at_2", "ac_at_3", "ac_at_5", "ac_at_10", "mrr", "candidate_universe_coverage")


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def table(rows):
    lines = ["| Model / group | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, values in rows:
        lines.append("| " + name + " | " + " | ".join(f"{values[key]:.4f}" for key in METRICS) + " |")
    return "\n".join(lines)


def main():
    evaluation = read(MODEL / "evaluation.json")
    opening = read(MODEL / "evaluation-opened.marker")
    scoring = read(MODEL / "scoring-completed.marker")
    freeze = read(MODEL / "freeze-manifest.json")
    assert opening["opened"] and evaluation["research_status"] == "FINAL_RESEARCH_FREEZE"
    assert opening["prediction_sha256"] == evaluation["prediction_sha256"] == scoring["prediction_sha256"]
    assert digest(RUN / "locked/sealed-predictions.json") == scoring["prediction_sha256"]
    assert digest(RUN / "locked/truth.sealed.jsonl") == freeze["locked_truth_sha256"]
    truth = jsonl(RUN / "locked/truth.sealed.jsonl")
    index = jsonl(RUN / "locked/telemetry-index.jsonl")
    plan = read(MODEL / "incident-plan.json")["incidents"]
    assert len(truth) == len(index) == len(plan) == 50
    assert {x["incident_id"] for x in truth} == {x["incident_id"] for x in index} == {x["incident_id"] for x in plan}
    assert all(x["valid_injection"] for x in truth)
    write_json(MODEL / "evaluation-inputs.json", {
        "data_role": "USED_TEST", "purpose": "Independent metric reproduction, never model selection",
        "source_truth_sha256": freeze["locked_truth_sha256"],
        "source_prediction_sha256": scoring["prediction_sha256"],
        "truth": [{key: value for key, value in item.items() if key != "injection_evidence"} for item in truth],
        "predictions": read(RUN / "locked/sealed-predictions.json"),
    })
    clusters = Counter((x["root_service"], x["fault_family"]) for x in truth)
    assert len(clusters) == 25 and set(clusters.values()) == {2}
    workload_statuses, candidate_pairs, trace_counts = Counter(), [], []
    attempts, timings, modality_missing = 0, [], []
    for item in index:
        path = RUN / item["telemetry_path"]
        assert digest(path) == item["sha256"] == freeze["telemetry_sha256"][item["incident_id"]]
        payload = read(path)
        assert payload["end_unix"] - payload["start_unix"] == 30
        result = json.loads(payload["workload_result"]["stdout"])
        attempts += result["attempts"]
        workload_statuses.update(result["statuses"])
        candidate_pairs.append(len({(x["service"], x["family"]) for x in payload["metrics"]}))
        trace_counts.append(len(payload["traces"]))
        timings.append((payload["start_unix"], payload["end_unix"]))
        if not payload["metrics"] or not payload["traces"]:
            modality_missing.append(item["incident_id"])
    audit_paths = sorted((RUN / "locked/attempts").glob("*.json"))
    rejected = [path.name for path in audit_paths if not read(path)["truth"]["valid_injection"]]
    audit = {
        "valid_incidents": 50, "clusters": 25, "repetitions_per_cluster": 2,
        "fault_counts": dict(Counter(x["fault_family"] for x in truth)),
        "root_counts": dict(Counter(x["root_service"] for x in truth)),
        "all_windows_exactly_30_seconds": True,
        "workload_operations": attempts, "workload_statuses": dict(workload_statuses),
        "metric_pairs_min": min(candidate_pairs), "metric_pairs_max": max(candidate_pairs),
        "spans_min": min(trace_counts), "spans_max": max(trace_counts), "spans_total": sum(trace_counts),
        "missing_modality_incidents": modality_missing,
        "accepted_retry_count": sum(x["collection_attempt"] - 1 for x in truth),
        "raw_attempts": len(audit_paths), "rejected_attempts": rejected,
        "collection_start_unix": min(x[0] for x in timings),
        "collection_end_unix": max(x[1] for x in timings),
        "attempt_sha256": {str(path.relative_to(RUN)): digest(path) for path in audit_paths},
        "canary_sha256": digest(RUN / "canary/validity.json"),
    }
    write_json(MODEL / "collection-audit.json", audit)
    ledger = read(ROOT / "ml/models/m13/data-ledger.json")
    ledger.update({"version": "m14-final-data-ledger-v1", "reserved_final_scored": True,
                   "research_status": "FINAL_RESEARCH_FREEZE"})
    ledger["roles"]["OpenTelemetry-AstronomyShop"] = "USED_TEST"
    ledger["roles"]["M14-Healthy"] = "HEALTHY_ONLY_ADAPTER_FIT_BEFORE_INJECTION"
    ledger["roles"]["M14-Canary"] = "MECHANICAL_VALIDATION_ONLY_NOT_EVALUATED"
    write_json(MODEL / "data-ledger.json", ledger)

    lines = ["# M14 Final Locked Transfer Results", "",
             f"Verdict: **{evaluation['verdict']}**. Data role: **USED_TEST**. Research status: **FINAL_RESEARCH_FREEZE**.", "",
             "One sealed 50-incident test on OpenTelemetry Astronomy Shop; 25 root/fault clusters, two repetitions each. No post-test model changes.", "",
             "## Pooled results", "", table(evaluation["pooled"].items()), "",
             "## Absolute Wilson 95% intervals", "",
             "| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 |", "|---|---|---|---|---|---|"]
    for name, values in evaluation["pooled"].items():
        lines.append("| " + name + " | " + " | ".join(f"[{low:.4f}, {high:.4f}]" for low, high in (values["absolute_wilson_95"][key] for key in METRICS[:5])) + " |")
    lines += ["", "## Paired M13 differences", "", "10,000 resamples per interval. Cluster CI is the preregistered significance gate; 25 root/fault clusters. Positive means M13 is better.", "",
              "| Comparator | Metric | Delta | Incident 95% CI | Cluster 95% CI | Positive cluster CI |", "|---|---|---:|---|---|---|"]
    for baseline, comparisons in evaluation["paired_m13_vs"].items():
        for metric, values in comparisons.items():
            a, b = values["incident"]["ci95"], values["cluster"]["ci95"]
            lines.append(f"| {baseline} | {metric} | {values['cluster']['observed_delta']:.4f} | [{a[0]:.4f}, {a[1]:.4f}] | [{b[0]:.4f}, {b[1]:.4f}] | {values['cluster']['supported_positive']} |")
    for dimension in ("fault", "root"):
        lines += ["", f"## Per {dimension}", ""]
        for name, values in evaluation[f"per_{dimension}"].items():
            lines += [f"### {name} (n=10)", "", table(values.items()), ""]
        lines += [f"### Macro {dimension}", "", table(evaluation[f"macro_{dimension}"].items()), ""]
        worst = {model: {metric: min(group[model][metric] for group in evaluation[f"per_{dimension}"].values()) for metric in METRICS} for model in evaluation["pooled"]}
        lines += [f"### Worst {dimension}, metric-wise minimum", "", "Different columns may attain their minimum in different groups; this is not a synthetic incident group.", "", table(worst.items()), ""]
    lines += ["## Locked gates", "", "```json", json.dumps(evaluation["verdict_gates"], indent=2, sort_keys=True), "```", "",
              "## Collection and scope", "",
              f"Healthy warm-up: 1,800/1,800 HTTP 200; healthy baseline: 5,400/5,400 HTTP 200. Healthy telemetry: 43,248 metric samples / 48 service-family pairs / 123,218 native spans. All five mechanism canaries passed after a Docker process-inspection compatibility fix.", "",
              f"Accepted corpus operations: {attempts}; statuses: `{dict(workload_statuses)}`. These are fault-exposed operations, not healthy failures to exclude. Raw attempts retained: {len(audit_paths)}; rejected mechanical attempts: {len(rejected)}. Native spans: {sum(trace_counts)}; per-incident range {min(trace_counts)}–{max(trace_counts)}. Metric-pair range: {min(candidate_pairs)}–{max(candidate_pairs)} of 48.", "",
              "The fixed observation window is 30 seconds; slow requests are drained after fault reset. Missing telemetry is not fabricated. Healthy-only target adaptation is permitted, but target fault labels never train a model.", "",
              f"Scoring latency is the combined four-method pipeline, not M13 alone: median {scoring['latency_ms']['median']:.2f} ms, p95 {scoring['latency_ms']['p95']:.2f} ms, maximum {scoring['latency_ms']['max']:.2f} ms; total {scoring['wall_seconds']:.2f} seconds. It is offline evidence, not a production latency SLA.", "",
              "## Limitations", "",
              "- One new system, five represented fault families and five injected roots; not arbitrary unseen-fault or production generalization.",
              "- A single deterministic workload, 30-second windows, two repetitions per root/fault cluster, one host/run. Temporal carryover and co-load are not ruled out by cluster bootstrap.",
              "- All candidates and PostgreSQL have a precollection 512 MiB ceiling; Checkout/ProductCatalog Go soft limit is 384 MiB. This differs from upstream defaults. Deployment/build exceptions and failed precollection smoke gates remain in `m14-engineering-log.md`.",
              "- Docker ran with two CPUs and about 7.74 GiB RAM, alongside an unrelated project that was not stopped. Source commit, exact image IDs and environment are sealed in readiness evidence.",
              "- The 32 MiB allocation demonstrates an observable memory injection, not proof of OOM or user-visible memory exhaustion. CPU, netem and pause are controlled mechanisms, not every real incident of those families.",
              "- Native trace collection is anchored at frontend traces; not a claim of complete autonomous background telemetry. Canonical metrics are Docker resource signals, not full application RED/USE instrumentation.",
              "- Rank is not causal proof or calibrated probability. Diagnostic error flags are descriptive hypotheses. No final-system ablation or retuning is authorized.",
              "- Wilson intervals are descriptive binomial intervals; paired cluster intervals are primary for comparisons. Gates use AC@1 OR MRR as registered, without a new multiplicity correction.", "",
              "Full grouped Wilson intervals and incident-level error records are in `ml/models/m14/evaluation.json`. Compact truth labels and all four sealed rankings are published in `evaluation-inputs.json` for independent metric reproduction (USED_TEST, never training). Original raw telemetry, process evidence and sealed files remain locally under `external-data/m14/runs/locked-v1/`, not embedded in Git."]
    (ROOT / "docs/m14-results.md").write_text("\n".join(lines) + "\n")
    errors = evaluation["error_analysis"]
    lines = ["# M14 Error Analysis", "", "No model changes follow this analysis. Error stages follow the preregistered truth rank; diagnostic flags are not causal truth.", "",
             "```json", json.dumps(errors["histogram"], indent=2, sort_keys=True), "```", "",
             "| Incident | Root | Fault | Rank | Stage | Descriptive flags |", "|---|---|---|---:|---|---|"]
    for error in errors["errors"]:
        lines.append(f"| {error['incident_id']} | {error['root_service']} | {error['fault_family']} | {error['truth_rank']} | {error['primary_stage']} | {', '.join(error['diagnostic_flags'])} |")
    lines += ["", "`OOD_DOMAIN_SHIFT` marks the held-out domain context; it does not prove why a particular ranking failed. `LOW_WORKLOAD_SIGNAL` means most workload operations timed out or returned 5xx, not that the injection is invalid. Other possible mechanisms are not assigned without evidence."]
    (ROOT / "docs/m14-error-analysis.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"verdict": evaluation["verdict"], "collection_audit": {k: v for k, v in audit.items() if k != "attempt_sha256"}, "reports_written": True}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
