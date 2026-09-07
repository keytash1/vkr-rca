"""Render compact human and machine M12 result artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


LABELS = {
    "chance": "Chance",
    "metric_heuristic": "Metric heuristic",
    "m10c": "M10C",
    "m10d_top3": "M10D Top-3",
    "m11_top5": "M11 Top-5",
}


def _table(metrics: dict) -> str:
    lines = ["| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in LABELS:
        value = metrics[name]
        lines.append(f"| {LABELS[name]} | {value['ac_at_1']:.4f} | {value['ac_at_2']:.4f} | {value['ac_at_3']:.4f} | {value['ac_at_5']:.4f} | {value['ac_at_10']:.4f} | {value['mrr']:.4f} | {value['candidate_universe_coverage']:.4f} |")
    return "\n".join(lines)


def _group_tables(groups: dict) -> str:
    blocks = []
    for group, values in groups.items():
        blocks.append(f"### `{group}`\n\n{_table(values)}")
    return "\n\n".join(blocks)


def write_reports(root: Path, evaluation: dict) -> None:
    pooled = evaluation["pooled"]
    m11 = pooled["m11_top5"]
    ci = m11["absolute_wilson_95"]
    paired = evaluation["paired_m11_vs"]
    operational = evaluation["operational"]
    results = f"""# M12 Results — Frozen Unseen-System Shadow Validation

System: DeathStarBench Hotel Reservation at `6ecb09706140f8730b5385c08f1386c654c3c526`.
All {evaluation['valid_incidents']} incidents are newly generated M12 locked data; model training count is zero.

{_table(pooled)}

M11 absolute Wilson 95% intervals: AC@1 `{ci['ac_at_1']}`, AC@2 `{ci['ac_at_2']}`,
AC@3 `{ci['ac_at_3']}`, AC@5 `{ci['ac_at_5']}`, AC@10 `{ci['ac_at_10']}`.
All incident and `(root_service, fault_family)` cluster paired intervals are in
`ml/models/m12/evaluation.json`; cluster intervals are the claim gate.

## Per fault family

{_group_tables(evaluation['per_fault'])}

## Per root service

{_group_tables(evaluation['per_root'])}

## Macro averages

### Fault-family macro

{_table(evaluation['macro_fault'])}

### Root-service macro

{_table(evaluation['macro_root'])}

## Operational profile

- Service count: `{operational['service_count']}`.
- Healthy + locked metric samples: `{operational['healthy_telemetry_samples']}` + `{operational['locked_telemetry_samples']}`.
- Adapter completeness / errors: `{operational['adapter_completeness']:.4f}` / `{operational['adapter_error_count']}`.
- Telemetry completeness: `{operational['telemetry_completeness']:.4f}`.
- Full inference median / p95: `{operational['inference_latency_ms']['median']:.3f}` / `{operational['inference_latency_ms']['p95']:.3f}` ms.
- Canonical window-to-output median / p95: `{operational['canonical_window_to_output_latency_ms']['median']:.3f}` / `{operational['canonical_window_to_output_latency_ms']['p95']:.3f}` ms.
- M11 evidence reranker median / p95: `{operational['component_latency_ms']['m11_evidence_reranker_ms']['median']:.3f}` / `{operational['component_latency_ms']['m11_evidence_reranker_ms']['p95']:.3f}` ms.
- Frozen model artifacts: `{operational['frozen_model_artifact_bytes']}` bytes.
- Peak RCA process RAM: `{operational['peak_process_ram_mb']:.3f}` MiB.
- Startup readiness: `{operational['startup_readiness']}`.

The full error list and all paired intervals are preserved in the machine-readable
evaluation artifact. Raw telemetry and sealed truth remain ignored under
`external-data/m12/`.

## Decisions

- M12_SYSTEM_DEPLOYMENT: PASS
- M12_TELEMETRY_PIPELINE: PARTIAL
- M12_LOCKED_INCIDENT_SET: PASS
- NEW_SYSTEM_TRANSFER: {evaluation['verdicts']['NEW_SYSTEM_TRANSFER']}
- TOP5_TRANSFER_GAIN: {evaluation['verdicts']['TOP5_TRANSFER_GAIN']}
- M12_TRACE_MODALITY: {evaluation['verdicts']['M12_TRACE_MODALITY']}
- M12_RESEARCH_CHAMPION: {_champion(evaluation)}

Telemetry is PARTIAL because metrics and Jaeger collection are deployed, but
the frozen inference path does not introduce a new M12 trace feature adapter.
Scores are association rankings, not causal verification or probabilities.

## Protocol deviations

- Healthy warm-up reduced from 300 to 60 seconds.
- Healthy baseline reduced from 900 to 180 seconds due the 2 CPU/8 GiB local environment and 50 live runs.
- cAdvisor was replaced before accepted healthy data because its Docker API was incompatible; the frozen replacement exporter uses Docker API v1.44 and one-second Prometheus scraping.
- Jaeger covers eight services, but trace-to-feature adaptation remains unavailable; frozen missing-modality semantics were used.
- The first evaluation attempt stopped before metric computation because its denominator assertion called `set()` on index dictionaries. The original freeze and first sealed-prediction hash are retained; the corrected attempt was allowed only because the assertion-only fix reproduced byte-identical predictions.
"""
    (root / "docs/m12-results.md").write_text(results)

    stages = Counter(item["primary_stage"] for item in evaluation["errors"])
    flags = Counter(flag for item in evaluation["errors"] for flag in item["diagnostic_flags"])
    error_doc = f"""# M12 Error Analysis

The final M11 Top-5 ranking has {len(evaluation['errors'])} Top-1 errors over the full
{evaluation['valid_incidents']}-incident valid denominator. Primary mutually exclusive stages:
`{dict(stages)}`. Overlapping descriptive flags: `{dict(flags)}`.

Truth-rank histogram: `{evaluation['truth_rank_histogram']}`.
Oracle candidate ceilings: `{evaluation['oracle_ceilings']}`.

Every error record is in `ml/models/m12/evaluation.json`. `MISSING_TRACES` means
the frozen canonical inference path had no trace vector; `OOD_DOMAIN_SHIFT`
describes the intentionally unseen domain and is not a causal diagnosis. No
incident was excluded because its anomaly was difficult for RCA to detect.
"""
    (root / "docs/m12-error-analysis.md").write_text(error_doc)

    claims = [
        ("Zero-shot new-system transfer", evaluation["verdicts"]["NEW_SYSTEM_TRANSFER"], "M11 Top-5 vs chance and generic metric heuristic", "AC@1/MRR", paired["chance"]["mrr"]),
        ("M11 Top-5 gain transfer", evaluation["verdicts"]["TOP5_TRANSFER_GAIN"], "Frozen M10D Top-3", "AC@1/MRR with AC@3 guardrail", paired["m10d_top3"]["mrr"]),
        ("Candidate-universe coverage", "SUPPORTED" if m11["candidate_universe_coverage"] >= .9 else "NOT_SUPPORTED", "Full metadata-derived service universe", "candidate coverage", None),
        ("Frozen service-invariant representation usefulness", evaluation["verdicts"]["NEW_SYSTEM_TRANSFER"], "Chance and generic metric heuristic", "AC@1/MRR", paired["metric_heuristic"]["mrr"]),
        ("Production-like telemetry adapter feasibility", "SUPPORTED_WITH_QUALIFICATION", "one-second Prometheus metrics", "coverage/adapter failures", None),
        ("Missing-modality behavior", "DESCRIPTIVE_ONLY", "frozen missing-trace semantics", "ranking metrics", None),
    ]
    blocks = []
    for claim, status, baseline, metric, interval in claims:
        blocks.append(f"""## {claim}

- CLAIM: {claim}.
- HYPOTHESIS: The frozen service-invariant pipeline remains useful without M12 training.
- STATUS: {status}.
- DATASET: M12 Hotel Reservation locked-v1.
- DATA ROLE: USED_TEST.
- SYSTEM: DeathStarBench Hotel Reservation.
- PROTOCOL: `docs/m12-protocol.md`; one-time evaluation after SHA-256 freeze.
- DENOMINATOR: {evaluation['valid_incidents']} independently valid incidents.
- BASELINE: {baseline}.
- METRIC: {metric}.
- RESULT: AC@1 {m11['ac_at_1']:.4f}; MRR {m11['mrr']:.4f}; coverage {m11['candidate_universe_coverage']:.4f}.
- INCIDENT CI: {interval['incident']['ci95'] if interval else 'not applicable'}.
- CLUSTER CI: {interval['cluster']['ci95'] if interval else 'not applicable'}.
- LIMITATION: one public system, five container-scoped fault families; trace features absent from canonical inference.
""")
    (root / "docs/m12-claim-registry.md").write_text("# M12 Claim Registry\n\n" + "\n".join(blocks))


def write_integrity(root: Path) -> dict:
    names = [
        "docs/m12-protocol.md", "docs/m12-system-selection.md", "docs/m12-deployment.md",
        "docs/m12-adapter-contract.md", "docs/m12-results.md", "docs/m12-error-analysis.md",
        "docs/m12-claim-registry.md", "ml/models/m12/preflight.json",
        "ml/models/m12/data-ledger.json", "ml/models/m12/system-manifest.json",
        "ml/models/m12/adapter-manifest.json", "ml/models/m12/incident-plan.json",
        "ml/models/m12/freeze-manifest.json", "ml/models/m12/freeze-manifest-attempt-1.json",
        "ml/models/m12/evaluation.json",
        "ml/rca_ml/m12_adapter.py", "ml/rca_ml/m12_evaluate.py", "ml/rca_ml/m12_shadow.py",
        "scripts/m12/run.py", "scripts/m12/freeze.py", "scripts/m12/workload.py",
        "deploy/m12/compose.yml", "deploy/m12/Dockerfile.hotel", "deploy/m12/Dockerfile.exporter",
    ]
    result = {"version": "m12-integrity-v1", "sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}}
    (root / "ml/models/m12/integrity-manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _champion(evaluation: dict) -> str:
    if evaluation["verdicts"]["NEW_SYSTEM_TRANSFER"] in {"STRONGLY_SUPPORTED", "SUPPORTED"}:
        return "PROMOTE_M11_AS_EXTERNALLY_VALIDATED"
    if evaluation["verdicts"]["NEW_SYSTEM_TRANSFER"] == "WEAK":
        return "KEEP_M11_WITH_TRANSFER_QUALIFICATION"
    return "M11_TRANSFER_NOT_SUPPORTED"
