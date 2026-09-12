"""Run the M13 cross-domain development and hardening experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import sha256_file
from .m12_adapter import canonical_features, robust_baseline
from .m12_evaluate import rank_candidates
from .m13_features import (
    COVERAGE_FEATURES,
    DIRECT_FEATURES,
    DISAPPEARANCE_FEATURES,
    FEATURES,
    PROPAGATION_FEATURES,
    RANKING_FEATURES,
    TRACE_FEATURES,
    build_candidate_rows,
    fit_healthy_baseline,
)
from .m13_protocol import (
    SEED,
    assert_selection_ids_allowed,
    cluster_key,
    deterministic_chance,
    grouped_folds,
    paired_bootstrap,
    rank_scores,
    ranking_metrics,
    truth_rank,
)

SEEDS = tuple(range(SEED, SEED + 5))
GRID = tuple(
    {"max_depth": depth, "eta": eta, "rounds": rounds}
    for depth in (2, 3) for eta in (.03, .08) for rounds in (24, 48)
)
FIXED = {"max_depth": 2, "eta": .08, "rounds": 24}

ABLATIONS = {
    "metrics_only": DIRECT_FEATURES + COVERAGE_FEATURES,
    "traces_only": TRACE_FEATURES + COVERAGE_FEATURES,
    "metrics_traces": DIRECT_FEATURES + TRACE_FEATURES + COVERAGE_FEATURES,
    "metrics_disappearance": DIRECT_FEATURES + DISAPPEARANCE_FEATURES + COVERAGE_FEATURES,
    "metrics_propagation": DIRECT_FEATURES + PROPAGATION_FEATURES + COVERAGE_FEATURES,
    "metrics_traces_propagation": DIRECT_FEATURES + TRACE_FEATURES + PROPAGATION_FEATURES + COVERAGE_FEATURES,
    "full_without_ranking_context": FEATURES,
    "full_with_ranking_context": FEATURES + RANKING_FEATURES,
}


def _parameters(config: dict, seed: int) -> dict:
    return {
        "objective": "rank:ndcg", "eval_metric": "ndcg@3", "tree_method": "hist",
        "lambdarank_pair_method": "topk", "lambdarank_num_pair_per_sample": 5,
        "max_depth": config["max_depth"], "eta": config["eta"],
        "min_child_weight": 2, "subsample": .8, "colsample_bytree": .8,
        "seed": seed, "nthread": 2,
    }


def _matrix(rows_by_id: dict[str, list[dict]], ids: list[str], columns: tuple[str, ...], labels: bool):
    selected, groups = [], []
    for incident_id in sorted(ids):
        rows = sorted(rows_by_id[incident_id], key=lambda item: item["service"])
        selected.extend(rows)
        groups.append(len(rows))
    matrix = np.asarray([[row["features"][name] for name in columns] for row in selected], dtype=np.float32)
    target = np.asarray([row["target"] for row in selected], dtype=np.float32) if labels else None
    data = xgb.DMatrix(matrix, label=target, feature_names=list(columns))
    data.set_group(np.asarray(groups, dtype=np.uint32))
    return data, selected


def _fit(rows_by_id, ids, columns, config, seed):
    data, _ = _matrix(rows_by_id, list(ids), columns, True)
    return xgb.train(_parameters(config, seed), data, num_boost_round=config["rounds"], verbose_eval=False)


def _predict(model, rows_by_id, ids, columns, transform=None):
    data, selected = _matrix(rows_by_id, list(ids), columns, False)
    if transform is not None:
        matrix = np.asarray([[row["features"][name] for name in columns] for row in selected], dtype=np.float32)
        matrix = transform(matrix, selected, columns)
        data = xgb.DMatrix(matrix, feature_names=list(columns))
        groups = [len(rows_by_id[incident]) for incident in sorted(ids)]
        data.set_group(np.asarray(groups, dtype=np.uint32))
    scores = model.predict(data)
    grouped = defaultdict(dict)
    for row, score in zip(selected, scores, strict=True):
        grouped[row["incident_id"]][row["service"]] = float(score)
    return {incident: rank_scores(values) for incident, values in grouped.items()}


def fixed_oof(rows_by_id, truth, cases, columns, config, seed=SEED, assignments=None, transform=None):
    assignments = assignments or grouped_folds(cases)
    predictions, provenance = {}, []
    for fold in sorted(set(assignments.values())):
        test_ids = sorted(i for i, value in assignments.items() if value == fold)
        train_ids = sorted(set(assignments) - set(test_ids))
        assert_selection_ids_allowed(train_ids + test_ids)
        train_clusters = {cluster_key(truth[i]) for i in train_ids}
        test_clusters = {cluster_key(truth[i]) for i in test_ids}
        if train_clusters & test_clusters:
            raise ValueError("M13 repetition cluster leakage")
        fold_offset = int.from_bytes(hashlib.sha256(str(fold).encode()).digest()[:4], "big") % 100_000
        model = _fit(rows_by_id, train_ids, columns, config, seed + fold_offset)
        predictions.update(_predict(model, rows_by_id, test_ids, columns, transform=transform))
        provenance.append({
            "fold": str(fold), "train_incidents": len(train_ids), "test_incidents": len(test_ids),
            "train_test_clusters_disjoint": True, "expert_predictions_in_sample": False,
        })
    if set(predictions) != set(truth):
        raise ValueError("OOF denominator mismatch")
    return predictions, provenance


def select_config(rows_by_id, truth, cases, columns):
    assignments = grouped_folds(cases)
    search = []
    for config in GRID:
        predictions, _ = fixed_oof(rows_by_id, truth, cases, columns, config, SEED, assignments)
        metrics = ranking_metrics(predictions, truth)
        search.append({"config": config, "ac_at_1": metrics["ac_at_1"], "mrr": metrics["mrr"]})
    search.sort(key=lambda item: (-item["mrr"], -item["ac_at_1"], item["config"]["max_depth"], item["config"]["rounds"], -item["config"]["eta"]))
    return search[0]["config"], search


def _base_rank_features(rows: list[dict], ranking: list[dict]) -> None:
    rank_by_service = {item["service"]: int(item["rank"]) for item in ranking}
    score_by_service = {item["service"]: float(item["score"]) for item in ranking}
    ordered = sorted((float(item["score"]) for item in ranking), reverse=True)
    top, second = ordered[0], ordered[1] if len(ordered) > 1 else ordered[0]
    scale = max(abs(top), 1e-9)
    for row in rows:
        rank = rank_by_service[row["service"]]
        row["features"].update({
            "base_rank_percentile": 1.0 - (rank - 1) / max(1, len(rows) - 1),
            "base_relative_score": score_by_service[row["service"]] / scale,
            "base_margin": (top - second) / scale if rank == 1 else (score_by_service[row["service"]] - top) / scale,
        })


def _rerank_top_k(base: dict[str, list[dict]], scores: dict[str, list[dict]], k: int) -> dict[str, list[dict]]:
    output = {}
    for incident in sorted(base):
        initial = sorted(base[incident], key=lambda item: item["rank"])
        membership = {item["service"] for item in initial[:k]}
        learned = [{**item} for item in scores[incident] if item["service"] in membership]
        tail = [{**item} for item in initial if item["service"] not in membership]
        combined = learned + [{"service": item["service"], "score": item["score"]} for item in tail]
        for rank, item in enumerate(combined, 1): item["rank"] = rank
        output[incident] = combined
    return output


def _fusion_oof(rows_by_id, truth, cases, config, seed=SEED):
    outer = grouped_folds(cases)
    direct_columns = DIRECT_FEATURES + TRACE_FEATURES + COVERAGE_FEATURES
    contextual_columns = PROPAGATION_FEATURES + DISAPPEARANCE_FEATURES + COVERAGE_FEATURES
    fusion_columns = (
        "direct_score", "context_score", "score_mean", "score_disagreement",
        "base_rank_percentile", "candidate_count_log", "missing_metric_modality",
        "missing_trace_modality", "trace_coverage",
    )
    predictions, provenance = {}, []
    for fold in sorted(set(outer.values())):
        test_ids = sorted(i for i, value in outer.items() if value == fold)
        train_ids = sorted(set(outer) - set(test_ids))
        train_cases = [item for item in cases if item["incident_id"] in train_ids]
        inner_assignments = grouped_folds(train_cases, folds=4, seed=seed + int(fold) + 100)
        train_truth = {i: truth[i] for i in train_ids}
        direct_inner, direct_prov = fixed_oof(rows_by_id, train_truth, train_cases, direct_columns, config, seed + 200, inner_assignments)
        context_inner, context_prov = fixed_oof(rows_by_id, train_truth, train_cases, contextual_columns, config, seed + 400, inner_assignments)
        fusion_train = _fusion_rows(rows_by_id, train_ids, direct_inner, context_inner)
        fusion_model = _fit(fusion_train, train_ids, fusion_columns, config, seed + 600 + int(fold))
        direct_model = _fit(rows_by_id, train_ids, direct_columns, config, seed + 800 + int(fold))
        context_model = _fit(rows_by_id, train_ids, contextual_columns, config, seed + 1000 + int(fold))
        direct_test = _predict(direct_model, rows_by_id, test_ids, direct_columns)
        context_test = _predict(context_model, rows_by_id, test_ids, contextual_columns)
        fusion_test = _fusion_rows(rows_by_id, test_ids, direct_test, context_test)
        predictions.update(_predict(fusion_model, fusion_test, test_ids, fusion_columns))
        provenance.append({
            "outer_fold": fold, "train_incidents": len(train_ids), "test_incidents": len(test_ids),
            "fusion_training_expert_predictions": "INNER_GROUP_OOF_ONLY",
            "direct_inner_folds": direct_prov, "context_inner_folds": context_prov,
            "in_sample_expert_scores_used_for_fusion": False,
        })
    return predictions, provenance


def _fusion_rows(source, ids, direct, context):
    result = {}
    for incident in sorted(ids):
        direct_scores = {item["service"]: item["score"] for item in direct[incident]}
        context_scores = {item["service"]: item["score"] for item in context[incident]}
        result[incident] = []
        for row in source[incident]:
            one, two = float(direct_scores[row["service"]]), float(context_scores[row["service"]])
            features = row["features"]
            result[incident].append({
                "incident_id": incident, "service": row["service"], "target": row["target"],
                "features": {
                    "direct_score": one, "context_score": two, "score_mean": (one + two) / 2,
                    "score_disagreement": abs(one - two), "base_rank_percentile": features["base_rank_percentile"],
                    "candidate_count_log": features["candidate_count_log"],
                    "missing_metric_modality": features["missing_metric_modality"],
                    "missing_trace_modality": features["missing_trace_modality"], "trace_coverage": features["trace_coverage"],
                },
            })
    return result


def _groups(rankings, truth, field):
    values = defaultdict(dict)
    for incident in sorted(truth): values[str(truth[incident][field])][incident] = rankings[incident]
    return {
        group: ranking_metrics(items, {i: truth[i] for i in items})
        for group, items in sorted(values.items())
    }


def _macro(groups):
    names = ("ac_at_1", "ac_at_2", "ac_at_3", "ac_at_5", "ac_at_10", "mrr")
    return {name: float(np.mean([item[name] for item in groups.values()])) for name in names}


def _comparison(challenger, baseline, truth):
    return {
        metric: {
            "incident": paired_bootstrap(challenger, baseline, truth, metric, cluster=False),
            "cluster": paired_bootstrap(challenger, baseline, truth, metric, cluster=True),
        }
        for metric in ("ac_at_1", "ac_at_3", "ac_at_5", "mrr")
    }


def _subset(rankings, truth, predicate):
    ids = [incident for incident, item in truth.items() if predicate(item)]
    return {i: rankings[i] for i in ids}, {i: truth[i] for i in ids}


def _permutation(rows_by_id, truth, cases, columns, config, group_columns, name):
    indices = [columns.index(column) for column in group_columns if column in columns]
    if not indices: return None
    def transform(matrix, selected, _columns):
        output = matrix.copy()
        offset = 0
        randomizer = np.random.default_rng(SEED + sum(map(ord, name)))
        while offset < len(selected):
            incident = selected[offset]["incident_id"]
            end = offset
            while end < len(selected) and selected[end]["incident_id"] == incident: end += 1
            permutation = randomizer.permutation(end - offset)
            for column in indices: output[offset:end, column] = output[offset:end, column][permutation]
            offset = end
        return output
    changed, _ = fixed_oof(rows_by_id, truth, cases, columns, config, SEED, transform=transform)
    return changed


def _error_decomposition(rankings, truth, frozen):
    primary, diagnostics, examples = Counter(), Counter(), []
    for incident, item in sorted(truth.items()):
        rank = truth_rank(rankings[incident], item["root_service"])
        base_rank = truth_rank(frozen[incident], item["root_service"])
        if rank == 1: stage = "SUCCESS_AT_1"
        elif rank is not None and rank <= 3: stage = "WITHIN_TOP3_ORDERING_ERROR"
        elif rank is not None and rank <= 5: stage = "WITHIN_TOP5_ORDERING_ERROR"
        elif rank is not None and rank <= 10: stage = "ROOT_BELOW_TOP5"
        elif rank is not None: stage = "ROOT_BELOW_TOP10"
        else: stage = "CANDIDATE_UNIVERSE_MISS"
        primary[stage] += 1
        flags = []
        if base_rank and base_rank > 5: flags.append("PROPAGATED_VICTIM_PATTERN")
        if item["fault_family"] == "service_unavailable": flags.append("EXPECTED_SIGNAL_DISAPPEARANCE")
        if item["workload_regime"] == "mixed_low": flags.append("LOW_WORKLOAD_SIGNAL")
        for flag in flags: diagnostics[flag] += 1
        if rank != 1 and len(examples) < 25:
            examples.append({"incident_id": incident, "root_service": item["root_service"], "rank": rank, "frozen_m11_rank": base_rank, "diagnostic_flags": flags or ["OTHER"]})
    return {"primary": dict(primary), "overlapping_diagnostics": dict(diagnostics), "examples": examples}


def _render_docs(root: Path, evaluation: dict, baseline: dict, corpus: dict, freeze: dict):
    metrics = evaluation["pooled"]
    selected = evaluation["selected_architecture"]
    protocol_deviations = evaluation["protocol_deviations"]
    (root / "docs/m13-development-corpus.md").write_text(f"""# M13 Development Corpus

DeathStarBench Social Network at `{corpus['upstream_commit']}` is the sole
`NEW_DEVELOPMENT` system. The corpus contains {corpus['valid_incidents']} valid
incidents in {corpus['clusters']} repetition-isolated clusters: six roots × five
fault families × two workloads × two repetitions. Raw truth and telemetry are
kept separately under ignored `external-data/m13/`.

Healthy baseline: {baseline['healthy_metric_count']} metric records,
{baseline['healthy_trace_count']} canonical spans and {baseline['windows']}
ten-second workload-conditioned windows. Trace collection succeeded for
{evaluation['telemetry']['trace_incidents']}/{corpus['valid_incidents']} incidents.
""")
    (root / "docs/m13-trace-contract.md").write_text("""# M13 Trace Contract

The Jaeger adapter emits only trace/span IDs for reconstruction, parent ID,
service join key, peer join key, timestamps, duration, generic span kind, error
flag and observed service edge. Operation names, routes, service embeddings,
system identity, dataset identity, fault identity and root labels are forbidden
features. Exclusive duration subtracts the exact union of overlapping local
client-descendant waits. `traces_collected` is distinct from an expected service
or edge disappearing from a successfully collected window.
""")
    unavailable = evaluation["hypotheses"]["disappearance"]
    (root / "docs/m13-disappearance-evidence.md").write_text(f"""# M13 Disappearance Evidence

Verdict: **{evaluation['verdicts']['disappearance']}**.

The comparison is matched: full diagnostic evidence versus the identical
architecture without disappearance signals. On `service_unavailable`, AC@1
delta is {unavailable['service_unavailable']['ac_at_1']['cluster']['observed_delta']:.4f}
with cluster 95% CI `{unavailable['service_unavailable']['ac_at_1']['cluster']['ci95']}`.
Missing collection and expected-but-disappeared remain separate masks.
""")
    lines = ["# M13 Matched Ablations", "", "All variants use identical grouped folds and the fixed preregistered grid.", "", "| Variant | AC@1 | AC@3 | AC@5 | MRR |", "|---|---:|---:|---:|---:|"]
    for name, value in evaluation["ablations"].items():
        item = value["metrics"]
        lines.append(f"| {name} | {item['ac_at_1']:.4f} | {item['ac_at_3']:.4f} | {item['ac_at_5']:.4f} | {item['mrr']:.4f} |")
    (root / "docs/m13-ablation.md").write_text("\n".join(lines) + "\n")
    error_lines = [
        "# M13 Error Analysis", "", f"Selected architecture: **{selected}**.", "",
        "Primary stages use the full 120-incident denominator for every serious model.", "",
        "| Model | Success@1 | Within Top-3 | Within Top-5 | Below Top-5 | Below Top-10 | Universe miss |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    error_keys = (
        "SUCCESS_AT_1", "WITHIN_TOP3_ORDERING_ERROR", "WITHIN_TOP5_ORDERING_ERROR",
        "ROOT_BELOW_TOP5", "ROOT_BELOW_TOP10", "CANDIDATE_UNIVERSE_MISS",
    )
    for name, analysis in evaluation["error_analysis"].items():
        primary = analysis["primary"]
        error_lines.append(f"| {name} | " + " | ".join(str(primary.get(key, 0)) for key in error_keys) + " |")
    selected_diagnostics = evaluation["error_analysis"][selected]["overlapping_diagnostics"]
    error_lines.extend([
        "", f"Selected-model overlapping diagnostic hypotheses: `{json.dumps(selected_diagnostics, sort_keys=True)}`.", "",
        "These flags are descriptive error hypotheses, not causal ground-truth labels.",
        "The full machine-readable examples are in `ml/models/m13/evaluation.json`.", "",
    ])
    (root / "docs/m13-error-analysis.md").write_text("\n".join(error_lines))
    table = ["| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, value in metrics.items():
        table.append(f"| {name} | {value['ac_at_1']:.4f} | {value['ac_at_2']:.4f} | {value['ac_at_3']:.4f} | {value['ac_at_5']:.4f} | {value['ac_at_10']:.4f} | {value['mrr']:.4f} |")
    (root / "docs/m13-results.md").write_text(f"""# M13 Results

Development-only result on DeathStarBench Social Network; the reserved final
system was not deployed or scored.

{chr(10).join(table)}

Selected: **{selected}**. Research champion decision:
**{evaluation['verdicts']['architecture']}**.

Primary figures are repetition-isolated grouped OOF within the development
system. Complementary leave-one-root-out AC@1/MRR are
{evaluation['held_out_root']['metrics']['ac_at_1']:.4f}/
{evaluation['held_out_root']['metrics']['mrr']:.4f}; leave-one-fault-family-out
AC@1/MRR are {evaluation['held_out_fault']['metrics']['ac_at_1']:.4f}/
{evaluation['held_out_fault']['metrics']['mrr']:.4f}. These harder diagnostics
are not a substitute for the still-reserved final-system test.

- Trace incremental value: {evaluation['verdicts']['trace']}
- Disappearance evidence: {evaluation['verdicts']['disappearance']}
- Propagation evidence: {evaluation['verdicts']['propagation']}
- Learned vs metric heuristic: {evaluation['verdicts']['learned_vs_heuristic']}
- Full-candidate reranking: {evaluation['verdicts']['full_candidate']}
- GNN: {evaluation['verdicts']['gnn']}
- Reliability V3: {evaluation['verdicts']['reliability']}
- Protocol deviations: `{json.dumps(protocol_deviations)}`
""")
    claims = ["# M13 Claim Registry", ""]
    for claim in evaluation["claims"]:
        claims.extend([f"## {claim['CLAIM']}", "", *[f"- {key}: {value}" for key, value in claim.items()], ""])
    (root / "docs/m13-claim-registry.md").write_text("\n".join(claims))


def run(root: Path) -> dict:
    started = time.perf_counter()
    run_dir = root / "external-data/m13/runs/development-v1"
    healthy = json.loads((run_dir / "healthy/baseline.json").read_text())
    index = [json.loads(line) for line in (run_dir / "telemetry-index.jsonl").read_text().splitlines() if line]
    assert_selection_ids_allowed([item["incident_id"] for item in index])
    services = json.loads((root / "ml/models/m13/system-manifest.json").read_text())["candidate_services"]
    baseline = fit_healthy_baseline(healthy, services)
    (root / "ml/models/m13/healthy-baseline.json").write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    legacy_baseline = robust_baseline(healthy["metrics"])
    (root / "ml/models/m13/legacy-metric-baseline.json").write_text(json.dumps(legacy_baseline, indent=2, sort_keys=True) + "\n")
    expected_edges = baseline["expected_edges"]

    rows_by_id, rankings = {}, {name: {} for name in ("chance", "metric_heuristic", "frozen_m11")}
    trace_incidents = 0
    total_spans = 0
    for item in index:
        path = run_dir / item["telemetry_path"]
        if sha256_file(path) != item["sha256"]: raise RuntimeError("M13 telemetry seal mismatch")
        payload = json.loads(path.read_text())
        incident = item["incident_id"]
        clean = {key: value for key, value in payload.items() if key != "incident_id"}
        rows = build_candidate_rows(clean, baseline, services)
        legacy_rows = canonical_features(payload["metrics"], legacy_baseline, services, expected_edges)
        frozen = rank_candidates(incident, legacy_rows, root)["m11_top5"]
        _base_rank_features(rows, frozen)
        for row in rows: row["incident_id"] = incident
        rows_by_id[incident] = rows
        rankings["chance"][incident] = deterministic_chance(incident, services)
        rankings["metric_heuristic"][incident] = rank_scores({row["service"]: row["features"]["metric_max_shift"] for row in rows})
        rankings["frozen_m11"][incident] = frozen
        trace_incidents += int(payload["traces_collected"] and bool(payload["traces"]))
        total_spans += len(payload["traces"])

    # Ground truth is joined only after all identity-free features and baseline rankings exist.
    truth_items = [json.loads(line) for line in (run_dir / "truth.jsonl").read_text().splitlines() if line]
    truth = {item["incident_id"]: {**item, "system": "DeathStarBench-SocialNetwork"} for item in truth_items if item["valid_injection"]}
    if set(truth) != set(rows_by_id): raise RuntimeError("M13 full denominator mismatch")
    cases = [truth[incident] for incident in sorted(truth)]
    for incident, rows in rows_by_id.items():
        for row in rows: row["target"] = int(row["service"] == truth[incident]["root_service"])

    selected_config, search = select_config(rows_by_id, truth, cases, ABLATIONS["full_with_ranking_context"])
    ablation_predictions, ablations = {}, {}
    for name, columns in ABLATIONS.items():
        predicted, provenance = fixed_oof(rows_by_id, truth, cases, columns, selected_config)
        ablation_predictions[name] = predicted
        ablations[name] = {"features": list(columns), "metrics": ranking_metrics(predicted, truth), "folds": provenance}

    fusion, fusion_provenance = _fusion_oof(rows_by_id, truth, cases, selected_config)
    full = ablation_predictions["full_with_ranking_context"]
    full_top5 = _rerank_top_k(rankings["frozen_m11"], full, 5)
    fusion_top5 = _rerank_top_k(rankings["frozen_m11"], fusion, 5)
    rankings.update({"extended_full_top5": full_top5, "two_expert_fusion_top5": fusion_top5})
    baseline_metrics = ranking_metrics(rankings["frozen_m11"], truth)
    full_justified = baseline_metrics["ac_at_5"] < .95
    full_comparison = _comparison(full, full_top5, truth)
    full_promoted = full_justified and (
        full_comparison["ac_at_1"]["cluster"]["supported_positive"]
        or full_comparison["mrr"]["cluster"]["supported_positive"]
    ) and ranking_metrics(full, truth)["ac_at_3"] >= ranking_metrics(full_top5, truth)["ac_at_3"] - .01
    if full_promoted: rankings["full_candidate_challenger"] = full

    serious = ["extended_full_top5", "two_expert_fusion_top5"] + (["full_candidate_challenger"] if full_promoted else [])
    selected_name = max(serious, key=lambda name: (ranking_metrics(rankings[name], truth)["mrr"], ranking_metrics(rankings[name], truth)["ac_at_1"], name))
    selected = rankings[selected_name]

    pooled = {name: ranking_metrics(value, truth) for name, value in rankings.items()}
    comparisons = {name: _comparison(selected, rankings[name], truth) for name in ("chance", "metric_heuristic", "frozen_m11")}
    per_fault = {name: _groups(value, truth, "fault_family") for name, value in rankings.items()}
    per_root = {name: _groups(value, truth, "root_service") for name, value in rankings.items()}

    trace_comp = _comparison(ablation_predictions["metrics_traces_propagation"], ablation_predictions["metrics_only"], truth)
    prop_comp = _comparison(ablation_predictions["metrics_traces_propagation"], ablation_predictions["metrics_traces"], truth)
    disappeared_comp = _comparison(ablation_predictions["full_without_ranking_context"], ablation_predictions["metrics_traces_propagation"], truth)
    ranking_context_comp = _comparison(ablation_predictions["full_with_ranking_context"], ablation_predictions["full_without_ranking_context"], truth)
    unav_full, unav_truth = _subset(ablation_predictions["full_without_ranking_context"], truth, lambda item: item["fault_family"] == "service_unavailable")
    unav_without, _ = _subset(ablation_predictions["metrics_traces_propagation"], truth, lambda item: item["fault_family"] == "service_unavailable")
    unav_comp = _comparison(unav_full, unav_without, unav_truth)

    trace_supported = trace_comp["ac_at_1"]["cluster"]["supported_positive"] or trace_comp["mrr"]["cluster"]["supported_positive"]
    prop_supported = prop_comp["ac_at_1"]["cluster"]["supported_positive"] or prop_comp["mrr"]["cluster"]["supported_positive"]
    disappearance_supported = unav_comp["ac_at_1"]["cluster"]["supported_positive"] or unav_comp["mrr"]["cluster"]["supported_positive"]
    trace_verdict = "SUPPORTED" if trace_supported else "PARTIALLY_SUPPORTED" if trace_comp["mrr"]["incident"]["supported_positive"] else "NOT_SUPPORTED"
    prop_verdict = "SUPPORTED" if prop_supported else "PARTIALLY_SUPPORTED" if prop_comp["mrr"]["incident"]["supported_positive"] else "NOT_SUPPORTED"
    disappearance_verdict = "SUPPORTED" if disappearance_supported else "PARTIALLY_SUPPORTED" if unav_comp["mrr"]["incident"]["supported_positive"] else "NOT_SUPPORTED"

    seed_robustness, model_files = {}, {}
    model_dir = root / "ml/models/m13"
    for seed in SEEDS:
        seed_oof, _ = fixed_oof(rows_by_id, truth, cases, ABLATIONS["full_with_ranking_context"], selected_config, seed)
        seed_robustness[str(seed)] = ranking_metrics(seed_oof, truth)
        model = _fit(rows_by_id, sorted(truth), ABLATIONS["full_with_ranking_context"], selected_config, seed)
        path = model_dir / f"diagnostic-ranker-seed-{seed}.json"
        model.save_model(path)
        model_files[path.name] = sha256_file(path)

    permutation = {}
    groups = {
        "metrics": DIRECT_FEATURES, "traces": TRACE_FEATURES, "propagation": PROPAGATION_FEATURES,
        "disappearance": DISAPPEARANCE_FEATURES, "coverage": COVERAGE_FEATURES, "ranking_context": RANKING_FEATURES,
    }
    original_metrics = ranking_metrics(full, truth)
    for name, columns in groups.items():
        changed = _permutation(rows_by_id, truth, cases, ABLATIONS["full_with_ranking_context"], selected_config, columns, name)
        current = ranking_metrics(changed, truth)
        permutation[name] = {"ac_at_1_drop": original_metrics["ac_at_1"] - current["ac_at_1"], "mrr_drop": original_metrics["mrr"] - current["mrr"]}

    root_holdout_assignments = {item["incident_id"]: item["root_service"] for item in cases}
    fault_holdout_assignments = {item["incident_id"]: item["fault_family"] for item in cases}
    root_holdout, root_provenance = fixed_oof(rows_by_id, truth, cases, ABLATIONS["full_with_ranking_context"], selected_config, assignments=root_holdout_assignments)
    fault_holdout, fault_provenance = fixed_oof(rows_by_id, truth, cases, ABLATIONS["full_with_ranking_context"], selected_config, assignments=fault_holdout_assignments)

    selected_fault = per_fault[selected_name]
    heuristic_fault = per_fault["metric_heuristic"]
    frozen_fault = per_fault["frozen_m11"]
    selected_root = per_root[selected_name]
    network_faults = ("network_latency", "packet_loss")
    net_selected, net_truth = _subset(selected, truth, lambda item: item["fault_family"] in network_faults)
    net_frozen, _ = _subset(rankings["frozen_m11"], truth, lambda item: item["fault_family"] in network_faults)
    chance_ok = comparisons["chance"]["ac_at_1"]["cluster"]["supported_positive"] or comparisons["chance"]["mrr"]["cluster"]["supported_positive"]
    heuristic_ok = comparisons["metric_heuristic"]["ac_at_1"]["cluster"]["supported_positive"] or comparisons["metric_heuristic"]["mrr"]["cluster"]["supported_positive"]
    m11_ok = comparisons["frozen_m11"]["ac_at_1"]["cluster"]["supported_positive"] or comparisons["frozen_m11"]["mrr"]["cluster"]["supported_positive"]
    ac3_ok = pooled[selected_name]["ac_at_3"] >= pooled["frozen_m11"]["ac_at_3"] - .01
    ac5_ok = pooled[selected_name]["ac_at_5"] >= pooled["frozen_m11"]["ac_at_5"] - .01
    family_ok = all(selected_fault[name]["ac_at_1"] >= frozen_fault[name]["ac_at_1"] - .05 for name in selected_fault)
    unavailable_ok = selected_fault["service_unavailable"]["ac_at_1"] > frozen_fault["service_unavailable"]["ac_at_1"]
    network_ok = ranking_metrics(net_selected, net_truth)["mrr"] >= ranking_metrics(net_frozen, net_truth)["mrr"]
    coverage_ok = pooled[selected_name]["candidate_universe_coverage"] >= pooled["frozen_m11"]["candidate_universe_coverage"]
    promotion = all((coverage_ok, chance_ok, heuristic_ok, m11_ok, ac3_ok, ac5_ok, family_ok, unavailable_ok, network_ok))

    promotion_gates = {
        "candidate_coverage_not_decreased": coverage_ok, "beats_chance_cluster_supported": chance_ok,
        "beats_metric_heuristic_cluster_supported": heuristic_ok, "beats_frozen_m11_cluster_supported": m11_ok,
        "ac_at_3_preserved": ac3_ok, "ac_at_5_preserved": ac5_ok,
        "no_fault_family_ac_at_1_loss_over_0_05": family_ok,
        "service_unavailable_ac_at_1_materially_improved": unavailable_ok,
        "network_combined_mrr_not_regressed": network_ok,
    }
    gnn = "NOT_JUSTIFIED"  # no GNN unless trace is supported and residual propagation is demonstrably limiting
    architecture = "PROMOTE_M13_RESEARCH_CHAMPION" if promotion else "KEEP_M11_RESEARCH_CHAMPION"
    protocol_deviations = list(healthy.get("protocol_deviations", []))
    claims = []
    def claim(name, status, baseline_name, result, limitation):
        claims.append({
            "CLAIM": name, "HYPOTHESIS": name, "STATUS": status,
            "DATASET": "DeathStarBench Social Network", "DATA ROLE": "NEW_DEVELOPMENT",
            "PROTOCOL": "grouped OOF; repetitions kept in clusters", "DENOMINATOR": len(truth),
            "BASELINE": baseline_name, "METRIC": "AC@1 or MRR", "RESULT": json.dumps(result, sort_keys=True),
            "INCIDENT CI": json.dumps(result.get("mrr", {}).get("incident", {}).get("ci95")),
            "CLUSTER CI": json.dumps(result.get("mrr", {}).get("cluster", {}).get("ci95")), "LIMITATION": limitation,
        })
    claim("learned model vs metric heuristic", "SUPPORTED" if heuristic_ok else "REJECTED", "metric heuristic", comparisons["metric_heuristic"], "single development system")
    claim("traces incremental value", trace_verdict, "metrics only", trace_comp, "trace and propagation enter together in primary contrast")
    claim("disappearance evidence", disappearance_verdict, "same model without disappearance", unav_comp, "service-unavailable subset")
    claim("propagation evidence", prop_verdict, "metrics plus traces", prop_comp, "handcrafted topology features")
    claim("Top-5/full-candidate recovery", "SUPPORTED" if full_promoted else "NOT_JUSTIFIED", "frozen M11 Top-5 membership", full_comparison, "development-only conditional gate")
    claim("cross-fault robustness", "SUPPORTED" if family_ok and unavailable_ok and network_ok else "REJECTED", "frozen M11 per-fault performance", comparisons["frozen_m11"], "five fault families on one development system")
    claim("GNN escalation", "NOT_JUSTIFIED", "strongest non-GNN challenger", {}, "residual errors do not establish propagation as the remaining bottleneck")

    evaluation = {
        "version": "m13-evaluation-v1", "selected_architecture": selected_name,
        "selected_hyperparameters": selected_config, "hyperparameter_search": search,
        "pooled": pooled, "paired_selected_vs": comparisons,
        "per_fault": per_fault, "macro_fault": {name: _macro(value) for name, value in per_fault.items()},
        "per_root": per_root, "macro_root": {name: _macro(value) for name, value in per_root.items()},
        "worst_groups": {
            "fault_ac_at_1": min(selected_fault.items(), key=lambda item: item[1]["ac_at_1"]),
            "root_ac_at_1": min(selected_root.items(), key=lambda item: item[1]["ac_at_1"]),
        },
        "ablations": ablations,
        "hypotheses": {
            "trace": trace_comp, "propagation": prop_comp,
            "disappearance": {"all": disappeared_comp, "service_unavailable": unav_comp},
            "full_candidate": full_comparison,
            "ranking_context": ranking_context_comp,
        },
        "feature_group_permutation": permutation,
        "five_seed_robustness": seed_robustness,
        "fusion_provenance": fusion_provenance,
        "held_out_root": {"metrics": ranking_metrics(root_holdout, truth), "folds": root_provenance, "per_root": _groups(root_holdout, truth, "root_service")},
        "held_out_fault": {"metrics": ranking_metrics(fault_holdout, truth), "folds": fault_provenance, "per_fault": _groups(fault_holdout, truth, "fault_family")},
        "telemetry": {"trace_incidents": trace_incidents, "total_incidents": len(truth), "canonical_spans": total_spans, "trace_incident_coverage": trace_incidents / len(truth)},
        "error_analysis": {
            name: _error_decomposition(rankings[name], truth, rankings["frozen_m11"])
            for name in ("frozen_m11", *serious)
        },
        "promotion_gates": promotion_gates,
        "verdicts": {
            "trace": trace_verdict, "disappearance": disappearance_verdict, "propagation": prop_verdict,
            "learned_vs_heuristic": "SUPPORTED" if heuristic_ok else "NOT_SUPPORTED",
            "full_candidate": "PROMOTED" if full_promoted else "NOT_JUSTIFIED",
            "gnn": gnn, "reliability": "NOT_RUN", "architecture": architecture,
        },
        "claims": claims, "protocol_deviations": protocol_deviations,
        "environment": {"python": platform.python_version(), "xgboost": xgb.__version__, "wall_seconds": time.perf_counter() - started},
        "data_isolation": {"m12_incidents_used": 0, "reserved_final_incidents_used": 0, "reserved_final_scored": False},
    }
    evaluation_path = model_dir / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation, indent=2, sort_keys=True) + "\n")

    corpus = {
        **json.loads((model_dir / "corpus-manifest.json").read_text()),
        "status": "COLLECTED_AND_VALIDATED", "valid_incidents": len(truth),
        "clusters": len({cluster_key(item) for item in truth.values()}),
        "upstream_commit": "6ecb09706140f8730b5385c08f1386c654c3c526",
        "truth_sha256": sha256_file(run_dir / "truth.jsonl"),
        "telemetry_index_sha256": sha256_file(run_dir / "telemetry-index.jsonl"),
    }
    (model_dir / "corpus-manifest.json").write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n")
    freeze = {
        "version": "m13-freeze-v1", "development_only": True, "selected_architecture": selected_name,
        "research_champion_decision": architecture, "feature_schema": list(ABLATIONS["full_with_ranking_context"]),
        "trace_adapter": "m13_trace-v1", "metric_adapter": "workload-conditioned Huber residual v1",
        "disappearance_formula": "0.45 activity drop + 0.35 missing expected outgoing edge + 0.20 expected trace disappearance",
        "top_k_behavior": "full candidate" if full_promoted else "preserve frozen M11 Top-5 membership",
        "fusion_structure": "nested grouped OOF two-expert challenger evaluated; selected architecture recorded above",
        "hyperparameters": selected_config, "seeds": list(SEEDS), "models": model_files,
        "artifact_sha256": {
            "trace_adapter": sha256_file(root / "ml/rca_ml/m13_trace.py"),
            "feature_adapter": sha256_file(root / "ml/rca_ml/m13_features.py"),
            "protocol": sha256_file(root / "docs/m13-protocol.md"),
            "trace_schema": sha256_file(root / "ml/models/m13/trace-schema.json"),
            "workload": sha256_file(root / "scripts/m13/workload.py"),
        },
        "reserved_final_test_consumed": False,
    }
    freeze_path = model_dir / "freeze-manifest.json"
    freeze_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n")
    _render_docs(root, evaluation, baseline, corpus, freeze)

    integrity_files = sorted({
        str(path.relative_to(root))
        for pattern in ("deploy/m13/**/*", "scripts/m13/*", "docs/m13-*", "ml/rca_ml/m13_*", "ml/models/m13/*")
        for path in root.glob(pattern)
        if path.is_file() and path.name != "integrity-manifest.json" and "__pycache__" not in path.parts
    })
    integrity = {"version": "m13-integrity-v1", "sha256": {name: sha256_file(root / name) for name in integrity_files}}
    (model_dir / "integrity-manifest.json").write_text(json.dumps(integrity, indent=2, sort_keys=True) + "\n")
    return evaluation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    result = run(Path(args.root).resolve())
    print(json.dumps({"selected_architecture": result["selected_architecture"], "verdicts": result["verdicts"], "pooled": result["pooled"]}, indent=2, sort_keys=True))


if __name__ == "__main__": main()
