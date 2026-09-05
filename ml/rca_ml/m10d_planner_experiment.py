"""Bounded cross-system evaluation for the M10D-C active diagnostic planner."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import platform
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import xgboost as xgb

from .dataset import read_jsonl, sha256_file
from .m10c_experiment import EXTERNAL, RE1, extended_metrics, load_rows
from .m10c_schema import FEATURE_COLUMNS_M10C
from .m10d_planner import (
    ACTION_NAMES, BASE_COSTS, COST_SCHEMES, METRIC_ACTIONS, POLICY_FEATURES,
    VisibleState, build_visible_state, choose_expected_utility,
    deterministic_random_action, full_evidence_columns_covered,
    gap_prediction_set, gap_quantile, policy_vector,
    realized_utility, source_action_availability, transition,
    visible_feature_mask,
)
from .metrics import paired_bootstrap
from .train import save_json

SEED = 20260906
SEEDS = tuple(range(SEED, SEED + 5))
BUDGETS = (0, 1, 2, 3, 5, "full")
ALPHA = .20
COST_WEIGHT = .02
MODEL_PARAMETERS = {
    "objective": "reg:squarederror", "eval_metric": "rmse", "tree_method": "hist",
    "max_depth": 2, "eta": .08, "min_child_weight": 5, "subsample": .9,
    "colsample_bytree": .9, "lambda": 5, "nthread": 4,
}
MODEL_ROUNDS = 32
BASELINES = (
    "RANDOM", "FIXED_ORDER", "METRICS_FIRST", "TRACE_FIRST",
    "STRONGEST_CURRENT_SIGNAL", "ALL_EVIDENCE_IMMEDIATELY",
)
DEPLOYABLE = "MYOPIC_VOI"
ORACLE = "ORACLE_ACTION"


class LazyRankings:
    def __init__(self, cache: "RankingCache", scores: np.ndarray):
        self.cache = cache
        self.scores = scores

    def __getitem__(self, incident: str) -> list[dict]:
        start, end = self.cache.slices[incident]
        ranking = [
            {"service": self.cache.services[index], "score": float(self.scores[index]),
             "label": self.cache.labels[index]}
            for index in range(start, end)
        ]
        ranking.sort(key=lambda item: (-item["score"], item["service"]))
        for rank, item in enumerate(ranking, 1):
            item["rank"] = rank
        return ranking


class RankingCache:
    """Caches ranker outputs; labels stay here and never enter VisibleState."""

    def __init__(self, model: xgb.Booster, rows: list[dict], incident_ids: Sequence[str],
                 columns: Sequence[str]):
        self.model = model
        self.incident_ids = list(incident_ids)
        self.columns = tuple(columns)
        wanted = set(incident_ids)
        selected = sorted((row for row in rows if row["incident_id"] in wanted),
                          key=lambda row: (row["incident_id"], row["service"]))
        self.matrix = np.asarray([[float(row[name]) for name in self.columns]
                                  for row in selected], dtype=np.float32)
        self.services = [row["service"] for row in selected]
        self.labels = [int(row["label"]) for row in selected]
        self.slices = {}
        for index, row in enumerate(selected):
            incident = row["incident_id"]
            if incident not in self.slices:
                self.slices[incident] = [index, index + 1]
            else:
                self.slices[incident][1] = index + 1
        if set(self.slices) != wanted:
            raise ValueError("ranking cache is missing incidents")
        self.values: dict[frozenset[str], LazyRankings] = {}
        self.inference_seconds = 0.0

    def rankings(self, revealed: Sequence[str]) -> LazyRankings:
        key = frozenset(revealed)
        if key not in self.values:
            started = time.perf_counter()
            matrix = self.matrix * visible_feature_mask(key, self.columns)
            scores = self.model.inplace_predict(matrix)
            self.values[key] = LazyRankings(self, scores)
            self.inference_seconds += time.perf_counter() - started
        return self.values[key]


def subsets(actions: Sequence[str]):
    for size in range(len(actions) + 1):
        yield from itertools.combinations(actions, size)


def truth_rank(ranking: Sequence[dict]) -> int:
    return next(int(item["rank"]) for item in ranking if int(item["label"]) == 1)


def fit_model(examples: list[tuple[np.ndarray, float]], seed: int) -> xgb.Booster:
    matrix = np.asarray([item[0] for item in examples], dtype=np.float32)
    target = np.asarray([item[1] for item in examples], dtype=np.float32)
    data = xgb.DMatrix(matrix, label=target, feature_names=list(POLICY_FEATURES))
    return xgb.train({**MODEL_PARAMETERS, "seed": seed}, data,
                     num_boost_round=MODEL_ROUNDS, verbose_eval=False)


class CompiledBooster:
    """Small, exact tree evaluator without per-action native-call overhead."""

    def __init__(self, model: xgb.Booster):
        payload = json.loads(bytes(model.save_raw(raw_format="json")))
        learner = payload["learner"]
        raw_base = learner["learner_model_param"]["base_score"].strip("[]")
        self.base_score = float(raw_base)
        self.trees = []
        for tree in learner["gradient_booster"]["model"]["trees"]:
            self.trees.append({
                "left": tree["left_children"], "right": tree["right_children"],
                "split": tree["split_indices"], "condition": tree["split_conditions"],
                "default_left": tree["default_left"],
            })

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        matrix = np.asarray(matrix, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        result = np.empty(len(matrix), dtype=np.float64)
        for row_index, row in enumerate(matrix):
            score = self.base_score
            for tree in self.trees:
                node = 0
                while tree["left"][node] != -1:
                    value = float(row[tree["split"][node]])
                    go_left = (tree["default_left"][node] if math.isnan(value)
                               else value < tree["condition"][node])
                    node = tree["left"][node] if go_left else tree["right"][node]
                score += tree["condition"][node]
            result[row_index] = score
        return result


def model_predictor(models: Sequence[xgb.Booster]) -> Callable[[np.ndarray], np.ndarray]:
    compiled = [CompiledBooster(model) for model in models]
    def predict(matrix: np.ndarray) -> np.ndarray:
        return np.mean(np.stack([model.predict(matrix) for model in compiled]), axis=0)
    return predict


def make_examples(train_ids: Sequence[str], cache: RankingCache,
                  availability: Mapping[str, tuple[str, ...]], quantile: float) -> list[tuple[np.ndarray, float]]:
    examples = []
    # RE1 has at most five metric actions. Enumerating all subsets is bounded and
    # avoids training the policy only on trajectories generated by itself.
    for incident in train_ids:
        actions = availability[incident]
        for revealed in subsets(actions):
            before = cache.rankings(revealed)[incident]
            state = build_visible_state(incident, before, actions, revealed,
                                        sum(BASE_COSTS[action] for action in revealed), quantile)
            for action in actions:
                if action in revealed:
                    continue
                after_revealed = tuple(set(revealed) | {action})
                after = cache.rankings(after_revealed)[incident]
                set_before = state.prediction_set_size
                set_after = len(gap_prediction_set(after, quantile))
                target = realized_utility(before, after, set_before, set_after,
                                          BASE_COSTS[action], alpha=ALPHA,
                                          cost_weight=COST_WEIGHT)
                examples.append((policy_vector(state, action), target))
    return examples


def _ordered(policy: str) -> tuple[str, ...]:
    if policy == "FIXED_ORDER":
        return ACTION_NAMES
    if policy == "METRICS_FIRST":
        return METRIC_ACTIONS + ("GET_TOPOLOGY", "GET_TRACE_EVIDENCE",
                                 "GET_DEPENDENCY_EVIDENCE")
    if policy == "TRACE_FIRST":
        return ("GET_TRACE_EVIDENCE", "GET_TOPOLOGY", "GET_DEPENDENCY_EVIDENCE") + METRIC_ACTIONS
    return ACTION_NAMES


def choose_baseline(policy: str, state: VisibleState, affordable: Sequence[str],
                    *, seed: int) -> str:
    if policy == "RANDOM":
        return deterministic_random_action(state.incident_id, state.revealed_actions,
                                           affordable, seed)
    if policy in {"FIXED_ORDER", "METRICS_FIRST", "TRACE_FIRST"}:
        return next(action for action in _ordered(policy) if action in affordable)
    if policy == "STRONGEST_CURRENT_SIGNAL":
        # No hidden family values are inspected. Strong current concentration
        # triggers a trace/topology confirmation; otherwise acquire the next
        # canonical metric family.
        if state.ranking_concentration > .10:
            for action in ("GET_TRACE_EVIDENCE", "GET_TOPOLOGY",
                           "GET_DEPENDENCY_EVIDENCE"):
                if action in affordable:
                    return action
        return next(action for action in ACTION_NAMES if action in affordable)
    raise ValueError(policy)


def run_policy(incident: str, policy: str, budget: float | str,
               cache: RankingCache, availability: Mapping[str, tuple[str, ...]],
               quantile: float, predictor: Callable[[np.ndarray], float] | None,
               costs: Mapping[str, int], *, seed: int = SEED) -> dict:
    actions = availability[incident]
    limit = float(sum(costs[action] for action in actions)) if budget == "full" else float(budget)
    if policy == "ALL_EVIDENCE_IMMEDIATELY":
        revealed = actions if sum(costs[action] for action in actions) <= limit else ()
        spent = float(sum(costs[action] for action in revealed))
    else:
        revealed: tuple[str, ...] = ()
        spent = 0.0
    first_top1 = None
    first_top3 = None
    first_set_le = {3: None, 2: None, 1: None}
    selected_actions = []
    action_time = 0.0
    while True:
        ranking = cache.rankings(revealed)[incident]
        rank = truth_rank(ranking)
        if rank == 1 and first_top1 is None:
            first_top1 = spent
        if rank <= 3 and first_top3 is None:
            first_top3 = spent
        state = build_visible_state(incident, ranking, actions, revealed, spent, quantile)
        for size in first_set_le:
            if state.prediction_set_size <= size and first_set_le[size] is None:
                first_set_le[size] = spent
        if policy == "ALL_EVIDENCE_IMMEDIATELY" or state.prediction_set_size == 1:
            break
        affordable = [action for action in actions if action not in revealed
                      and spent + costs[action] <= limit + 1e-12]
        if not affordable:
            break
        started = time.perf_counter()
        if policy == DEPLOYABLE:
            if predictor is None:
                raise ValueError("deployable planner requires a truth-free predictor")
            action, _ = choose_expected_utility(state, affordable, predictor, costs)
        elif policy == ORACLE:
            utilities = []
            for candidate in affordable:
                after = cache.rankings(tuple(set(revealed) | {candidate}))[incident]
                utility = realized_utility(
                    ranking, after, state.prediction_set_size,
                    len(gap_prediction_set(after, quantile)), costs[candidate],
                    alpha=ALPHA, cost_weight=COST_WEIGHT)
                utilities.append((utility, candidate))
            _, action = max(utilities, key=lambda item: (item[0], item[1]))
        else:
            action = choose_baseline(policy, state, affordable, seed=seed)
        action_time += time.perf_counter() - started
        assert action is not None
        revealed, spent = transition(state, action, costs, limit)
        selected_actions.append(action)
    final = cache.rankings(revealed)[incident]
    final_state = build_visible_state(incident, final, actions, revealed, spent, quantile)
    rank = truth_rank(final)
    selected_set = gap_prediction_set(final, quantile)
    root = next(item["service"] for item in final if int(item["label"]) == 1)
    return {
        "incident_id": incident, "truth_rank": rank, "spent_cost": spent,
        "set_size": final_state.prediction_set_size, "set_covered": root in selected_set,
        "actions": selected_actions, "first_correct_top1_cost": first_top1,
        "first_root_top3_cost": first_top3, "action_selection_seconds": action_time,
        "first_set_le_3_cost": first_set_le[3], "first_set_le_2_cost": first_set_le[2],
        "first_set_le_1_cost": first_set_le[1],
    }


def summarize(outcomes: Sequence[dict]) -> dict:
    ranks = [int(item["truth_rank"]) for item in outcomes]
    metrics = extended_metrics({str(index): [{"rank": rank, "label": 1,
                                              "service": "root", "score": 0.0}]
                                for index, rank in enumerate(ranks)})
    top1_costs = [float(item["first_correct_top1_cost"]) for item in outcomes
                  if item["first_correct_top1_cost"] is not None]
    top3_costs = [float(item["first_root_top3_cost"]) for item in outcomes
                  if item["first_root_top3_cost"] is not None]
    set_costs = {
        size: [float(item[f"first_set_le_{size}_cost"]) for item in outcomes
               if item[f"first_set_le_{size}_cost"] is not None]
        for size in (3, 2, 1)
    }
    return {
        **metrics,
        "mean_set_size": float(np.mean([item["set_size"] for item in outcomes])),
        "empirical_set_coverage": float(np.mean([item["set_covered"] for item in outcomes])),
        "mean_spent_cost": float(np.mean([item["spent_cost"] for item in outcomes])),
        "mean_cost_to_correct_top1": float(np.mean(top1_costs)) if top1_costs else None,
        "mean_cost_to_root_in_top3": float(np.mean(top3_costs)) if top3_costs else None,
        "fraction_correct_top1": len(top1_costs) / len(outcomes),
        "fraction_root_in_top3": len(top3_costs) / len(outcomes),
        **{f"mean_cost_to_set_le_{size}": (float(np.mean(values)) if values else None)
           for size, values in set_costs.items()},
        **{f"fraction_set_le_{size}": len(values) / len(outcomes)
           for size, values in set_costs.items()},
        "action_selection_ms_per_incident": 1000 * sum(item["action_selection_seconds"] for item in outcomes) / len(outcomes),
    }


def curve_summary(by_budget: Mapping[str, Sequence[dict]]) -> dict:
    points = []
    for budget in BUDGETS:
        key = str(budget)
        value = summarize(by_budget[key])
        points.append({"budget": key, "cost": value["mean_spent_cost"],
                       "ac_at_1": value["ac_at_1"], "mrr": value["mrr"],
                       "mean_set_size": value["mean_set_size"]})
    unique = {}
    for point in points:
        unique[point["cost"]] = point
    ordered = [unique[cost] for cost in sorted(unique)]
    x = np.asarray([item["cost"] for item in ordered], dtype=float)
    scale = float(x[-1]) if len(x) and x[-1] else 1.0
    def area(field: str) -> float:
        y = np.asarray([item[field] for item in ordered], dtype=float)
        return float(np.trapezoid(y, x=x) / scale) if len(x) > 1 else float(y[0])
    return {"points": points, "auc_accuracy_cost": area("ac_at_1"),
            "auc_mrr_cost": area("mrr"), "auc_set_size_cost": area("mean_set_size")}


def evaluate_set(incident_ids: Sequence[str], policies: Sequence[str],
                 cache: RankingCache, availability: Mapping[str, tuple[str, ...]],
                 quantile: float, predictor: Callable[[np.ndarray], float] | None,
                 costs: Mapping[str, int] = BASE_COSTS, *, seed: int = SEED) -> dict:
    result = {policy: {str(budget): [] for budget in BUDGETS} for policy in policies}
    for policy in policies:
        for budget in BUDGETS:
            result[policy][str(budget)] = [
                run_policy(incident, policy, budget, cache, availability, quantile,
                           predictor if policy == DEPLOYABLE else None, costs, seed=seed)
                for incident in incident_ids
            ]
    return result


def grouped_summary(outcomes: Sequence[dict], case_meta: Mapping[str, dict], field: str) -> dict:
    values = {}
    groups = sorted({case_meta[item["incident_id"]][field] for item in outcomes})
    for group in groups:
        selected = [item for item in outcomes if case_meta[item["incident_id"]][field] == group]
        values[group] = summarize(selected)
    return values


def seed_robustness(seed_outcomes: Mapping[int, Mapping[str, Sequence[dict]]]) -> dict:
    result = {}
    for budget in (1, 2, 3, 5, "full"):
        values = [summarize(seed_outcomes[seed][str(budget)]) for seed in SEEDS]
        result[str(budget)] = {}
        for metric in ("ac_at_1", "mrr", "mean_set_size", "mean_spent_cost"):
            samples = [value[metric] for value in values]
            result[str(budget)][metric] = {
                "mean": float(np.mean(samples)), "std": float(np.std(samples)),
                "min": float(np.min(samples)), "max": float(np.max(samples)),
            }
    return result


def action_counts(outcomes: Sequence[dict]) -> dict[str, int]:
    return dict(Counter(action for item in outcomes for action in item["actions"]))


def rankings_invariant(cache: RankingCache, availability: Mapping[str, tuple[str, ...]]) -> dict:
    original = cache.rankings(ACTION_NAMES)
    failures = []
    max_score_delta = 0.0
    # Per-incident available-action masks must also reconstruct the original.
    for incident, actions in availability.items():
        actual = cache.rankings(actions)[incident]
        expected = original[incident]
        if [item["service"] for item in actual] != [item["service"] for item in expected]:
            failures.append(incident)
        expected_scores = {item["service"]: float(item["score"]) for item in expected}
        max_score_delta = max(max_score_delta, max(
            abs(float(item["score"]) - expected_scores[item["service"]]) for item in actual))
    return {"identical_ranks": not failures, "mismatched_incidents": failures,
            "max_abs_score_delta": max_score_delta,
            "columns_all_assigned": full_evidence_columns_covered(cache.columns)}


def _sha_payload(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _find_truth_free(root: Path) -> Path:
    direct = root / "artifacts/m10c/m10c-v2/truth-free.jsonl"
    linked = root / "artifacts/artifacts/m10c/m10c-v2/truth-free.jsonl"
    for path in (direct, linked):
        if path.exists():
            return path
    raise FileNotFoundError("M10C truth-free input not found; pass --truth-free")


def run(root: Path, model_dir: Path, truth_free: Path | None = None) -> dict:
    started = time.monotonic()
    truth_free = truth_free or _find_truth_free(root)
    seal = truth_free.with_name("truth-free-seal.json")
    cases, rows, ids = load_rows(truth_free, seal, root / "external-data/rcaeval/cases.parquet")
    records = read_jsonl(truth_free)
    availability = {record["external_case_id"]: source_action_availability(record)
                    for record in records}
    case_meta = {case["incident_id"]: case for case in cases}
    all_ids = sum((ids[name] for name in RE1 + EXTERNAL), [])
    columns = tuple(json.loads((root / "ml/models/m10c-v2/feature-schema.json").read_text())["selected_columns"])
    ranker = xgb.Booster(); ranker.load_model(root / "ml/models/m10c-v2/m10c-core-v2.json")
    cache = RankingCache(ranker, rows, all_ids, columns)
    full_rankings = cache.rankings(ACTION_NAMES)
    invariance = rankings_invariant(cache, availability)
    if not all(invariance[key] for key in ("identical_ranks", "columns_all_assigned")):
        raise ValueError(f"full-evidence invariance failed: {invariance}")

    development: dict[str, dict[str, list[dict]]] = {
        policy: {str(budget): [] for budget in BUDGETS}
        for policy in (DEPLOYABLE,) + BASELINES + (ORACLE,)
    }
    dev_seed_outcomes = {seed: {str(budget): [] for budget in BUDGETS} for seed in SEEDS}
    dev_sensitivity = {scheme: {str(budget): [] for budget in BUDGETS}
                       for scheme in ("uniform", "trace_expensive")}
    fold_report = {}
    for held_out in RE1:
        train_ids = sum((ids[name] for name in RE1 if name != held_out), [])
        held_out_ids = ids[held_out]
        calibration = {incident: full_rankings[incident] for incident in train_ids}
        quantile = gap_quantile(calibration, .9)
        examples = make_examples(train_ids, cache, availability, quantile)
        models = [fit_model(examples, seed) for seed in SEEDS]
        ensemble = model_predictor(models)
        fold_values = evaluate_set(
            held_out_ids, (DEPLOYABLE,) + BASELINES + (ORACLE,), cache,
            availability, quantile, ensemble)
        for policy, by_budget in fold_values.items():
            for budget, values in by_budget.items():
                development[policy][budget].extend(values)
        for seed, model in zip(SEEDS, models, strict=True):
            values = evaluate_set(held_out_ids, (DEPLOYABLE,), cache, availability,
                                  quantile, model_predictor((model,)))[DEPLOYABLE]
            for budget, outcomes in values.items():
                dev_seed_outcomes[seed][budget].extend(outcomes)
        for scheme in dev_sensitivity:
            values = evaluate_set(held_out_ids, (DEPLOYABLE,), cache, availability,
                                  quantile, ensemble, COST_SCHEMES[scheme])[DEPLOYABLE]
            for budget, outcomes in values.items():
                dev_sensitivity[scheme][budget].extend(outcomes)
        fold_report[held_out] = {
            "train_systems": [name for name in RE1 if name != held_out],
            "train_incidents": len(train_ids), "held_out_incidents": len(held_out_ids),
            "offline_examples": len(examples), "prediction_set_quantile": quantile,
            "planner": {budget: summarize(values) for budget, values in fold_values[DEPLOYABLE].items()},
        }

    dev_summary = {
        policy: {budget: summarize(values) for budget, values in by_budget.items()}
        for policy, by_budget in development.items()
    }
    dev_curves = {policy: curve_summary(values) for policy, values in development.items()}
    dev_full_metrics = extended_metrics({incident: full_rankings[incident]
                                         for incident in sum((ids[name] for name in RE1), [])})
    dev_full_mean_cost = float(np.mean([
        sum(BASE_COSTS[action] for action in availability[incident])
        for incident in sum((ids[name] for name in RE1), [])]))
    comparisons = {}
    positive_budgets = []
    for budget in (1, 2, 3, 5):
        key = str(budget)
        best = max(BASELINES, key=lambda policy: (dev_summary[policy][key]["mrr"], policy))
        learned = development[DEPLOYABLE][key]
        baseline = development[best][key]
        learned_by_id = {item["incident_id"]: item for item in learned}
        baseline_by_id = {item["incident_id"]: item for item in baseline}
        ordered = sorted(learned_by_id)
        paired = paired_bootstrap(
            [learned_by_id[item]["truth_rank"] for item in ordered],
            [baseline_by_id[item]["truth_rank"] for item in ordered],
            resamples=10000, seed=SEED)
        comparisons[key] = {"best_non_oracle_baseline": best, "paired": paired}
        if paired["mrr"]["ci_low"] > 0:
            positive_budgets.append(key)
    verdict = "PROMOTED" if len(positive_budgets) >= 2 and invariance["identical_ranks"] else "REJECTED"

    # Freeze configuration and the final RE1-only models before touching external outcomes.
    all_re1 = sum((ids[name] for name in RE1), [])
    final_quantile = gap_quantile({incident: full_rankings[incident] for incident in all_re1}, .9)
    final_examples = make_examples(all_re1, cache, availability, final_quantile)
    model_dir.mkdir(parents=True, exist_ok=True)
    final_models = []
    for seed in SEEDS:
        model = fit_model(final_examples, seed)
        path = model_dir / f"planner-seed-{seed}.json"
        model.save_model(path); final_models.append(model)
    config = {
        "version": "m10d-planner-v1", "seeds": list(SEEDS), "model": MODEL_PARAMETERS,
        "rounds": MODEL_ROUNDS, "alpha": ALPHA, "cost_weight": COST_WEIGHT,
        "actions": list(ACTION_NAMES), "cost_schemes": COST_SCHEMES,
        "budgets": list(BUDGETS), "policy_features": list(POLICY_FEATURES),
        "training_data": "RE1 only", "external_selection": False,
    }
    save_json(model_dir / "action-schema.json", config)
    freeze = {
        "frozen_before_external": True, "configuration_sha256": _sha_payload(config),
        "base_commit": "b18c70c4deddb86c637a5fad4c9f68a2ff465423",
        "m10c_ranker_sha256": sha256_file(root / "ml/models/m10c-v2/m10c-core-v2.json"),
        "truth_free_sha256": sha256_file(truth_free),
        "models": {f"planner-seed-{seed}.json": sha256_file(model_dir / f"planner-seed-{seed}.json")
                   for seed in SEEDS},
    }
    save_json(model_dir / "freeze-manifest.json", freeze)

    # Locked post-M10C external evaluation. Nothing below can alter verdict.
    external_ids = sum((ids[name] for name in EXTERNAL), [])
    external = evaluate_set(
        external_ids, (DEPLOYABLE,) + BASELINES + (ORACLE,), cache, availability,
        final_quantile, model_predictor(final_models))
    external_summary = {
        policy: {budget: summarize(values) for budget, values in by_budget.items()}
        for policy, by_budget in external.items()
    }
    external_grouped = {
        dataset: {budget: summarize([
            item for item in external[DEPLOYABLE][budget]
            if case_meta[item["incident_id"]]["dataset"] == dataset])
                  for budget in map(str, BUDGETS)}
        for dataset in EXTERNAL
    }
    sensitivity = {}
    for scheme in ("uniform", "trace_expensive"):
        outcomes = evaluate_set(external_ids, (DEPLOYABLE,), cache, availability,
                                final_quantile, model_predictor(final_models),
                                COST_SCHEMES[scheme])[DEPLOYABLE]
        sensitivity[scheme] = {budget: summarize(values) for budget, values in outcomes.items()}

    external_seed_outcomes = {}
    for seed, model in zip(SEEDS, final_models, strict=True):
        external_seed_outcomes[seed] = evaluate_set(
            external_ids, (DEPLOYABLE,), cache, availability, final_quantile,
            model_predictor((model,)))[DEPLOYABLE]

    budget3 = external[DEPLOYABLE]["3"]
    best_external_budget3 = max(BASELINES, key=lambda policy: external_summary[policy]["3"]["mrr"])
    baseline3 = {item["incident_id"]: item for item in external[best_external_budget3]["3"]}
    errors = Counter({name: 0 for name in (
        "domain_shift", "metric_ambiguity", "missing_modality", "candidate_ambiguity",
        "ranking_error", "confidence_error", "verifier_contradiction_miss",
        "planner_bad_action",
    )})
    full_map = {incident: truth_rank(full_rankings[incident]) for incident in external_ids}
    for item in budget3:
        if item["truth_rank"] == 1:
            continue
        incident = item["incident_id"]
        actions = availability[incident]
        if item["set_size"] == 1:
            errors["confidence_error"] += 1
        elif "GET_TRACE_EVIDENCE" not in actions:
            errors["missing_modality"] += 1
        elif full_map[incident] > 1:
            errors["ranking_error"] += 1
        elif item["truth_rank"] > baseline3[incident]["truth_rank"]:
            errors["planner_bad_action"] += 1
        elif full_map[incident] <= 3:
            errors["candidate_ambiguity"] += 1
        else:
            errors["metric_ambiguity"] += 1

    forced_external = {incident: full_rankings[incident] for incident in external_ids}
    frozen_metrics = extended_metrics(forced_external)
    total_model_bytes = sum((model_dir / f"planner-seed-{seed}.json").stat().st_size for seed in SEEDS)
    result = {
        "version": "m10d-planner-v1", "verdict": verdict,
        "promotion_rule": "positive paired-bootstrap MRR lower CI at >=2 non-full budgets plus full-evidence invariance",
        "promotion_positive_budgets": positive_budgets,
        "external_can_change_verdict": False,
        "data": {
            "development": "RE1 cross-system holdout",
            "synthetic_abc": {"applicable": False,
                "reason": "detector corpus has no service candidate/action evidence schema"},
            "external": "post-M10C locked evaluation; not pristine model selection",
        },
        "full_evidence_invariance": {**invariance, "external_metrics": frozen_metrics,
            "expected_m10c": {"ac_at_1": .7888888888888889,
                              "ac_at_3": .9416666666666667,
                              "mrr": .8690174062049062}},
        "development": {
            "folds": fold_report, "overall": dev_summary, "curves": dev_curves,
            "paired_vs_best_non_oracle": comparisons,
            "seed_robustness": seed_robustness(dev_seed_outcomes),
            "cost_sensitivity": {scheme: {budget: summarize(values)
                                           for budget, values in by_budget.items()}
                                 for scheme, by_budget in dev_sensitivity.items()},
            "by_system": grouped_summary(development[DEPLOYABLE]["3"], case_meta, "system"),
            "action_counts_budget_3": action_counts(development[DEPLOYABLE]["3"]),
            "strong_result": {
                "full_evidence_mrr": dev_full_metrics["mrr"],
                "target_95pct_full_mrr": .95 * dev_full_metrics["mrr"],
                "planner_budget_3_mrr": dev_summary[DEPLOYABLE]["3"]["mrr"],
                "mean_full_telemetry_cost": dev_full_mean_cost,
                "planner_budget_3_mean_cost": dev_summary[DEPLOYABLE]["3"]["mean_spent_cost"],
                "passes": (dev_summary[DEPLOYABLE]["3"]["mrr"] >= .95 * dev_full_metrics["mrr"]
                           and dev_summary[DEPLOYABLE]["3"]["mean_spent_cost"] <= .5 * dev_full_mean_cost),
            },
        },
        "external_360": {
            "summary": external_summary,
            "planner_curves": curve_summary(external[DEPLOYABLE]),
            "by_dataset": external_grouped,
            "by_system_budget_3": grouped_summary(external[DEPLOYABLE]["3"], case_meta, "system"),
            "action_counts_budget_3": action_counts(external[DEPLOYABLE]["3"]),
            "cost_sensitivity": sensitivity,
            "seed_robustness": seed_robustness(external_seed_outcomes),
            "oracle_isolated_upper_bound": {budget: external_summary[ORACLE][budget]
                                             for budget in map(str, BUDGETS)},
        },
        "error_taxonomy_budget_3": dict(errors),
        "performance": {
            "rank_cache_inference_seconds": cache.inference_seconds,
            "rank_cache_masks": len(cache.values),
            "planner_action_selection_ms_per_incident_budget_3": external_summary[DEPLOYABLE]["3"]["action_selection_ms_per_incident"],
            "serialized_models": len(final_models), "serialized_model_bytes": total_model_bytes,
            "policy_features": len(POLICY_FEATURES), "training_examples": len(final_examples),
        },
        "freeze": freeze,
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "xgboost": xgb.__version__, "bootstrap_seed": SEED,
                        "bootstrap_resamples": 10000, "runtime_seconds": time.monotonic() - started},
    }
    save_json(model_dir / "evaluation.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--models", type=Path, default=Path("ml/models/m10d-planner"))
    parser.add_argument("--truth-free", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    truth_free = args.truth_free.resolve() if args.truth_free else None
    result = run(root, (root / args.models).resolve(), truth_free)
    print(json.dumps({"verdict": result["verdict"],
                      "positive_budgets": result["promotion_positive_budgets"],
                      "runtime_seconds": result["environment"]["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
