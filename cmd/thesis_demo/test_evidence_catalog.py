"""Evidence semantics, neutral LLM context and v1 compatibility."""
import copy
import unittest

from api_contract import document
from evidence_catalog import (EvidenceRegistry, MAX_SERIES_POINTS, assistant_context,
                              build_catalog, canonical_bytes)
from jsonschema import Draft202012Validator
from server import DiagnosticApplication


def fixture():
    services = ["alpha", "beta"]
    window = {"candidate_services": services, "start_unix": 100, "end_unix": 110,
        "requests_per_second": 5,
        "metrics": [{"service": "alpha", "family": "cpu", "timestamp": t,
                     "value": float(t - 100), "unit": "cores"} for t in range(100, 111)],
        "traces": [{"service": "alpha", "start_time_us": 101_000_000,
            "duration_us": 2000, "trace_id": "a" * 32, "span_id": "b" * 16,
            "error": True, "operation": "SECRET_FREEFORM", "tags": {"token": "SECRET_TOKEN"},
            "observed_edge": {"source": "beta", "target": "alpha"}}]}
    result = {"result_id": "12345678-1234-4234-8234-123456789012", "start_unix": 100,
        "end_unix": 110, "input_sha256": "a" * 64, "baseline_sha256": "b" * 64,
        "feature_schema_sha256": "c" * 64, "model_version": "example"}
    baseline = {"metric": {"alpha": {"cpu": {"samples": 10, "intercept": 1,
        "slope": .2, "residual_median": 0, "residual_iqr": 2}}}}
    return window, result, baseline


class CatalogSemanticsTests(unittest.TestCase):
    def build(self, **kwargs):
        return build_catalog(*fixture(), **kwargs)

    def test_exact_raw_values_and_workload_prediction(self):
        catalog = self.build()
        fact = next(f for f in catalog["observations"] if f["service"] == "alpha" and f["kind"] == "metric" and f["values"]["family"] == "cpu")
        values = fact["values"]
        self.assertEqual((values["samples"], values["min"], values["median"], values["max"]), (11, 0, 5, 10))
        self.assertEqual(values["baseline_comparison"]["expected_at_observed_load"], 2)
        self.assertEqual(values["baseline_comparison"]["absolute_residual_p90"], 3.5)
        self.assertEqual(values["baseline_comparison"]["load_comparability"], "NOT_ESTABLISHED")
        self.assertIsNone(values["baseline_comparison"]["healthy_start_unix"])
        self.assertEqual(sum(b["samples"] for b in values["series"]), 11)
        self.assertTrue(any(c["code"] == "CHECK_METRIC_DEVIATION" for c in catalog["checks"]))

    def test_missing_metric_is_not_zero_and_traces_not_causality(self):
        catalog = self.build(source_status={"traces": "unavailable"})
        metric = next(f for f in catalog["observations"] if f["service"] == "beta" and f["kind"] == "metric")
        self.assertEqual(metric["values"]["state"], "MISSING")
        self.assertIsNone(metric["values"]["median"])
        self.assertIsNone(metric["values"]["baseline_comparison"])
        traces = next(f for f in catalog["observations"] if f["service"] == "beta" and f["kind"] == "traces")
        self.assertEqual(traces["values"]["state"], "UNAVAILABLE")
        dependency = next(f for f in catalog["observations"] if f["kind"] == "dependencies")
        self.assertEqual(dependency["values"]["edges"], [{"source": "beta", "target": "alpha", "observed_edges": 1}])
        self.assertIn("NOT_CAUSAL", dependency["values"]["meaning"])

    def test_trace_overhang_is_not_counted_as_in_interval_evidence(self):
        window, result, baseline = fixture()
        window["traces"] += [window["traces"][0] | {"start_time_us": t} for t in (99_000_000, 111_000_000)]
        window["metrics"].append(window["metrics"][0] | {"timestamp": 111, "value": 1e9})
        catalog = build_catalog(window, result, baseline)
        summary = DiagnosticApplication._observation_summary(window, ("alpha", "beta"))
        traces = next(f for f in catalog["observations"] if f["service"] == "alpha" and f["kind"] == "traces")
        self.assertEqual(traces["values"]["observed_spans"], 1)
        self.assertEqual(summary["alpha"]["traces"]["count"], 1)
        self.assertEqual(summary["alpha"]["metrics"]["cpu"]["max"], 10)
        window["traces"] = []
        window["traces_collected"] = False
        replay = build_catalog(window, result, baseline)
        self.assertEqual(replay["source_quality"]["traces"], "unavailable")

    def test_freeform_tags_do_not_reach_catalog_or_llm(self):
        catalog = self.build()
        self.assertNotIn("SECRET", canonical_bytes(catalog).decode())
        self.assertNotIn("SECRET", canonical_bytes(assistant_context(catalog)).decode())
        self.assertTrue(all(c["status"] == "PROPOSED_NOT_EXECUTED" for c in catalog["checks"]))
        ids = {f["id"] for f in catalog["observations"]}
        self.assertTrue(all(set(c["evidence_ids"]) <= ids for c in catalog["checks"]))

    def test_dependency_outside_inventory_is_an_explicit_gap(self):
        window, result, baseline = fixture()
        window["traces"][0]["observed_edge"] = {"source": "external-db", "target": "alpha"}
        window["traces"].append(window["traces"][0] | {"service": "external-db",
            "observed_edge": {"source": "alpha", "target": "external-db"}})
        catalog = build_catalog(window, result, baseline)
        dependencies = next(f for f in catalog["observations"] if f["service"] == "alpha" and f["kind"] == "dependencies")
        self.assertEqual(dependencies["values"]["external_edge_observations"], 2)
        self.assertEqual(dependencies["values"]["edges"], [])
        self.assertTrue(any(check["code"] == "CHECK_CANDIDATE_INVENTORY" for check in catalog["checks"]))
        self.assertEqual(catalog["services"], ["alpha", "beta"])

    def test_blind_context_is_allowlisted_and_rank_order_independent(self):
        catalog = self.build()
        original = assistant_context(catalog)
        catalog.update({"model_score": "POISON", "incident_id": "POISON", "base_rank": "POISON"})
        catalog["services"].reverse()
        catalog["observations"].reverse()
        for fact in catalog["observations"]:
            fact["rank"] = "POISON"
            fact["values"]["future_ml_score"] = "POISON"
            if fact["kind"] == "metric":
                for bin in fact["values"]["series"]:
                    bin["future_base_rank"] = "POISON"
                if fact["values"]["baseline_comparison"]:
                    fact["values"]["baseline_comparison"]["score"] = "POISON"
            fact["source_links"] = [{"url": "https://example.invalid/POISON"}]
        self.assertEqual(original, assistant_context(catalog))
        self.assertNotIn("POISON", canonical_bytes(assistant_context(catalog)).decode())
        hint = [{"service": "beta", "rank": 1, "model_score": .8},
                {"service": "alpha", "rank": 2, "model_score": .2}]
        self.assertEqual(assistant_context(catalog, ranking=hint)["ranking_hint"], hint)
        with self.assertRaises(ValueError):
            assistant_context(catalog, ranking=hint[:1])

    def test_catalog_schema_and_stable_ids(self):
        catalog = self.build()
        Draft202012Validator({"$ref": "#/components/schemas/EvidenceCatalog", "components": document()["components"]}).validate(catalog)
        repeated = self.build()
        self.assertEqual(catalog, repeated)
        window, result, baseline = fixture()
        result["baseline_sha256"] = "f" * 64
        changed = build_catalog(window, result, baseline)
        self.assertNotEqual(catalog["observations"][0]["id"], changed["observations"][0]["id"])

    def test_binning_is_bounded_and_preserves_extremes_and_count(self):
        window, result, baseline = fixture()
        window["metrics"] = [{"service": "alpha", "family": "cpu", "timestamp": 100 + i / 2000,
            "value": float(i), "unit": "cores"} for i in range(10001)]
        catalog = build_catalog(window, result, baseline)
        metric = catalog["observations"][0]["values"]
        self.assertEqual(metric["max"], 10000)
        self.assertLessEqual(len(metric["series"]), MAX_SERIES_POINTS)
        self.assertEqual(sum(b["samples"] for b in metric["series"]), 10001)

    def test_registry_copy_expiry_and_budgets(self):
        clock = [0]
        store = EvidenceRegistry(max_entries=1, ttl_seconds=10, clock=lambda: clock[0])
        catalog = self.build()
        store.put(catalog)
        fetched = store.get(catalog["analysis_id"])
        fetched["services"].clear()
        self.assertEqual(store.get(catalog["analysis_id"])["services"], ["alpha", "beta"])
        second = copy.deepcopy(catalog); second["analysis_id"] = "second"
        store.put(second)
        self.assertIsNone(store.get(catalog["analysis_id"]))
        clock[0] = 10
        self.assertIsNone(store.get("second"))
        with self.assertRaises(ValueError):
            EvidenceRegistry(max_entry_bytes=1).put(catalog)



if __name__ == "__main__":
    unittest.main()
