import json
import hashlib
import unittest
from pathlib import Path

from rca_ml.m13_features import FEATURES, build_candidate_rows, fit_healthy_baseline
from rca_ml.m13_experiment import FIXED, _rerank_top_k, fixed_oof
from rca_ml.m13_protocol import (
    assert_selection_ids_allowed,
    deterministic_chance,
    grouped_folds,
    paired_bootstrap,
    ranking_metrics,
)
from rca_ml.m13_trace import canonicalize_jaeger, exclusive_duration_us, union_duration

ROOT = Path(__file__).resolve().parents[2]


def span(span_id, service, start, duration, parent="", kind="SERVER"):
    return {
        "trace_id": "trace", "span_id": span_id, "parent_span_id": parent,
        "service": service, "peer_service": "", "start_time_us": start,
        "duration_us": duration, "span_kind": kind, "error": False,
        "observed_edge": {"source": "a", "target": service} if parent and service != "a" else None,
    }


class M13ProtocolTest(unittest.TestCase):
    def test_trace_adapter_deterministic_and_parent_edge(self):
        payload = {"data": [{
            "traceID": "t", "processes": {
                "p1": {"serviceName": "gateway"}, "p2": {"serviceName": "orders"},
            },
            "spans": [
                {"traceID": "t", "spanID": "2", "processID": "p2", "startTime": 2,
                 "duration": 4, "references": [{"refType": "CHILD_OF", "spanID": "1"}],
                 "tags": [{"key": "span.kind", "value": "server"}]},
                {"traceID": "t", "spanID": "1", "processID": "p1", "startTime": 1,
                 "duration": 8, "references": [], "tags": []},
            ],
        }]}
        one = canonicalize_jaeger(payload)
        two = canonicalize_jaeger(json.loads(json.dumps(payload)))
        self.assertEqual(one, two)
        child = next(item for item in one if item["span_id"] == "2")
        self.assertEqual({"source": "gateway", "target": "orders"}, child["observed_edge"])
        self.assertFalse(any("operation" in key for item in one for key in item))

    def test_exclusive_duration_and_overlapping_wait_union(self):
        server = span("s", "a", 0, 100)
        spans = [server, span("c1", "a", 10, 50, "s", "CLIENT"), span("c2", "a", 40, 40, "s", "CLIENT")]
        self.assertEqual(70, union_duration([(10, 60), (40, 80)]))
        self.assertEqual((30, 70), exclusive_duration_us(server, spans))

    def test_identity_is_rejected(self):
        baseline = {"expected_edges": [], "metric": {}, "trace": {}}
        for key in ("root_service", "fault_family", "system", "dataset", "label"):
            with self.assertRaises(ValueError):
                build_candidate_rows({
                    key: "secret", "requests_per_second": 1, "start_unix": 0,
                    "end_unix": 1, "metrics": [], "traces": [], "traces_collected": True,
                }, baseline, ["a"])

    def test_expected_disappearance_is_not_missing_collection(self):
        fit = {"intercept": 10.0, "slope": 0.0, "residual_median": 0.0, "residual_iqr": 1.0, "samples": 10}
        baseline = {
            "expected_edges": [{"source": "a", "target": "b", "presence": 1.0}],
            "metric": {name: {} for name in ("a", "b")},
            "trace": {name: {signal: fit for signal in (
                "span_rate", "request_rate", "error_rate", "latency_median_us", "latency_p90_us",
                "latency_p99_us", "exclusive_median_us", "downstream_wait_ratio",
            )} for name in ("a", "b")},
        }
        incident = {"requests_per_second": 1, "start_unix": 0, "end_unix": 1,
                    "metrics": [], "traces": [span("a", "a", 100_000, 1000)], "traces_collected": True}
        rows = {item["service"]: item["features"] for item in build_candidate_rows(incident, baseline, ["a", "b"])}
        self.assertEqual(1.0, rows["b"]["expected_but_disappeared_mask"])
        self.assertEqual(1.0, rows["b"]["trace_collected_mask"])
        self.assertEqual(1.0, rows["a"]["missing_expected_edge_ratio"])
        self.assertGreater(rows["b"]["last_seen_delta"], 0)
        incident["traces_collected"] = False
        missing = {item["service"]: item["features"] for item in build_candidate_rows(incident, baseline, ["a", "b"])}
        self.assertEqual(1.0, missing["b"]["missing_trace_modality"])
        self.assertEqual(0.0, missing["b"]["trace_collected_mask"])

    def test_healthy_only_workload_conditioning(self):
        metrics = []
        for second in range(20):
            rps = 6 if second < 10 else 18
            metrics.append({"timestamp": second, "service": "a", "family": "cpu", "value": rps * 2, "unit": "cores"})
        healthy = {
            "metrics": metrics, "traces": [],
            "segments": [
                {"start_unix": 0, "end_unix": 9, "requests_per_second": 6},
                {"start_unix": 10, "end_unix": 19, "requests_per_second": 18},
            ],
        }
        fitted = fit_healthy_baseline(healthy, ["a"])
        self.assertGreater(fitted["metric"]["a"]["cpu"]["slope"], 1.5)
        self.assertEqual("M13_HEALTHY_ENGINEERING", fitted["fit_role"])

    def test_cluster_split_keeps_repetitions_together(self):
        cases = [
            {"incident_id": f"i-{root}-{fault}-{rep}", "system": "s", "root_service": root,
             "fault_family": fault, "workload_regime": "low", "intensity": "x"}
            for root in ("a", "b", "c") for fault in ("cpu", "net") for rep in (1, 2)
        ]
        folds = grouped_folds(cases)
        for root in ("a", "b", "c"):
            for fault in ("cpu", "net"):
                self.assertEqual(folds[f"i-{root}-{fault}-1"], folds[f"i-{root}-{fault}-2"])
        self.assertEqual(set(c["incident_id"] for c in cases), set(folds))

    def test_full_denominator_heuristic_and_bootstrap(self):
        truth = {
            "i1": {"root_service": "a", "system": "s", "fault_family": "cpu", "workload_regime": "l", "intensity": "x"},
            "i2": {"root_service": "missing", "system": "s", "fault_family": "cpu", "workload_regime": "l", "intensity": "x"},
        }
        good = {"i1": deterministic_chance("same", ["a"]), "i2": deterministic_chance("same", ["a"])}
        self.assertEqual(good["i1"], deterministic_chance("same", ["a"]))
        self.assertEqual(.5, ranking_metrics(good, truth)["candidate_universe_coverage"])
        self.assertEqual(
            paired_bootstrap(good, good, truth, "mrr", cluster=True, resamples=100),
            paired_bootstrap(good, good, truth, "mrr", cluster=True, resamples=100),
        )

    def test_data_roles_and_feature_schema(self):
        ledger = json.loads((ROOT / "ml/models/m13/data-ledger.json").read_text())
        self.assertEqual("USED_TEST_READONLY", ledger["roles"]["M12-HotelReservation"])
        self.assertEqual("RESERVED_FINAL_TEST", ledger["roles"]["OpenTelemetry-AstronomyShop"])
        forbidden_identity_features = {"service", "service_name", "system", "system_name", "fault", "fault_family", "dataset", "root", "root_service"}
        self.assertFalse(forbidden_identity_features & set(FEATURES))
        with self.assertRaises(ValueError): assert_selection_ids_allowed(["m12-001"])
        with self.assertRaises(ValueError): assert_selection_ids_allowed(["astronomy-001"])

    def test_oof_provenance_and_candidate_universe(self):
        cases, rows, truth = [], {}, {}
        for index in range(10):
            incident = f"m13-test-{index}"
            root = "a" if index % 2 else "b"
            case = {"incident_id": incident, "system": "dev", "root_service": root,
                    "fault_family": f"fault-{index % 5}", "workload_regime": "low", "intensity": "fixed"}
            cases.append(case); truth[incident] = case
            rows[incident] = [
                {"incident_id": incident, "service": service, "target": int(service == root),
                 "features": {"signal": float(service == root)}}
                for service in ("a", "b", "c")
            ]
        predicted, provenance = fixed_oof(rows, truth, cases, ("signal",), FIXED)
        self.assertEqual(set(truth), set(predicted))
        self.assertTrue(all(not fold["expert_predictions_in_sample"] for fold in provenance))
        self.assertTrue(all({"a", "b", "c"} == {item["service"] for item in ranking} for ranking in predicted.values()))

    def test_top_k_projection_does_not_mutate_full_candidate_ranking(self):
        full = {"i": [{"service": name, "score": 4-index, "rank": index} for index, name in enumerate(("a", "b", "c", "d"), 1)]}
        snapshot = json.loads(json.dumps(full))
        base = {"i": [{"service": name, "score": 4-index, "rank": index} for index, name in enumerate(("d", "c", "b", "a"), 1)]}
        _rerank_top_k(base, full, 2)
        self.assertEqual(snapshot, full)

    def test_post_experiment_integrity_and_fusion_provenance(self):
        evaluation_path = ROOT / "ml/models/m13/evaluation.json"
        integrity_path = ROOT / "ml/models/m13/integrity-manifest.json"
        if not evaluation_path.exists() or not integrity_path.exists():
            self.skipTest("M13 experiment artifacts are generated after real corpus collection")
        evaluation = json.loads(evaluation_path.read_text())
        self.assertEqual(0, evaluation["data_isolation"]["m12_incidents_used"])
        self.assertFalse(evaluation["data_isolation"]["reserved_final_scored"])
        self.assertTrue(all(not fold["in_sample_expert_scores_used_for_fusion"] for fold in evaluation["fusion_provenance"]))
        self.assertEqual(5, len(evaluation["five_seed_robustness"]))
        from rca_ml.m13_runtime import M13Runtime
        runtime = M13Runtime(ROOT)
        self.assertEqual("ok", runtime.health()["status"])
        index = json.loads((ROOT / "external-data/m13/runs/development-v1/telemetry-index.jsonl").read_text().splitlines()[0])
        incident = json.loads((ROOT / "external-data/m13/runs/development-v1" / index["telemetry_path"]).read_text())
        first = runtime.analyze(incident)
        second = runtime.analyze(incident)
        self.assertEqual(first, second)
        self.assertEqual("DIAGNOSTIC_RANKING_ONLY", first["causal_status"])
        self.assertEqual(12, len(first["candidates"]))
        self.assertNotIn("probability", json.dumps(first).lower())
        integrity = json.loads(integrity_path.read_text())
        for relative, expected in integrity["sha256"].items():
            self.assertEqual(expected, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), relative)


if __name__ == "__main__":
    unittest.main()
