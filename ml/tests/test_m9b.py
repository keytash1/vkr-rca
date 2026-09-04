import math
import inspect
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from rca_ml.m9b_experiment import (
    METRIC_SYSTEM_HOLDOUTS,
    MULTISOURCE_FOLDS,
    baseline_evaluation,
    ids_by_dataset,
    join_labels,
    modality_subsets,
    rank_fusion,
    rank_scores,
)
from rca_ml.m9b_features import (
    _percentile_ranks,
    audit_metric_frame,
    channel_features,
    extract_case_features,
    is_infrastructure_entity,
    match_entity,
    parse_metric_column,
)
from rca_ml.m9b_model import incident_split
from rca_ml.m9b_schema import (
    FEATURE_COLUMNS_M9B,
    METRIC_MODEL_COLUMNS,
    TOPOLOGY_COLUMNS,
    TRACE_MODEL_COLUMNS,
    validate_schema,
)


def trace_snapshot():
    services = []
    for service in ("orders", "payment"):
        services.append({"service": service, "ready": True, "latency_z": 0.2,
                         "error_z": 0, "latency_strength": 0.1, "error_strength": 0,
                         "latency_anomalous": False, "error_anomalous": False,
                         "m5_severity": 0.1, "trace_coverage": 1,
                         "expected_affected_services": [], "median_exclusive_duration_ms": 2})
    return {"feature_schema_version": "m6-v1", "state": "no_anomaly",
            "ready_universe": ["orders", "payment"], "observed_anomalies": [],
            "services": services, "topology_edges": [{"caller": "orders", "callee": "payment"}],
            "active_topology_trace_coverage": 1, "primary_signal": "none",
            "topology_source": "active_traces"}


def metric_frame(inject=1000):
    times = np.arange(inject - 600, inject + 600, dtype=float)
    return pd.DataFrame({"time": times,
                         "orders_cpu": np.where(times < inject, 10.0, 20.0),
                         "orders_mem": np.where(times < inject, 20.0, 20.0),
                         "redis_cpu": np.where(times < inject, 1.0, 50.0)})


class M9BTests(unittest.TestCase):
    def test_strict_metric_parser(self):
        self.assertEqual(parse_metric_column("orders_latency-90"), ("orders", "latency_p90"))
        self.assertEqual(parse_metric_column("ts-order-service_diskio"), ("ts-order-service", "disk_io"))
        self.assertIsNone(parse_metric_column("orders_latency"))

    def test_entity_mapping_and_unmatched_database(self):
        self.assertEqual(match_entity("orders_service", ["orders", "payment"]), "orders")
        self.assertIsNone(match_entity("orders-mongo", ["orders"]))
        self.assertTrue(is_infrastructure_entity("redis"))

    def test_cadence_duplicate_nan_inf_audit(self):
        frame = pd.DataFrame({"time": [1, 2, 2, 4], "orders_cpu": [1, np.nan, np.inf, 4]})
        audit = audit_metric_frame(frame)
        self.assertEqual(audit["duplicate_timestamps"], 1)
        self.assertEqual(audit["nan_values"], 1)
        self.assertEqual(audit["inf_values"], 1)
        self.assertEqual(audit["cadence_seconds_median"], 1.5)

    def test_baseline_current_separation_and_robust_shift(self):
        frame = metric_frame()
        value = channel_features(frame.time, frame.orders_cpu, 1000)
        self.assertEqual(value["baseline_samples"], 600)
        self.assertEqual(value["current_samples"], 600)
        self.assertGreater(value["signed_location_z"], 0)
        self.assertEqual(value["persistence_fraction"], 1)
        self.assertEqual(value["max_exceedance_run_fraction"], 1)

    def test_fixed_time_rolling_and_timing_are_normalized(self):
        times = pd.Series(np.arange(400, 1600, dtype=float))
        values = pd.Series(np.r_[np.zeros(600), np.zeros(300), np.ones(300) * 10])
        value = channel_features(times, values, 1000)
        for seconds in (30, 60, 120):
            self.assertGreater(value[f"rolling_{seconds}_score"], 0)
            self.assertGreaterEqual(value[f"rolling_{seconds}_fraction"], 0)
            self.assertLessEqual(value[f"rolling_{seconds}_fraction"], 1)
        self.assertGreaterEqual(value["first_exceedance_fraction"], 0)
        self.assertLessEqual(value["peak_fraction"], 1)

    def test_masks_finite_and_no_hard_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "opaque.parquet"
            metric_frame().to_parquet(path)
            result = extract_case_features(path, 1000, trace_snapshot())
        self.assertEqual(result["candidate_services"], ["orders", "payment"])
        vectors = {value["service"]: value["vector"] for value in result["services"]}
        self.assertEqual(vectors["orders"]["metric_cpu_has"], 1)
        self.assertEqual(vectors["payment"]["metric_cpu_has"], 0)
        self.assertEqual(vectors["payment"]["has_trace"], 1)
        self.assertTrue(all(math.isfinite(number) for vector in vectors.values() for number in vector.values()))

    def test_path_rename_invariance(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "root-name.parquet"
            second = Path(temporary) / "opaque-renamed.parquet"
            metric_frame().to_parquet(first)
            metric_frame().to_parquet(second)
            self.assertEqual(extract_case_features(first, 1000, trace_snapshot()),
                             extract_case_features(second, 1000, trace_snapshot()))

    def test_relative_percentiles(self):
        self.assertEqual(_percentile_ranks([1, 3, 2]), [0, 1, .5])
        self.assertEqual(_percentile_ranks([2, 2]), [.5, .5])

    def test_label_join_requires_truth_free_seal(self):
        parameters = inspect.signature(extract_case_features).parameters
        self.assertFalse({"root", "fault", "case_id"} & set(parameters))
        with self.assertRaisesRegex(ValueError, "sealed"):
            join_labels([], pd.DataFrame(), {"sealed_before_label_join": False})

    def test_schema_whitelist_and_modalities(self):
        validate_schema()
        self.assertFalse(set(METRIC_MODEL_COLUMNS) & set(TRACE_MODEL_COLUMNS))
        self.assertFalse(set(METRIC_MODEL_COLUMNS) & set(TOPOLOGY_COLUMNS))
        self.assertTrue(set(TRACE_MODEL_COLUMNS) < set(FEATURE_COLUMNS_M9B))
        self.assertTrue(set(TOPOLOGY_COLUMNS) < set(FEATURE_COLUMNS_M9B))

    def test_re1_dataset_and_hash_split_isolation(self):
        cases = [{"dataset": dataset, "external_case_id": f"{dataset}-{number}", "triggered_eligible": True}
                 for dataset in ("RE1-OB", "RE1-SS", "RE1-TT", "RE2-OB") for number in range(10)]
        grouped = ids_by_dataset(cases)
        self.assertEqual(len(grouped["RE1-OB"]), 10)
        train, validation = incident_split(grouped["RE1-OB"] + grouped["RE1-SS"], "holdout")
        self.assertFalse(set(train) & set(validation))
        self.assertFalse(any("RE1-TT" in value for value in train + validation))
        for _, training, held_out in METRIC_SYSTEM_HOLDOUTS:
            self.assertNotIn(held_out, training)
            self.assertEqual(len(training), 2)

    def test_multisource_system_holdout_and_modality_ablation_contract(self):
        self.assertEqual({value[1] for value in MULTISOURCE_FOLDS}, {"RE2-OB", "RE2-TT"})
        for _, training, tests in MULTISOURCE_FOLDS:
            self.assertNotIn(training, tests)
            self.assertTrue(any(value.startswith("RE3-") for value in tests))
        self.assertEqual(set(modality_subsets()), {"metrics_only", "traces_only", "topology_only",
                                                   "metrics_traces", "metrics_topology",
                                                   "traces_topology", "all"})

    def test_rank_fusion_and_deterministic_ties(self):
        a = rank_scores([{"service": "a", "score": 2, "label": 1}, {"service": "b", "score": 1, "label": 0}])
        b = rank_scores([{"service": "a", "score": 0, "label": 1}, {"service": "b", "score": 2, "label": 0}])
        self.assertEqual([value["service"] for value in rank_fusion((a, b))], ["a", "b"])
        self.assertEqual(rank_fusion((a, b)), rank_fusion((a, b)))

    def test_baselines_rank_all_candidates(self):
        rows = []
        for service, label, metric in (("a", 1, 2), ("b", 0, 1)):
            row = {name: 0.0 for name in FEATURE_COLUMNS_M9B}
            row.update({"incident_id": "i", "service": service, "label": label,
                        "metric_max_shift_score": metric, "metric_top2_score": metric})
            rows.append(row)
        metrics, rankings = baseline_evaluation(rows, ["i"])
        self.assertEqual(metrics["metric_max_shift"]["ac_at_1"], 1)
        self.assertEqual(metrics["chance"]["ac_at_1"], .5)
        self.assertEqual(len(rankings["soft_trace_v1"]["i"]), 2)


if __name__ == "__main__":
    unittest.main()
