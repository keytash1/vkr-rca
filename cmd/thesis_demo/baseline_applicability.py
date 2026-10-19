"""Explain baseline provenance without changing features, scores or candidates.

A single healthy interval supplies ONE aggregate model input, not a validated
load distribution. Matching it never certifies transfer or causality.
"""

import math

VERSION = "baseline-applicability-v1"
SOURCES = {"profile_constant", "measured_interval_mean"}


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        return None
    return float(value)


def assess(provenance, start, end, current_rps, current_source=None):
    """Return an allowlisted explanation; malformed/old metadata stays unknown."""
    provenance = provenance if isinstance(provenance, dict) else {}
    healthy_start = _number(provenance.get("healthy_start_unix"))
    healthy_end = _number(provenance.get("healthy_end_unix"))
    temporal = "UNKNOWN"
    if healthy_start is not None and healthy_end is not None and healthy_start < healthy_end:
        # Metric windows include both boundaries. A shared endpoint therefore
        # overlaps; Loki's end-exclusive research contract is unrelated here.
        temporal = ("PRECEDES" if healthy_end < start else
                    "AFTER" if healthy_start > end else "OVERLAPS")
    else:
        healthy_start = healthy_end = None
    reference = provenance.get("workload_reference")
    reference = reference if isinstance(reference, dict) else {}
    reference_rps = _number(reference.get("requests_per_second"), positive=True)
    reference_source = reference.get("source")
    if (type(reference.get("version")) is not int or reference["version"] != 1
            or not isinstance(reference_source, str) or reference_source not in SOURCES or reference_rps is None):
        reference_rps, reference_source = None, "unknown"
    if not isinstance(current_source, str) or current_source not in SOURCES:
        current_source = "unknown"
    current = _number(current_rps, positive=True)
    ratio = current / reference_rps if current is not None and reference_rps is not None else None
    if ratio is not None and not math.isfinite(ratio):
        ratio = None
    relation = "UNKNOWN"
    if current is not None and reference_rps is not None:
        # Numerical equality only; not an empirical tolerance or acceptance gate.
        relation = ("SAME_REFERENCE_RPS" if math.isclose(current, reference_rps, rel_tol=1e-12)
                    else "DIFFERENT_REFERENCE_RPS")
    reasons = []
    if temporal != "PRECEDES":
        reasons.append("HEALTHY_PERIOD_" + temporal)
    if reference_source == "unknown":
        reasons.append("REFERENCE_LOAD_UNKNOWN")
    elif reference_source == "profile_constant":
        reasons.append("REFERENCE_LOAD_CONFIGURED_NOT_MEASURED")
    if current_source == "unknown":
        reasons.append("CURRENT_LOAD_SOURCE_UNKNOWN")
    elif current_source == "profile_constant":
        reasons.append("CURRENT_LOAD_CONFIGURED_NOT_MEASURED")
    if relation == "DIFFERENT_REFERENCE_RPS":
        reasons.append("LOAD_DIFFERS_FROM_SINGLE_REFERENCE")
    if current is None:
        reasons.append("CURRENT_LOAD_UNKNOWN")
    return {
        "version": VERSION, "state": "REVIEW_REQUIRED" if reasons else "REFERENCE_ONLY",
        "healthy_start_unix": healthy_start, "healthy_end_unix": healthy_end,
        "temporal_relation": temporal, "reference_rps": reference_rps,
        "current_rps": current, "rps_ratio": ratio,
        "reference_source": reference_source, "current_source": current_source,
        "load_relation": relation, "reasons": reasons,
        "meaning": "PROVENANCE_CHECK_NOT_MODEL_CONFIDENCE_OR_CAUSAL_PROOF",
    }


def context_projection(value, start, end, current_rps):
    """Never copy arbitrary provenance/quality fields to a provider."""
    if not isinstance(value, dict) or value.get("version") != VERSION:
        return None
    # Reconstruct numeric and enum fields rather than trusting nested payloads.
    return assess({
        "healthy_start_unix": value.get("healthy_start_unix"),
        "healthy_end_unix": value.get("healthy_end_unix"),
        "workload_reference": {"version": 1, "requests_per_second": value.get("reference_rps"),
                               "source": value.get("reference_source")},
    }, start, end, current_rps, value.get("current_source"))
