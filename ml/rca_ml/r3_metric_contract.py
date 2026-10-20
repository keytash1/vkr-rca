"""Research-only metric transform. No I/O, labels, fitting or runtime imports."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from statistics import median

VERSION = "metric-semantics-v1"
FAMILIES = ("cpu", "memory", "error", "latency")
FIELDS = ("available", "missing_fraction", "unavailable_fraction",
          "no_activity_fraction", "signed_median_shift", "p90_absolute_shift", "persistence")
COLUMNS = tuple(f"{family}_{field}" for family in FAMILIES for field in FIELDS)
FLOORS = {"cpu": .01, "memory": 1024**2, "error": .01, "latency": .001}
SCALE_RELATIVE_FLOOR = .05
MAX_RESIDUAL = 1e6
SEMANTICS = {
    "cpu": ("consumed_cores", "container_resource_gauge", 0, "sum_replicas", "service_containers"),
    "memory": ("working_set", "container_resource_gauge", 0, "sum_replicas", "service_containers"),
    "error": ("5xx_response_fraction", "counter_rate_ratio", 30, "ratio_of_summed_rates", "completed_business_server_requests"),
    "latency": ("histogram_estimated_p95", "histogram_quantile", 30, "quantile_of_summed_bucket_rates", "completed_business_server_requests"),
}
UNITS = {
    "cpu": {"cores": 1., "millicores": .001},
    "memory": {"bytes": 1., "KiB": 1024., "MiB": 1024.**2},
    "error": {"ratio": 1., "percent": .01},
    "latency": {"seconds": 1., "milliseconds": .001, "microseconds": 1e-6},
}
STATES = ("OBSERVED", "MISSING", "UNAVAILABLE", "NO_ACTIVITY")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def canonical_specs():
    return {family: dict(zip(("statistic", "source_kind", "lookback_seconds", "aggregation", "population"), spec),
                         unit=next(iter(UNITS[family]))) for family, spec in SEMANTICS.items()}


def schema_digest():
    return digest({"version": VERSION, "columns": COLUMNS, "floors": FLOORS,
                   "relative_floor": SCALE_RELATIVE_FLOOR, "max_residual": MAX_RESIDUAL,
                   "quantile": "linear", "persistence_threshold": 3., "baseline_min_samples": 20,
                   "baseline_min_coverage": .8})


def validate_specs(specs):
    if not isinstance(specs, dict) or set(specs) != set(FAMILIES):
        raise ValueError("FOUR_EXPLICIT_CHANNEL_SPECS_REQUIRED")
    keys = {"unit", "statistic", "source_kind", "lookback_seconds", "aggregation", "population"}
    for family in FAMILIES:
        spec = specs[family]
        if not isinstance(spec, dict) or set(spec) != keys:
            raise ValueError("CHANNEL_SPEC_FIELDS_INVALID")
        actual = tuple(spec[k] for k in ("statistic", "source_kind", "lookback_seconds", "aggregation", "population"))
        if (not isinstance(spec["unit"], str) or type(spec["lookback_seconds"]) is not int or actual != SEMANTICS[family]
                or spec["unit"] not in UNITS[family]):
            raise ValueError("CHANNEL_SEMANTICS_UNSUPPORTED:" + family)
    # Unit conversion is accepted; a different statistic or population is not.
    return digest({"version": VERSION, "semantics": SEMANTICS})


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return float(value)


@dataclass(frozen=True)
class Period:
    start: float
    end: float
    step: float
    services: tuple[str, ...]
    semantic_sha256: str
    # Complete grid, sorted by service/family/time: no raw tags or cause labels.
    records: tuple[tuple[str, str, float, str, float | None], ...]


def normalize_period(*, start, end, step, services, specs, records):
    signature = validate_specs(specs)
    start, end, step = map(number, (start, end, step))
    if not 0 < start < end or end-start > 3600 or not 1 <= step <= 60:
        raise ValueError("PERIOD_LIMIT_INVALID")
    services = tuple(services)
    if (not 1 <= len(services) <= 64
            or any(not isinstance(s, str) or not s or len(s) > 128 for s in services)
            or len(set(services)) != len(services)):
        raise ValueError("SERVICE_INVENTORY_INVALID")
    services = tuple(sorted(services))
    count = math.floor((end-start)/step) + 1
    by_key = {}
    for index, row in enumerate(records):
        if index >= 64*4*3601:
            raise ValueError("POINT_LIMIT_EXCEEDED")
        if not isinstance(row, dict) or set(row) != {"service", "family", "timestamp", "state", "value"}:
            raise ValueError("POINT_FIELDS_INVALID")
        service, family, state = row["service"], row["family"], row["state"]
        if service not in services or family not in FAMILIES or state not in STATES:
            raise ValueError("POINT_SCOPE_OR_STATE_INVALID")
        stamp = number(row["timestamp"])
        offset = (stamp-start)/step
        slot = round(offset)
        if not 0 <= slot < count or not math.isclose(offset, slot, abs_tol=1e-7, rel_tol=0):
            raise ValueError("POINT_OUTSIDE_QUERY_GRID")
        key = (service, family, slot)
        if key in by_key:
            raise ValueError("DUPLICATE_POINT_OR_UNAGGREGATED_REPLICAS")
        if state == "OBSERVED":
            value = number(row["value"]) * UNITS[family][specs[family]["unit"]]
            if not math.isfinite(value) or value < 0 or family == "error" and value > 1:
                raise ValueError("CANONICAL_VALUE_INVALID")
        else:
            if row["value"] is not None or state == "NO_ACTIVITY" and family not in {"error", "latency"}:
                raise ValueError("UNOBSERVED_VALUE_MUST_BE_UNDEFINED")
            value = None
        by_key[key] = (state, value)
    normalized = tuple((service, family, start+i*step, *by_key.get((service, family, i), ("MISSING", None)))
                       for service in services for family in FAMILIES for i in range(count))
    return Period(start, end, step, services, signature, normalized)


def quantile(values, q):
    ordered = sorted(values)
    position = (len(ordered)-1)*q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high]-ordered[low])*(position-low)


def grouped(period):
    result = {(s, f): [] for s in period.services for f in FAMILIES}
    for service, family, _, state, value in period.records:
        result[service, family].append((state, value))
    return result


@dataclass(frozen=True)
class Reference:
    end: float
    services: tuple[str, ...]
    semantic_sha256: str
    schema_sha256: str
    # Tuples avoid exposing mutable baseline dictionaries.
    values: tuple[tuple[str, str, float, float], ...]


def fit_reference(healthy):
    """Healthy statistics only, not an ML fit; never accepts target labels."""
    reference = []
    for (service, family), rows in grouped(healthy).items():
        values = [value for state, value in rows if state == "OBSERVED"]
        if len(values) < 20 or len(values)/len(rows) < .8:
            raise ValueError("HEALTHY_SUPPORT_INSUFFICIENT:" + service + ":" + family)
        center = median(values)
        scale = max(quantile(values, .75)-quantile(values, .25), abs(center)*SCALE_RELATIVE_FLOOR, FLOORS[family])
        reference.append((service, family, center, scale))
    return Reference(healthy.end, healthy.services, healthy.semantic_sha256, schema_digest(), tuple(reference))


def extract(reference, incident):
    if (reference.services != incident.services or reference.semantic_sha256 != incident.semantic_sha256
            or reference.schema_sha256 != schema_digest()):
        raise ValueError("REFERENCE_CONTRACT_OR_INVENTORY_MISMATCH")
    if reference.end >= incident.start:
        raise ValueError("HEALTHY_MUST_PRECEDE_INCIDENT_WITHOUT_OVERLAP")
    reference_values = {(s, f): (center, scale) for s, f, center, scale in reference.values}
    rows_by_key = grouped(incident)
    rows, saturated = [], 0
    for service in incident.services:
        vector = []
        for family in FAMILIES:
            samples = rows_by_key[service, family]
            center, scale = reference_values[service, family]
            residuals = []
            for state, value in samples:
                if state == "OBSERVED":
                    residual = (value-center)/scale
                    saturated += int(abs(residual) > MAX_RESIDUAL)
                    residuals.append(max(-MAX_RESIDUAL, min(MAX_RESIDUAL, residual)))
            vector.extend((float(bool(residuals)),
                           *(sum(s == state for s, _ in samples)/len(samples)
                             for state in ("MISSING", "UNAVAILABLE", "NO_ACTIVITY")),
                           median(residuals) if residuals else 0.,
                           quantile([abs(v) for v in residuals], .9) if residuals else 0.,
                           sum(abs(v) >= 3 for v in residuals)/len(residuals) if residuals else 0.))
        if len(vector) != 28 or not all(math.isfinite(v) for v in vector):
            raise ValueError("FEATURE_MATRIX_INVALID")
        rows.append({"service": service, "vector": vector})
    return {"version": VERSION, "columns": list(COLUMNS), "schema_sha256": schema_digest(),
            "semantic_sha256": incident.semantic_sha256, "saturated_observations": saturated,
            "rows": rows, "ranking_computed": False}
