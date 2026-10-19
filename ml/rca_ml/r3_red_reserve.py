"""Research-only topology-aware RED reserve; not a calibrated cause probability."""
from __future__ import annotations

import math
from statistics import median

from .r3_red import FLOORS, evidence, values


def reserve(ranking, observations, healthy, services, source_states, edges, *, traces_available):
    """Keep ML with traces; otherwise prioritize unexplained anomalous frontier.

    Matching a downstream symptom is a heuristic, not subtraction of quantiles
    or causal proof. All ties retain the original ML order.
    """
    if set(services) != set(healthy) or set(services) != {r["service"] for r in ranking} or len(ranking) != len(services):
        raise ValueError("reserve candidate universe differs")
    if [r["rank"] for r in ranking] != list(range(1, len(services)+1)):
        raise ValueError("original ranking must be ordered and complete")
    original = [dict(r) for r in ranking]
    def unchanged(reason, **details):
        return {"applied": False, "reason": reason, "ranking": original, **details}
    if traces_available:
        return unchanged("incident_traces_available")
    red = evidence(observations, healthy, services, source_states)
    if any(state not in {"available", "no_activity"} for state in red["states"].values()):
        return unchanged("incomplete_red", states=red["states"])
    children = {s: set() for s in services}
    for edge in edges:
        if set(edge) != {"source", "target", "presence"}:
            raise ValueError("unexpected topology fields")
        a, b, presence = edge["source"], edge["target"], edge["presence"]
        if a not in children or b not in children or isinstance(presence, bool) or not isinstance(presence, (int, float)) or not math.isfinite(presence) or not 0 <= presence <= 1:
            raise ValueError("invalid topology edge")
        if a != b and presence >= .5:
            children[a].add(b)
    if not any(children.values()):
        return unchanged("no_healthy_topology")
    # Cycles do not identify a unique downstream frontier: abstain explicitly.
    visited, pending = set(), set()
    def visit(service):
        if service in pending:
            return False
        if service in visited:
            return True
        pending.add(service)
        if not all(visit(child) for child in children[service]):
            return False
        pending.remove(service)
        visited.add(service)
        return True
    if not all(visit(service) for service in services):
        return unchanged("cyclic_healthy_topology")
    grouped = values(observations, services)
    deltas = {s: {c: max(0., median(grouped[s][c])-healthy[s][c]["median"])
                   if grouped[s][c] and red["states"][s] == "available" else None
                   for c in FLOORS} for s in services}
    channels = {s: {c for c in FLOORS if red["shifts"][s][c] is not None and red["shifts"][s][c] >= 3}
                for s in services}
    anomalous = {s for s in services if channels[s]}
    if not anomalous:
        return unchanged("no_supported_red_anomaly")
    compatible = {s: [] for s in services}
    for service in anomalous:
        for child in sorted(children[service] & anomalous):
            common = [c for c in sorted(channels[service] & channels[child])
                      if deltas[child][c] >= .5*deltas[service][c]]
            if common:
                compatible[service].append({"service": child, "channels": common})
    frontier = {s for s in anomalous if not compatible[s]}
    # Scores only order within a tier. They are not comparable to ML scores.
    ordered = sorted(original, key=lambda r: (
        -int(r["service"] in frontier), -int(r["service"] in anomalous),
        -red["scores"][r["service"]], r["rank"]))
    reordered = [{"service": r["service"], "rank": i, "score": red["scores"][r["service"]],
                  "original_rank": r["rank"]} for i, r in enumerate(ordered, 1)]
    return {"applied": True, "reason": "supported_red_frontier", "ranking": reordered,
            "frontier": sorted(frontier), "compatible_downstream_symptoms": compatible,
            "states": red["states"], "shifts": red["shifts"], "deltas": deltas,
            "warning": "Heuristic diagnostic priority, not a cause probability or proof"}
