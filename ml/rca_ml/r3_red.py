"""Experimental unit-aware RED evidence; never imported by frozen inference."""
from __future__ import annotations

import math
from statistics import median

import numpy as np

UNITS = {"request_rate": "requests_per_second", "error_ratio": "ratio", "latency_p95": "seconds"}
FLOORS = {"error_ratio": .01, "latency_p95": .001}


def values(observations: list[dict], services: tuple[str, ...]) -> dict:
    grouped = {s: {c: [] for c in UNITS} for s in services}
    seen = set()
    for row in observations:
        if set(row) != {"service", "channel", "unit", "timestamp", "value"}:
            raise ValueError("unexpected fields at RED boundary")
        service, channel = row["service"], row["channel"]
        if service not in grouped or channel not in UNITS or row["unit"] != UNITS[channel]:
            raise ValueError("unknown RED service/channel or unit mismatch")
        timestamp = row["timestamp"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("invalid RED timestamp")
        key = (service, channel, timestamp)
        if key in seen:
            raise ValueError("unaggregated or duplicate RED series")
        seen.add(key)
        value = row["value"]
        if value is None:  # undefined query result, not zero
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid RED value")
        if channel == "error_ratio" and value > 1:
            raise ValueError("error ratio must be within [0,1], not percent")
        grouped[service][channel].append(float(value))
    return grouped


def fit_healthy(observations: list[dict], services: tuple[str, ...]) -> dict:
    grouped = values(observations, services)
    baseline = {}
    for service, channels in grouped.items():
        if any(not data for data in channels.values()) or median(channels["request_rate"]) <= 0:
            raise ValueError("healthy RED support is incomplete or inactive")
        baseline[service] = {}
        for channel, floor in FLOORS.items():
            data = channels[channel]
            q25, q75 = np.quantile(data, [.25, .75])
            baseline[service][channel] = {"median": median(data), "scale": max(float(q75-q25), floor)}
    return baseline


def evidence(observations: list[dict], baseline: dict, services: tuple[str, ...], source_states: dict) -> dict:
    grouped = values(observations, services)
    if set(source_states) != set(services) or any(s not in {"available", "unavailable", "unknown"} for s in source_states.values()):
        raise ValueError("explicit per-service source coverage is required")
    scores, states, shifts = {}, {}, {}
    for service, channels in grouped.items():
        rate = median(channels["request_rate"]) if channels["request_rate"] else None
        if source_states[service] != "available":
            state = "source_" + source_states[service]
        elif rate is None:
            state = "unavailable"
        elif rate == 0:
            state = "no_activity"
        elif any(not channels[c] for c in FLOORS):
            state = "incomplete"
        else:
            state = "available"
        states[service] = state
        shifts[service] = {}
        for channel in FLOORS:
            reference = baseline[service][channel]
            shifts[service][channel] = (
                max(0.0, (median(channels[channel])-reference["median"])/reference["scale"])
                if channels[channel] and state == "available" else None
            )
        scores[service] = max(shifts[service].values()) if state == "available" else 0.0
    return {"scores": scores, "states": states, "shifts": shifts,
            "eligible_for_fusion": all(s == "available" for s in states.values())
                                   and len(set(scores.values())) > 1 and max(scores.values()) > 0}


def average_ranks(scores: dict[str, float]) -> dict[str, float]:
    ordered = sorted(scores, key=lambda s: (-scores[s], s))
    result = {}
    for service in ordered:
        better = sum(v > scores[service] for v in scores.values())
        tied = sum(v == scores[service] for v in scores.values())
        result[service] = 1 + better + (tied-1)/2
    return result


def fuse(ranking: list[dict], red: dict) -> list[dict]:
    if not red["eligible_for_fusion"]:
        return [dict(row) for row in ranking]
    ranks = average_ranks(red["scores"])
    if set(ranks) != {r["service"] for r in ranking}:
        raise ValueError("RED and ML candidate universes differ")
    combined = [{"service": r["service"], "score": 1/(60+r["rank"])+1/(60+ranks[r["service"]]),
                 "original_rank": r["rank"]} for r in ranking]
    combined.sort(key=lambda r: (-r["score"], r["original_rank"]))
    return [{"service": r["service"], "score": r["score"], "rank": i} for i, r in enumerate(combined, 1)]
