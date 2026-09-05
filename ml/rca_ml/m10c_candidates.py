"""Generic metric source contract and label-blind M10C candidate generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from .m10c_schema import METRIC_FAMILIES, RCAEVAL_SUFFIXES
from .m9b_features import is_infrastructure_entity, normalize_entity, service_key


@dataclass(frozen=True)
class CanonicalMetric:
    entity: str
    family: str
    timestamps: np.ndarray
    values: np.ndarray
    source_name: str


@dataclass(frozen=True)
class Candidate:
    name: str
    type: str = "service"
    has_metrics: bool = False
    has_traces: bool = False
    has_topology: bool = False


class MetricSource(Protocol):
    def list_families(self) -> tuple[str, ...]: ...
    def list_entities(self) -> tuple[str, ...]: ...
    def read_series(self, entity: str, family: str) -> tuple[CanonicalMetric, ...]: ...


class RCAEvalFrameSource:
    """RCAEval column adapter; the core consumes only canonical families."""

    def __init__(self, frame: pd.DataFrame, suffixes: dict[str, str] | None = None):
        if "time" not in frame:
            raise ValueError("metric frame has no time column")
        self._frame = frame.copy()
        self._frame["time"] = pd.to_numeric(self._frame["time"], errors="coerce")
        self._suffixes = dict(suffixes or RCAEVAL_SUFFIXES)
        invalid = set(self._suffixes.values()) - set(METRIC_FAMILIES)
        if invalid:
            raise ValueError(f"unknown canonical metric families: {sorted(invalid)}")
        self._columns: dict[tuple[str, str], list[str]] = {}
        for column in self._frame.columns:
            parsed = self._parse(column)
            if parsed:
                self._columns.setdefault(parsed, []).append(column)

    def _parse(self, column: str) -> tuple[str, str] | None:
        if column == "time":
            return None
        for suffix in sorted(self._suffixes, key=len, reverse=True):
            marker = "_" + suffix
            if str(column).endswith(marker) and len(str(column)) > len(marker):
                return str(column)[:-len(marker)], self._suffixes[suffix]
        return None

    def list_families(self) -> tuple[str, ...]:
        return tuple(sorted({family for _, family in self._columns}))

    def list_entities(self) -> tuple[str, ...]:
        return tuple(sorted({entity for entity, _ in self._columns}))

    def read_series(self, entity: str, family: str) -> tuple[CanonicalMetric, ...]:
        result = []
        for column in sorted(self._columns.get((entity, family), [])):
            values = pd.to_numeric(self._frame[column], errors="coerce")
            finite = np.isfinite(self._frame["time"]) & np.isfinite(values)
            result.append(CanonicalMetric(
                entity=normalize_entity(entity), family=family,
                timestamps=self._frame.loc[finite, "time"].to_numpy(dtype=float),
                values=values[finite].to_numpy(dtype=float), source_name=column,
            ))
        return tuple(result)


def resolve_metric_entity(entity: str, trace_services: tuple[str, ...] | list[str]) -> str | None:
    if is_infrastructure_entity(entity):
        return None
    wanted = service_key(entity)
    matches = sorted(service for service in set(trace_services) if service_key(service) == wanted)
    return matches[0] if len(matches) == 1 else normalize_entity(entity)


def generate_candidates(
    metric_source: MetricSource,
    trace_services: tuple[str, ...] | list[str],
    topology_services: tuple[str, ...] | list[str] = (),
) -> tuple[Candidate, ...]:
    traces = set(trace_services)
    topology = set(topology_services)
    metric_names = {
        mapped for entity in metric_source.list_entities()
        if (mapped := resolve_metric_entity(entity, trace_services)) is not None
    }
    names = sorted(metric_names | traces)
    return tuple(Candidate(
        name=name,
        has_metrics=name in metric_names,
        has_traces=name in traces,
        has_topology=name in topology,
    ) for name in names)


def candidates_from_audit(features: dict) -> tuple[Candidate, ...]:
    """Reconstruct the generic union from sealed telemetry metadata only."""
    traces = {
        item["service"] for item in features["services"]
        if float(item["vector"].get("has_trace", 0)) > 0
    }
    metric_names = {
        mapped for item in features["entity_mapping"]
        if (mapped := resolve_metric_entity(item["raw_entity"], sorted(traces))) is not None
    }
    topology = {
        item["service"] for item in features["services"]
        if any(float(item["vector"].get(name, 0)) != 0 for name in (
            "trace_in_degree", "trace_out_degree", "trace_ancestor_count", "trace_descendant_count"
        ))
    }
    return tuple(Candidate(
        name=name, has_metrics=name in metric_names, has_traces=name in traces,
        has_topology=name in topology,
    ) for name in sorted(metric_names | traces))

