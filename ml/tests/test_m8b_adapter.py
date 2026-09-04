import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

from rca_ml.m8b_adapter import audit_schema, canonical_operation, run_adapter
from rca_ml.m8b_experiment import evaluate


class M8BAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temp.name) / "offline-rca"
        subprocess.run(["go", "build", "-o", cls.binary, "./cmd/offline-rca"], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_operation_canonicalization(self):
        self.assertEqual(canonical_operation(None, "GET /orders/123?full=1"), "GET /orders/{id}")
        self.assertEqual(
            canonical_operation("", "GET /objects/123e4567-e89b-12d3-a456-426614174000"),
            "GET /objects/{uuid}",
        )

    def test_schema_load_time_conversion_and_path_rename_invariance(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "truth-looking-name.parquet"
            second = Path(directory) / "renamed-opaque.parquet"
            self._write_fixture(first)
            second.write_bytes(first.read_bytes())
            self.assertEqual(audit_schema(first)["rows"], 270)
            left = run_adapter(first, external_case_id="opaque", inject_unix=1_700_000_000, mode="fault", binary=self.binary)
            right = run_adapter(second, external_case_id="opaque", inject_unix=1_700_000_000, mode="fault", binary=self.binary)
            self.assertEqual(left, right)
            self.assertEqual(left["features"]["feature_schema_version"], "m6-v1")
            self.assertNotIn("truth-looking-name", json.dumps(left))

    def test_healthy_windows_exclude_post_fault_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.parquet"
            self._write_fixture(path)
            result = run_adapter(path, external_case_id="healthy", inject_unix=1_700_000_000, mode="healthy", binary=self.binary)
            self.assertEqual(result["features"]["state"], "no_anomaly")

    def test_label_join_reports_root_not_observable_without_dropping_case(self):
        record = self._evaluation_record(services=[])
        label = pd.DataFrame([{
            "case": "opaque", "dataset": "RE2-OB", "suite": "RE2", "system": "OB",
            "fault": "cpu", "root_cause_service": "missing-service",
        }])
        result = evaluate([record], label, {"sealed_before_truth_join": True})
        self.assertEqual(result["coverage"]["evaluated"], 1)
        self.assertEqual(result["cases"][0]["status"], "root_not_observable")

    def test_insufficient_baseline_is_explicit(self):
        record = self._evaluation_record(services=[{"service": "root", "ready": True}])
        record["fault"]["features"]["state"] = "insufficient_current_data"
        record["fault"]["anomalies"] = {"operations": [{"state": "insufficient_baseline"}]}
        label = pd.DataFrame([{
            "case": "opaque", "dataset": "RE2-OB", "suite": "RE2", "system": "OB",
            "fault": "cpu", "root_cause_service": "root",
        }])
        result = evaluate([record], label, {"sealed_before_truth_join": True})
        self.assertEqual(result["cases"][0]["status"], "insufficient_baseline")

    @staticmethod
    def _evaluation_record(services):
        rankings = {name: [] for name in ("max_severity", "topology_consistency", "local_evidence", "hybrid_v1")}
        coverage = {"error_evidence_coverage": 0, "exclusive_trace_coverage": 0, "parent_match_rate": 0}
        return {
            "external_case_id": "opaque", "dataset": "RE2-OB",
            "fault": {"features": {"state": "no_anomaly", "services": services, "ready_universe": [],
                                    "observed_anomalies": []}, "anomalies": {"operations": []},
                      "rca": {"rankings": rankings}, "coverage": coverage},
            "healthy": {"features": {"state": "no_anomaly"}},
            "frozen_m7": {"ranking": []},
        }

    @staticmethod
    def _write_fixture(path: Path):
        rows = {name: [] for name in ("time", *(
            "traceID", "spanID", "serviceName", "methodName", "operationName", "parentSpanID"
        ), "startTimeMillis", "startTime", "duration", "statusCode")}
        index = 0
        for offset, duration in [(-500, 1_000), (-200, 1_000), (10, 700_000)]:
            for repeat in range(30):
                start = (1_700_000_000 + offset + repeat) * 1_000_000
                trace = f"t-{index}"
                values = [
                    (f"r-{index}", None, "entry", "GET /work", duration + 2_000),
                    (f"c-{index}", f"r-{index}", "entry", "GET leaf", duration + 1_000),
                    (f"s-{index}", f"c-{index}", "leaf", "GET /work", duration),
                ]
                for span, parent, service, operation, latency in values:
                    rows["time"].append("00:00")
                    rows["traceID"].append(trace)
                    rows["spanID"].append(span)
                    rows["serviceName"].append(service)
                    rows["methodName"].append(None)
                    rows["operationName"].append(operation)
                    rows["parentSpanID"].append(parent)
                    rows["startTimeMillis"].append(start // 1_000)
                    rows["startTime"].append(start)
                    rows["duration"].append(latency)
                    rows["statusCode"].append(0)
                index += 1
        pq.write_table(pa.table(rows), path)


if __name__ == "__main__":
    unittest.main()
