"""Strict outbound aggregate projection. Identity mapping stays on the host.

Pseudonyms do not anonymize numeric telemetry. The operator still needs consent
for the selected destination and data category; projection is defense in depth.
"""

from __future__ import annotations

import math

from assistant_context import assistant_context

UNITS = {
    "cpu": "cores",
    "memory": "bytes",
    "network": "bytes_per_second",
    "traffic_rate": "bytes_per_second",
}
STATES = {"OBSERVED", "MISSING", "UNAVAILABLE", "NOT_OBSERVED"}
BASELINE_METHOD = "workload_linear_prediction_and_residual_iqr"


class PrivacyError(ValueError):
    pass


def _number(value, *, nullable=False, count=False):
    if value is None and nullable:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (count and (not isinstance(value, int) or value < 0))
    ):
        raise PrivacyError("OUTBOUND_NUMBER_INVALID")
    return value


def prepare_outbound_aggregates(catalog, *, ranking=None, include_details=False):
    """Return (catalog, rank hint, local identity map); no free-form strings.

    Refuse unknown semantics rather than passing a new arbitrary field/string.
    Every service is retained and pseudonyms are independent of ranking.
    """
    projected = assistant_context(
        catalog, ranking=ranking, summary_only=not include_details
    )
    services = projected["services"]
    if len(services) != len(set(services)) or not services or len(services) > 100:
        raise PrivacyError("OUTBOUND_INVENTORY_INVALID")
    names = {name: f"svc-{index:03d}" for index, name in enumerate(services, 1)}
    clean = {
        "services": list(names.values()),
        "start_unix": _number(projected["start_unix"]),
        "end_unix": _number(projected["end_unix"]),
        "requests_per_second": _number(projected["requests_per_second"]),
        "source_quality": {},
        "observations": [],
        "limitations": [
            "DIAGNOSTIC_OBSERVATIONS_NOT_CAUSAL_PROOF",
            "BASELINE_LOAD_COMPARABILITY_NOT_ESTABLISHED",
            "SAMPLING_AND_RETENTION_UNKNOWN",
            "PSEUDONYM_NUMBERS_ARE_NEUTRAL_NOT_RANKS",
            "ONLY_AGGREGATES_NO_RAW_SPANS_OR_SOURCE_URLS",
        ],
    }
    trace_status = projected["source_quality"].get("traces")
    for marker in ("INCIDENT_CONTEXT_NOT_DISCLOSED_TO_ASSISTANT", "CONTEXT_IS_BOUNDED_SOURCE_ASSERTIONS_NOT_PROOF"):
        if marker in projected["limitations"]:
            clean["limitations"].append(marker)
    if trace_status not in {"available", "unavailable", "REPLAY_STATUS_UNKNOWN"}:
        raise PrivacyError("OUTBOUND_TRACE_STATUS_INVALID")
    clean["source_quality"] = {
        "traces": trace_status,
        "sampling": "UNKNOWN",
        "retention": "UNKNOWN",
    }
    applicability = projected["source_quality"].get("baseline_applicability")
    if applicability is not None:
        # assistant_context reconstructs this numeric/enum-only structure. No
        # arbitrary provenance text, URLs or credentials enter the projection.
        clean["source_quality"]["baseline_applicability"] = applicability
    fact_ids, identities = {}, set()
    ordered = sorted(
        projected["observations"],
        key=lambda f: (f["service"], f["kind"], f["values"].get("family", "")),
    )
    for fact in ordered:
        service, kind, values = fact["service"], fact["kind"], fact["values"]
        identity = (service, kind, values.get("family", ""))
        if service not in names or identity in identities or fact["id"] in fact_ids:
            raise PrivacyError("OUTBOUND_OBSERVATION_IDENTITY_INVALID")
        identities.add(identity)
        identifier = f"obs-{len(fact_ids) + 1:03d}"
        fact_ids[fact["id"]] = identifier
        if values.get("state") not in STATES:
            raise PrivacyError("OUTBOUND_STATE_INVALID")
        value = {"state": values["state"]}
        if kind == "metric":
            family = values["family"]
            if family not in UNITS or values["unit"] != UNITS[family]:
                raise PrivacyError("OUTBOUND_UNIT_INVALID")
            value.update(
                family=family,
                unit=UNITS[family],
                samples=_number(values["samples"], count=True),
                series=[],
            )
            for key in ("min", "median", "max", "returned_point_coverage"):
                value[key] = _number(values.get(key), nullable=True)
            comparison = values.get("baseline_comparison")
            value["baseline_comparison"] = None
            if comparison:
                if (
                    comparison["method"] != BASELINE_METHOD
                    or comparison["load_comparability"] != "NOT_ESTABLISHED"
                ):
                    raise PrivacyError("OUTBOUND_BASELINE_SEMANTICS_INVALID")
                value["baseline_comparison"] = {
                    key: _number(comparison[key], nullable=key.startswith("healthy_"))
                    for key in (
                        "expected_at_observed_load",
                        "residual_iqr",
                        "absolute_residual_p90",
                        "healthy_start_unix",
                        "healthy_end_unix",
                    )
                }
                value["baseline_comparison"].update(
                    method=BASELINE_METHOD, load_comparability="NOT_ESTABLISHED"
                )
            if include_details:
                series = values.get("series", [])
                if not isinstance(series, list) or len(series) > 64:
                    raise PrivacyError("OUTBOUND_SERIES_BUDGET")
                previous_end = None
                for item in series:
                    point = {
                        key: _number(item[key], count=key == "samples")
                        for key in (
                            "start_unix",
                            "end_unix",
                            "min",
                            "max",
                            "mean",
                            "samples",
                        )
                    }
                    if (
                        not fact["start_unix"]
                        <= point["start_unix"]
                        <= point["end_unix"]
                        <= fact["end_unix"]
                        or (
                            previous_end is not None
                            and point["start_unix"] <= previous_end
                        )
                        or not point["min"] <= point["mean"] <= point["max"]
                        or point["samples"] < 1
                    ):
                        raise PrivacyError("OUTBOUND_SERIES_INVALID")
                    previous_end = point["end_unix"]
                    value["series"].append(point)
        elif kind == "traces":
            value.update(
                observed_spans=_number(values["observed_spans"], count=True),
                observed_error_spans=_number(
                    values["observed_error_spans"], count=True
                ),
                sampling="UNKNOWN",
                retention="UNKNOWN",
                examples=[],
                example_selection="OMITTED_AGGREGATES_ONLY",
            )
            if values.get("timing") is not None:
                timing = values["timing"]
                if (timing.get("unit") != "microseconds" or timing.get("selection") not in {
                    "SERVER_SPANS", "ALL_KINDS_NO_SERVER_OBSERVED"} or timing.get("wait_state") not in {
                    "BUDGET_EXCEEDED", "OBSERVED_SERVER_DECOMPOSITION", "NO_SERVER_SPANS"}
                    or timing.get("meaning") != "OBSERVED_WALL_TIME_NOT_CPU_OR_CAUSAL_PROOF_SAMPLING_UNKNOWN"):
                    raise PrivacyError("OUTBOUND_TRACE_TIMING_SEMANTICS")
                projected_timing = {key: timing[key] for key in ("unit", "selection", "wait_state", "meaning")}
                for key in ("timed_spans", "unresolved_parent_spans"):
                    projected_timing[key] = _number(timing[key], count=True)
                for key in ("median_us", "p90_us", "max_us", "observed_client_wait_median_us", "observed_exclusive_median_us"):
                    projected_timing[key] = _number(timing[key], nullable=True)
                    if projected_timing[key] is not None and projected_timing[key] < 0:
                        raise PrivacyError("OUTBOUND_TRACE_TIMING_INVALID")
                value["timing"] = projected_timing
            if include_details:
                examples = values.get("examples", [])
                if not isinstance(examples, list) or len(examples) > 3:
                    raise PrivacyError("OUTBOUND_TRACE_EXAMPLE_BUDGET")
                for item in examples:
                    start = _number(item["start_time_us"])
                    duration = _number(item["duration_us"])
                    if (
                        not fact["start_unix"] <= start / 1e6 <= fact["end_unix"]
                        or duration < 0
                        or not isinstance(item["error"], bool)
                    ):
                        raise PrivacyError("OUTBOUND_TRACE_EXAMPLE_INVALID")
                    value["examples"].append(
                        {
                            "start_time_us": start,
                            "duration_us": duration,
                            "error": item["error"],
                        }
                    )
                value["example_selection"] = (
                    "ERROR_FIRST_THEN_LONGEST_NOT_RANDOM_NO_IDENTIFIERS"
                )
        elif kind == "dependencies":
            value.update(
                edges=[],
                external_edge_observations=_number(
                    values["external_edge_observations"], count=True
                ),
                meaning="OBSERVED_CALLS_NOT_CAUSAL_PROOF",
            )
            for edge in values["edges"]:
                if edge["source"] not in names or edge["target"] not in names:
                    raise PrivacyError("OUTBOUND_EDGE_OUTSIDE_INVENTORY")
                value["edges"].append(
                    {
                        "source": names[edge["source"]],
                        "target": names[edge["target"]],
                        "observed_edges": _number(edge["observed_edges"], count=True),
                    }
                )
        elif kind == "context":
            from context_catalog import assistant_projection
            value = assistant_projection(values)
            if value is None:
                raise PrivacyError("OUTBOUND_CONTEXT_NOT_APPROVED")
        else:
            raise PrivacyError("OUTBOUND_KIND_INVALID")
        clean["observations"].append(
            {
                "id": identifier,
                "service": names[service],
                "kind": kind,
                "start_unix": _number(fact["start_unix"]),
                "end_unix": _number(fact["end_unix"]),
                "values": value,
            }
        )
    hint = None
    if ranking is not None:
        hint = [
            {
                "service": names[row["service"]],
                "rank": row["rank"],
                "model_score": row["model_score"],
            }
            for row in projected["ranking_hint"]
        ]
    # This sidecar is LOCAL ONLY; it must not be appended to prompt or tools.
    local_mapping = {
        "services": names,
        "observations": fact_ids,
        "privacy_version": "aggregate-egress-v3-source-timings-details"
        if include_details
        else "aggregate-egress-v3-source-timings-summary",
    }
    if any(f["kind"] == "context" for f in catalog["observations"]):
        local_mapping["privacy_version"] = "aggregate-egress-v4-incident-context"
    return clean, hint, local_mapping
