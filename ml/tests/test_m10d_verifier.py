import unittest

from rca_ml.m10c_schema import FEATURE_COLUMNS_M10C
from rca_ml.m10d_verifier import (
    DEFAULT_STATUS_POLICY,
    assert_truth_free,
    build_evidence_profiles,
    fit_ood_stats,
    status_for,
)
from rca_ml.m10d_verifier_experiment import LEARNED_COLUMNS, _rerank


def row(service, **updates):
    value = {name: 0.0 for name in FEATURE_COLUMNS_M10C}
    value.update({"incident_id": "i", "service": service})
    value.update(updates)
    return value


def ranking(*services):
    return [
        {"service": service, "rank": position, "score": 1.0 / position}
        for position, service in enumerate(services, 1)
    ]


class M10DVerifierTests(unittest.TestCase):
    def test_truth_free_inference_rejects_labels_and_semantic_identity(self):
        with self.assertRaisesRegex(ValueError, "truth"):
            assert_truth_free([{"service": "payment", "label": 1}])
        with self.assertRaisesRegex(ValueError, "identity"):
            assert_truth_free([{"service": "payment", "system": "ob"}])

    def test_metric_support_uses_shift_persistence_and_percentile(self):
        rows = [
            row("payment", coverage_has_metrics=1, coverage_metric_family_ratio=.2,
                metric_cpu_has=1, metric_cpu_max_shift=20,
                metric_cpu_max_shift_percentile=1, metric_cpu_persistence=1),
            row("orders", coverage_has_metrics=1, coverage_metric_family_ratio=.2,
                metric_cpu_has=1, metric_cpu_max_shift=.1,
                metric_cpu_max_shift_percentile=0, metric_cpu_persistence=0),
        ]
        profiles = build_evidence_profiles(rows, ranking("payment", "orders"), top_k=2)
        self.assertGreater(
            profiles[0]["components"]["MetricSupport"],
            profiles[1]["components"]["MetricSupport"],
        )
        self.assertEqual(profiles[0]["dominant_metric_families"][0]["family"], "cpu")

    def test_exclusive_local_evidence_penalizes_propagated_wait(self):
        rows = [
            row("orders", coverage_has_traces=1, trace_trace_coverage=1,
                trace_local_evidence=.2, trace_median_exclusive_ratio=.05,
                trace_median_downstream_wait_ratio=.95),
            row("payment", coverage_has_traces=1, trace_trace_coverage=1,
                trace_local_evidence=.9, trace_median_exclusive_ratio=.9,
                trace_median_downstream_wait_ratio=.1),
        ]
        profiles = build_evidence_profiles(rows, ranking("orders", "payment"), top_k=2)
        self.assertLess(
            profiles[0]["components"]["TraceLocalSupport"],
            profiles[1]["components"]["TraceLocalSupport"],
        )
        self.assertGreater(profiles[0]["components"]["ContradictionEvidence"], .7)
        self.assertIn("waits downstream", " ".join(profiles[0]["contradictions"]))

    def test_propagation_graph_summary_and_contradiction(self):
        good = row(
            "payment", coverage_has_topology=1, topology_active_trace_coverage=1,
            trace_topology_precision=1, trace_topology_recall=1, trace_topology_f1=1,
            trace_expected_affected_ratio=.75, trace_observed_anomaly_ratio=.75,
        )
        bad = row(
            "orders", coverage_has_topology=1, topology_active_trace_coverage=1,
            trace_topology_precision=0, trace_topology_recall=0, trace_topology_f1=0,
            trace_expected_affected_ratio=.25, trace_observed_anomaly_ratio=.75,
        )
        profiles = build_evidence_profiles([good, bad], ranking("payment", "orders"), top_k=2)
        self.assertGreater(
            profiles[0]["components"]["PropagationSupport"],
            profiles[1]["components"]["PropagationSupport"],
        )
        self.assertEqual(profiles[0]["propagation_detail"]["weighted_graph_distance_proxy"], 0)
        self.assertGreater(profiles[1]["components"]["ContradictionEvidence"], .5)

    def test_missing_trace_keeps_metric_only_candidate(self):
        metric_only = row(
            "database", coverage_has_metrics=1, coverage_metric_family_ratio=1 / 13,
            metric_database_has=1, metric_database_max_shift=20,
            metric_database_max_shift_percentile=1, metric_database_persistence=1,
        )
        profile = build_evidence_profiles([metric_only], ranking("database"))[0]
        self.assertEqual(profile["components"]["TraceLocalSupport"], 0)
        self.assertGreater(profile["components"]["MetricSupport"], .8)
        self.assertEqual(profile["components"]["ExpertAgreement"], .5)
        self.assertNotEqual(profile["status"], "CONTRADICTED")

    def test_status_is_deterministic_and_insufficient_precedes_support(self):
        components = {name: 0.0 for name in (
            "MetricSupport", "TraceLocalSupport", "PropagationSupport", "TopologySupport",
            "DependencyWaitSupport", "CoverageSupport", "ContradictionEvidence",
            "OODPenalty", "ExpertAgreement",
        )}
        components.update({"CoverageSupport": .1, "MetricSupport": 1})
        first = status_for(components, .9, DEFAULT_STATUS_POLICY)
        second = status_for(components, .9, DEFAULT_STATUS_POLICY)
        self.assertEqual(first, second)
        self.assertEqual(first, "INSUFFICIENT_EVIDENCE")

    def test_ood_fit_is_scoped_to_supplied_development_ids(self):
        train = row("a", metric_cpu_max_shift=1)
        train["incident_id"] = "train"
        test = row("b", metric_cpu_max_shift=1000)
        test["incident_id"] = "test"
        stats = fit_ood_stats([train, test], ["train"])
        self.assertEqual(stats["metric_cpu_max_shift"]["high"], 1)

    def test_learned_verifier_schema_has_no_identity_or_truth(self):
        forbidden = {"service", "system", "dataset", "fault", "root", "label", "target"}
        self.assertFalse(set(LEARNED_COLUMNS) & forbidden)

    def test_reranking_is_deterministic_and_does_not_move_tail(self):
        source = {"i": [
            {"service": service, "rank": rank, "score": 5 - rank, "label": int(service == "b")}
            for rank, service in enumerate(("a", "b", "c", "d"), 1)
        ]}
        scores = {("i", "a"): .1, ("i", "b"): .9, ("i", "c"): .2}
        first = _rerank(source, scores)
        second = _rerank(source, scores)
        self.assertEqual(first, second)
        self.assertEqual([item["service"] for item in first["i"]], ["b", "c", "a", "d"])
        self.assertEqual(first["i"][-1]["rank"], 4)


if __name__ == "__main__":
    unittest.main()
