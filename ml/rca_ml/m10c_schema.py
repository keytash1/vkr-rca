"""Canonical telemetry vocabulary and compact M10C candidate schema."""

from __future__ import annotations

M10C_SCHEMA_VERSION = "m10c-v2-candidate"

METRIC_FAMILIES = (
    "traffic_rate",
    "error_rate",
    "latency",
    "cpu",
    "memory",
    "disk",
    "network",
    "saturation",
    "dependency",
    "runtime",
    "database",
    "cache",
    "queue",
)

# Source-specific spellings belong here, outside the ranking core. Longest
# suffix wins, allowing an adapter to add aliases without changing the model.
RCAEVAL_SUFFIXES = {
    "load": "traffic_rate",
    "workload": "traffic_rate",
    "error": "error_rate",
    "latency": "latency",
    "latency-50": "latency",
    "latency-90": "latency",
    "cpu": "cpu",
    "mem": "memory",
    "memory": "memory",
    "diskio": "disk",
    "disk": "disk",
    "socket": "network",
    "network": "network",
}

FAMILY_FIELDS = ("has", "max_shift", "persistence")
METRIC_COLUMNS = tuple(
    f"metric_{family}_{field}" for family in METRIC_FAMILIES for field in FAMILY_FIELDS
)
METRIC_PERCENTILE_COLUMNS = tuple(
    f"metric_{family}_max_shift_percentile" for family in METRIC_FAMILIES
)
METRIC_GLOBAL_COLUMNS = (
    "metric_available_family_count",
    "metric_available_family_ratio",
    "metric_max_shift_score",
    "metric_top2_score",
)
WORKLOAD_RESIDUAL_COLUMNS = (
    "workload_residual_location",
    "workload_residual_p90",
    "workload_residual_persistence",
    "workload_residual_peak",
)
TRACE_COLUMNS = (
    "trace_latency_z_log1p",
    "trace_error_z_log1p",
    "trace_latency_strength",
    "trace_error_strength",
    "trace_m5_severity_log1p",
    "trace_local_evidence",
    "trace_trace_coverage",
    "trace_median_exclusive_ratio",
    "trace_median_downstream_wait_ratio",
    "trace_log1p_median_exclusive_duration_ms",
    "trace_latency_anomalous",
    "trace_error_anomalous",
)
TRACE_PERCENTILE_COLUMNS = (
    "trace_latency_z_log1p_percentile",
    "trace_error_z_log1p_percentile",
    "trace_median_exclusive_ratio_percentile",
    "trace_median_downstream_wait_ratio_percentile",
)
TOPOLOGY_COLUMNS = (
    "topology_in_degree",
    "topology_out_degree",
    "topology_normalized_in_degree",
    "topology_normalized_out_degree",
    "topology_ancestor_ratio",
    "topology_descendant_ratio",
    "topology_active_trace_coverage",
)
COVERAGE_COLUMNS = (
    "coverage_has_metrics",
    "coverage_has_traces",
    "coverage_has_topology",
    "coverage_metric_family_ratio",
    "coverage_trace_fraction",
    "coverage_candidate_metric_ratio",
    "coverage_candidate_trace_ratio",
)

FEATURE_COLUMNS_M10C = (
    METRIC_COLUMNS
    + METRIC_PERCENTILE_COLUMNS
    + METRIC_GLOBAL_COLUMNS
    + WORKLOAD_RESIDUAL_COLUMNS
    + TRACE_COLUMNS
    + TRACE_PERCENTILE_COLUMNS
    + TOPOLOGY_COLUMNS
    + COVERAGE_COLUMNS
)

METRIC_EXPERT_COLUMNS = tuple(
    name for name in FEATURE_COLUMNS_M10C
    if name.startswith("metric_") or name.startswith("workload_")
)
TRACE_EXPERT_COLUMNS = tuple(
    name for name in FEATURE_COLUMNS_M10C
    if name.startswith("trace_") or name.startswith("topology_") or name.startswith("coverage_")
)

FORBIDDEN_FEATURES = frozenset({
    "service", "system", "dataset", "case", "case_id", "incident_id",
    "root", "root_service", "fault", "fault_family", "label", "metric_name",
})


def validate_schema() -> None:
    if len(FEATURE_COLUMNS_M10C) != len(set(FEATURE_COLUMNS_M10C)):
        raise ValueError("M10C feature schema contains duplicates")
    if set(FEATURE_COLUMNS_M10C) & FORBIDDEN_FEATURES:
        raise ValueError("M10C feature schema leaks identity or truth")
    if len(FEATURE_COLUMNS_M10C) > 126:
        raise ValueError("M10C candidate schema does not reduce M9B by at least 50%")

