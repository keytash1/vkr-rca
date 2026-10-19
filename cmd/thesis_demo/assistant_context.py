"""Pure allowlisted context; no ML imports, credentials, labels or network I/O."""

from __future__ import annotations

import copy
import json
import math
from baseline_applicability import context_projection as baseline_context
from context_catalog import assistant_projection as context_projection
from http_observations import CHANNELS as HTTP_CHANNELS, FAMILIES as HTTP_FAMILIES


def assistant_context(catalog, *, ranking=None, summary_only=False):
    """Neutral default for the blind comparison; rank is an explicit opt-in.

    No drop-top-k or score-based ordering. Summary projection keeps every fact
    and quality marker, and declares that detailed series/examples were omitted.
    """

    def pick(value, names):
        return {key: copy.deepcopy(value[key]) for key in names if key in value}

    facts = []
    for fact in catalog["observations"]:
        clean = pick(fact, ("id", "service", "kind", "start_unix", "end_unix"))
        value = fact["values"]
        if fact["kind"] == "metric":
            clean["values"] = pick(
                value,
                (
                    "family",
                    "unit",
                    "samples",
                    "min",
                    "median",
                    "max",
                    "returned_point_coverage",
                    "state",
                ),
            )
            comparison = value.get("baseline_comparison")
            if value.get("family") in HTTP_FAMILIES.values():
                channel = next(c for c, family in HTTP_FAMILIES.items() if family == value["family"])
                unit, statistic = HTTP_CHANNELS[channel]
                if (value.get("unit"), value.get("statistic"), value.get("model_input")) != (unit, statistic, False):
                    raise ValueError("invalid supplemental HTTP observation semantics")
                clean["values"].update(statistic=statistic, model_input=False)
                lookback = value.get("query_lookback_seconds")
                if type(lookback) is not int or not 1 <= lookback <= 3600:
                    raise ValueError("invalid HTTP observation lookback")
                clean["values"]["query_lookback_seconds"] = lookback
            clean["values"]["baseline_comparison"] = (
                pick(
                    comparison,
                    (
                        "expected_at_observed_load",
                        "residual_iqr",
                        "absolute_residual_p90",
                        "method",
                        "healthy_start_unix",
                        "healthy_end_unix",
                        "load_comparability",
                    ),
                )
                if comparison
                else None
            )
            if not summary_only:
                clean["values"]["series"] = [
                    pick(
                        item,
                        ("start_unix", "end_unix", "min", "max", "mean", "samples"),
                    )
                    for item in value["series"]
                ]
        elif fact["kind"] == "traces":
            clean["values"] = pick(
                value,
                (
                    "state",
                    "observed_spans",
                    "observed_error_spans",
                    "sampling",
                    "retention",
                    "example_selection",
                ),
            )
            if not summary_only:
                clean["values"]["examples"] = [
                    pick(
                        span,
                        (
                            "trace_id",
                            "span_id",
                            "start_time_us",
                            "duration_us",
                            "error",
                        ),
                    )
                    for span in value["examples"]
                ]
            if value.get("timing") is not None:
                clean["values"]["timing"] = pick(value["timing"], (
                    "unit", "selection", "timed_spans", "median_us", "p90_us", "max_us",
                    "observed_client_wait_median_us", "observed_exclusive_median_us",
                    "wait_state", "unresolved_parent_spans", "meaning"))
        elif fact["kind"] == "dependencies":
            clean["values"] = pick(
                value, ("state", "meaning", "external_edge_observations")
            )
            clean["values"]["edges"] = [
                pick(edge, ("source", "target", "observed_edges"))
                for edge in value["edges"]
            ]
        elif fact["kind"] == "context":
            projection = context_projection(value)
            if projection is None:
                continue  # Raw context stays local without explicit operator opt-in.
            clean["values"] = projection
        else:
            raise ValueError("unsupported assistant observation kind")
        facts.append(clean)
    services = sorted(catalog["services"])
    result = {
        "context_version": "assistant-context-v1",
        "services": services,
        "start_unix": catalog["start_unix"],
        "end_unix": catalog["end_unix"],
        "requests_per_second": catalog["requests_per_second"],
        "source_quality": pick(
            catalog["source_quality"],
            (
                "traces",
                "sampling",
                "retention",
                "source_annotation_count",
                "collected_at_unix",
            ),
        ),
        "observations": sorted(facts, key=lambda f: (f["service"], f["kind"], f["id"])),
        "limitations": list(catalog["limitations"]),
    }
    if any(f["kind"] == "context" and f["values"].get("assistant_categories_enabled") is not True for f in catalog["observations"]):
        result["limitations"].append("INCIDENT_CONTEXT_NOT_DISCLOSED_TO_ASSISTANT")
    if summary_only:
        result["projection"] = {
            "kind": "all_candidate_summaries",
            "omitted_detail_fields": ["metric.series", "traces.examples"],
            "observations_included": len(facts),
            "candidates_included": len(services),
        }
    applicability = baseline_context(catalog["source_quality"].get("baseline_applicability"),
                                     catalog["start_unix"], catalog["end_unix"], catalog["requests_per_second"])
    if applicability is not None:
        result["source_quality"]["baseline_applicability"] = applicability
    http_status = catalog["source_quality"].get("http_observations")
    if isinstance(http_status, dict):
        states = {s: state for s, state in http_status.get("services", {}).items()
                  if s in services and state in {"OBSERVED", "NO_ACTIVITY", "PARTIAL", "INCOMPLETE", "UNAVAILABLE"}}
        result["source_quality"]["http_observations"] = {
            "status": http_status.get("status") if http_status.get("status") in {"complete", "partial", "unavailable"} else "unavailable",
            "services": states, "model_input": False}
    if ranking is not None:
        if (
            not isinstance(ranking, list)
            or len(ranking) != len(services)
            or {r["service"] for r in ranking} != set(services)
            or sorted(r["rank"] for r in ranking) != list(range(1, len(services) + 1))
            or any(
                isinstance(r["rank"], bool)
                or not isinstance(r["rank"], int)
                or isinstance(r["model_score"], bool)
                or not isinstance(r["model_score"], (int, float))
                or not math.isfinite(r["model_score"])
                for r in ranking
            )
        ):
            raise ValueError("ranking hint inventory or values differ")
        result["ranking_hint"] = [
            {k: r[k] for k in ("service", "rank", "model_score")}
            for r in sorted(ranking, key=lambda r: r["rank"])
        ]
    return result


def compact_prompt_context(context):
    """Lossless factoring of repeated metadata; no top-k or numerical rounding.

    Per-fact times are inherited only when exactly equal to the shared interval.
    Baseline method/healthy interval/comparability remain explicit references.
    """
    result = copy.deepcopy(context)
    references = {}
    common_keys = (
        "method",
        "healthy_start_unix",
        "healthy_end_unix",
        "load_comparability",
    )
    for fact in result["observations"]:
        if (fact.get("start_unix"), fact.get("end_unix")) == (
            result["start_unix"],
            result["end_unix"],
        ):
            del fact["start_unix"]
            del fact["end_unix"]
        comparison = fact["values"].get("baseline_comparison")
        if comparison:
            shared = {
                key: comparison.pop(key) for key in common_keys if key in comparison
            }
            signature = json.dumps(shared, sort_keys=True, separators=(",", ":"))
            if signature not in references:
                references[signature] = (f"baseline-{len(references) + 1}", shared)
            comparison["context_ref"] = references[signature][0]
    result["baseline_contexts"] = {
        identifier: fields for identifier, fields in references.values()
    }
    baseline_fields = sorted(
        {
            key
            for fact in result["observations"]
            for key in (fact["values"].get("baseline_comparison") or {})
        }
    )
    comparisons = [
        fact["values"]["baseline_comparison"]
        for fact in result["observations"]
        if fact["values"].get("baseline_comparison")
    ]
    if comparisons and all(
        set(comparison) == set(baseline_fields) for comparison in comparisons
    ):
        for fact in result["observations"]:
            comparison = fact["values"].get("baseline_comparison")
            if comparison:
                fact["values"]["baseline_comparison"] = [
                    comparison[key] for key in baseline_fields
                ]
        result["baseline_value_fields"] = baseline_fields
    tables = {}
    for fact in result.pop("observations"):
        fact_fields = tuple(sorted(set(fact) - {"kind", "values"}))
        value_fields = tuple(sorted(fact["values"]))
        key = (fact["kind"], fact_fields, value_fields)
        if key not in tables:
            tables[key] = {
                "kind": fact["kind"],
                "fact_fields": list(fact_fields),
                "value_fields": list(value_fields),
                "rows": [],
            }
        tables[key]["rows"].append(
            [
                *[fact[field] for field in fact_fields],
                [fact["values"][field] for field in value_fields],
            ]
        )
    result["observation_tables"] = [tables[key] for key in sorted(tables)]
    result["transport_encoding"] = {
        "version": "factored-context-v1",
        "fact_time_default": "top_level_interval_if_not_explicit",
        "baseline_context_ref": "baseline_contexts",
        "numeric_values_rounded": False,
        "table_row": "fact_fields values followed by value_fields values array",
        "baseline_value_row": "baseline_value_fields order if this field is present",
    }
    return result
