from __future__ import annotations

import unittest

from rca_ml.m10c_schema import FEATURE_COLUMNS_M10C, FORBIDDEN_FEATURES
from rca_ml.m10d_planner import (
    ACTION_NAMES, BASE_COSTS, POLICY_FEATURES, VisibleState, build_visible_state,
    choose_expected_utility, full_evidence_columns_covered, gap_prediction_set,
    mask_rows, policy_vector, realized_utility, source_action_availability,
    transition,
)
from rca_ml.m10d_planner_experiment import ORACLE, run_policy


def _ranking(root_rank: int = 2):
    services = [
        {"service": "a", "score": 1.0, "rank": 1, "label": int(root_rank == 1)},
        {"service": "b", "score": .6, "rank": 2, "label": int(root_rank == 2)},
        {"service": "c", "score": .2, "rank": 3, "label": int(root_rank == 3)},
    ]
    return services


def _state(revealed=(), spent=0.0):
    return build_visible_state(
        "opaque-1", _ranking(), ("GET_CPU_METRICS", "GET_TRACE_EVIDENCE"),
        revealed, spent, .5)


class M10DPlannerTests(unittest.TestCase):
    def test_visible_state_cannot_carry_hidden_truth(self):
        state = _state()
        public = state.public_dict()
        self.assertFalse({"label", "root", "truth", "full_rows", "hidden"} & set(public))
        self.assertNotIn("b", str(policy_vector(state, "GET_CPU_METRICS").tolist()))

    def test_action_availability_uses_only_present_sources(self):
        record = {"features": {
            "source_families": ["cpu", "latency"],
            "candidates": [{"has_traces": True, "has_topology": False}],
        }}
        self.assertEqual(source_action_availability(record), (
            "GET_LATENCY_METRICS", "GET_CPU_METRICS", "GET_TRACE_EVIDENCE",
            "GET_DEPENDENCY_EVIDENCE",
        ))

    def test_action_costs_are_preregistered(self):
        self.assertEqual(BASE_COSTS["GET_CPU_METRICS"], 1)
        self.assertEqual(BASE_COSTS["GET_TOPOLOGY"], 1)
        self.assertEqual(BASE_COSTS["GET_TRACE_EVIDENCE"], 2)
        self.assertEqual(BASE_COSTS["GET_DEPENDENCY_EVIDENCE"], 2)

    def test_state_transition_respects_availability_and_budget(self):
        state = _state()
        revealed, spent = transition(state, "GET_CPU_METRICS", BASE_COSTS, 1)
        self.assertEqual(revealed, ("GET_CPU_METRICS",))
        self.assertEqual(spent, 1)
        with self.assertRaisesRegex(ValueError, "budget"):
            transition(_state(), "GET_TRACE_EVIDENCE", BASE_COSTS, 1)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            transition(_state(), "GET_MEMORY_METRICS", BASE_COSTS, 2)

    def test_masking_reveals_only_requested_evidence_and_full_is_exact(self):
        row = {"incident_id": "x", "service": "a", "label": 1,
               **{name: float(index + 1) for index, name in enumerate(FEATURE_COLUMNS_M10C)}}
        cpu = mask_rows([row], ("GET_CPU_METRICS",), FEATURE_COLUMNS_M10C)[0]
        self.assertEqual(cpu["metric_cpu_persistence"], row["metric_cpu_persistence"])
        self.assertEqual(cpu["metric_latency_persistence"], 0)
        self.assertEqual(cpu["coverage_has_metrics"], row["coverage_has_metrics"])
        full = mask_rows([row], ACTION_NAMES, FEATURE_COLUMNS_M10C)[0]
        self.assertTrue(all(full[name] == row[name] for name in FEATURE_COLUMNS_M10C))
        self.assertTrue(full_evidence_columns_covered(FEATURE_COLUMNS_M10C))

    def test_realized_utility_matches_formula(self):
        before = _ranking(root_rank=3)
        after = _ranking(root_rank=1)
        value = realized_utility(before, after, 3, 1, 2, alpha=.2, cost_weight=.02)
        self.assertAlmostEqual(value, (1 - 1 / 3) + .2 * 2 / 3 - .04)

    def test_expected_utility_policy_is_deterministic(self):
        state = _state()
        action, score = choose_expected_utility(
            state, ["GET_TRACE_EVIDENCE", "GET_CPU_METRICS"],
            lambda matrix: matrix[:, POLICY_FEATURES.index("action_get_cpu_metrics")],
        )
        self.assertEqual(action, "GET_CPU_METRICS")
        self.assertEqual(score, 1)

    def test_policy_schema_has_no_identity_or_label_features(self):
        lowered = {name.lower() for name in POLICY_FEATURES}
        self.assertFalse(lowered & FORBIDDEN_FEATURES)
        self.assertFalse(any(token in name for name in lowered
                             for token in ("service", "system", "dataset", "fault", "root", "label")))

    def test_prediction_set_uses_scores_not_truth(self):
        ranking = _ranking(root_rank=3)
        without_labels = [{**item, "label": 0} for item in ranking]
        self.assertEqual(gap_prediction_set(ranking, .5), gap_prediction_set(without_labels, .5))

    def test_oracle_is_not_a_serializable_policy_feature_or_action(self):
        self.assertNotIn(ORACLE, ACTION_NAMES)
        self.assertFalse(any("oracle" in name for name in POLICY_FEATURES))

    def test_visible_state_dataclass_fields_do_not_accept_hidden_rows(self):
        self.assertNotIn("full_rows", VisibleState.__dataclass_fields__)
        self.assertNotIn("truth", VisibleState.__dataclass_fields__)
        self.assertNotIn("label", VisibleState.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
