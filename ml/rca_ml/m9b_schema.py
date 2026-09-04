"""Versioned feature whitelist for M9B soft-evidence RCA."""

from __future__ import annotations

M9B_SCHEMA_VERSION = "m9b-v1"
METRIC_FAMILIES = (
    "cpu",
    "memory",
    "disk_io",
    "socket",
    "workload",
    "error",
    "latency_p50",
    "latency_p90",
)

METRIC_SUFFIXES = {
    "cpu": "cpu",
    "mem": "memory",
    "diskio": "disk_io",
    "socket": "socket",
    "workload": "workload",
    "error": "error",
    "latency-50": "latency_p50",
    "latency-90": "latency_p90",
}

FAMILY_FIELDS = (
    "has",
    "available_count",
    "baseline_samples",
    "current_samples",
    "max_shift",
    "top2_mean_shift",
    "max_persistence",
    "signed_location_z",
    "abs_location_z",
    "p90_shift_z",
    "iqr_shift_z",
    "max_run_fraction",
    "first_exceedance_fraction",
    "peak_fraction",
    "rolling_30_score",
    "rolling_30_median",
    "rolling_30_fraction",
    "rolling_60_score",
    "rolling_60_median",
    "rolling_60_fraction",
    "rolling_120_score",
    "rolling_120_median",
    "rolling_120_fraction",
)

METRIC_COLUMNS = tuple(f"metric_{family}_{field}" for family in METRIC_FAMILIES for field in FAMILY_FIELDS)
METRIC_GLOBAL_COLUMNS = (
    "metric_available_family_count",
    "metric_available_family_ratio",
    "metric_max_shift_score",
    "metric_top2_score",
)

# M7 numeric evidence is reused under an explicit namespace. Identity strings are
# never copied to the model vector.
TRACE_FIELDS = (
    "latency_z_log1p",
    "error_z_log1p",
    "latency_strength",
    "error_strength",
    "latency_anomalous",
    "error_anomalous",
    "m5_severity_log1p",
    "topology_precision",
    "topology_recall",
    "topology_f1",
    "local_evidence",
    "trace_coverage",
    "median_exclusive_ratio",
    "median_downstream_wait_ratio",
    "log1p_median_exclusive_duration_ms",
    "active_topology_trace_coverage",
    "is_observed_anomaly",
    "expected_affected_count",
    "expected_affected_ratio",
    "ready_universe_size",
    "observed_anomaly_count",
    "observed_anomaly_ratio",
    "primary_signal_latency",
    "primary_signal_error",
    "topology_source_active",
    "in_degree",
    "out_degree",
    "normalized_in_degree",
    "normalized_out_degree",
    "ancestor_count",
    "descendant_count",
    "ancestor_ratio",
    "descendant_ratio",
)
TRACE_COLUMNS = ("has_trace",) + tuple(f"trace_{name}" for name in TRACE_FIELDS)

PERCENTILE_BASE_COLUMNS = (
    "metric_max_shift_score",
    "metric_top2_score",
    *(f"metric_{family}_max_shift" for family in METRIC_FAMILIES),
    *(f"metric_{family}_max_persistence" for family in METRIC_FAMILIES),
    "trace_latency_z_log1p",
    "trace_error_z_log1p",
    "trace_m5_severity_log1p",
    "trace_topology_f1",
    "trace_local_evidence",
    "trace_trace_coverage",
    "trace_median_exclusive_ratio",
    "trace_median_downstream_wait_ratio",
    "trace_log1p_median_exclusive_duration_ms",
    "trace_normalized_in_degree",
    "trace_normalized_out_degree",
    "trace_ancestor_ratio",
    "trace_descendant_ratio",
)
PERCENTILE_COLUMNS = tuple(f"{name}_percentile" for name in PERCENTILE_BASE_COLUMNS)

FEATURE_COLUMNS_M9B = METRIC_COLUMNS + METRIC_GLOBAL_COLUMNS + TRACE_COLUMNS + PERCENTILE_COLUMNS
METRIC_MODEL_COLUMNS = tuple(
    name for name in FEATURE_COLUMNS_M9B
    if name.startswith("metric_") and not name.startswith("metric_trace_")
)

TOPOLOGY_TOKENS = (
    "topology_", "degree", "ancestor", "descendant", "expected_affected",
    "active_topology", "topology_source",
)
TOPOLOGY_COLUMNS = tuple(name for name in FEATURE_COLUMNS_M9B if any(token in name for token in TOPOLOGY_TOKENS))
TRACE_MODEL_COLUMNS = tuple(
    name for name in FEATURE_COLUMNS_M9B
    if name.startswith("trace_") and name not in TOPOLOGY_COLUMNS
)

FORBIDDEN_FEATURES = frozenset({
    "service", "system", "dataset", "case", "case_id", "incident_id", "root",
    "root_service", "fault", "fault_family", "path", "operation", "metric_entity",
    "metric_name", "ground_truth", "label",
})


def validate_schema() -> None:
    if len(FEATURE_COLUMNS_M9B) != len(set(FEATURE_COLUMNS_M9B)):
        raise ValueError("FEATURE_COLUMNS_M9B contains duplicates")
    leaked = set(FEATURE_COLUMNS_M9B) & FORBIDDEN_FEATURES
    if leaked:
        raise ValueError(f"forbidden M9B features: {sorted(leaked)}")
    if not set(METRIC_MODEL_COLUMNS) < set(FEATURE_COLUMNS_M9B):
        raise ValueError("metric feature subset is invalid")
