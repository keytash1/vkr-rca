"""Versioned, explicit and leakage-resistant model feature schema."""

FEATURE_SCHEMA_VERSION = "m7-v1"
SOURCE_FEATURE_SCHEMA_VERSION = "m6-v1"
MODEL_VERSION = "m7-lambdamart-v1"

FEATURE_COLUMNS = (
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

FORBIDDEN_FEATURE_COLUMNS = frozenset(
    {
        "service",
        "service_name",
        "operation",
        "operation_name",
        "trace_id",
        "span_id",
        "request_id",
        "incident_id",
        "root_service",
        "fault_service",
        "fault_type",
        "fault_value",
        "fault_intensity",
        "scenario",
        "scenario_name",
        "expected_affected_services",
        "lexical_service_order",
        "m6_rank",
        "hybrid_v1_score",
        "label",
        "ground_truth",
    }
)

FEATURE_GROUPS = {
    "anomaly": (
        "latency_z_log1p",
        "error_z_log1p",
        "latency_strength",
        "error_strength",
        "latency_anomalous",
        "error_anomalous",
        "m5_severity_log1p",
        "is_observed_anomaly",
    ),
    "topology": (
        "topology_precision",
        "topology_recall",
        "topology_f1",
        "expected_affected_count",
        "expected_affected_ratio",
        "in_degree",
        "out_degree",
        "normalized_in_degree",
        "normalized_out_degree",
        "ancestor_count",
        "descendant_count",
        "ancestor_ratio",
        "descendant_ratio",
    ),
    "trace": (
        "local_evidence",
        "trace_coverage",
        "median_exclusive_ratio",
        "median_downstream_wait_ratio",
        "log1p_median_exclusive_duration_ms",
    ),
    "global": (
        "active_topology_trace_coverage",
        "ready_universe_size",
        "observed_anomaly_count",
        "observed_anomaly_ratio",
        "primary_signal_latency",
        "primary_signal_error",
        "topology_source_active",
    ),
}


def validate_schema() -> None:
    """Fail closed if a forbidden or duplicated model feature is introduced."""
    if len(FEATURE_COLUMNS) != len(set(FEATURE_COLUMNS)):
        raise ValueError("FEATURE_COLUMNS contains duplicates")
    leaked = set(FEATURE_COLUMNS) & FORBIDDEN_FEATURE_COLUMNS
    if leaked:
        raise ValueError(f"forbidden model features: {sorted(leaked)}")
    grouped = [column for values in FEATURE_GROUPS.values() for column in values]
    if sorted(grouped) != sorted(FEATURE_COLUMNS):
        raise ValueError("FEATURE_GROUPS must cover FEATURE_COLUMNS exactly once")
