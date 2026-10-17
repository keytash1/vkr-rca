"""Descriptive source timings, independent of ML scores/features/baseline.

Observed exclusive wall time is NOT CPU time or causal attribution. Subtract
the union of same-service CLIENT-descendant intervals inside a SERVER span.
Missing parents/sampling can make observed wait too small. Unknown remains null.
"""

from collections import defaultdict

MAX_VISITS = 200_000


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    position = (len(values)-1) * q
    left = int(position)
    right = min(left+1, len(values)-1)
    return values[left] + (values[right]-values[left]) * (position-left)


def union(intervals):
    total, end = 0, None
    for left, right in sorted(intervals):
        if right <= left:
            continue
        total += max(0, right-max(left, end if end is not None else left))
        end = max(end if end is not None else right, right)
    return total


def summarize_timings(spans, services, start_us, end_us):
    by_trace, children, selected = defaultdict(dict), defaultdict(lambda: defaultdict(list)), defaultdict(list)
    for span in spans:
        trace, identifier = span["trace_id"], span["span_id"]
        by_trace[trace][identifier] = span
        children[trace][span.get("parent_span_id", "")].append(span)
        if span["service"] in services and start_us <= span["start_time_us"] <= end_us:
            selected[span["service"]].append(span)
    visits = 0
    result = {}
    for service in services:
        local = selected[service]
        servers = [s for s in local if s.get("span_kind") == "SERVER"]
        timed = servers or local
        durations = [s["duration_us"] for s in timed]
        wait, exclusive = [], []
        exhausted = False
        for span in servers:
            pending = list(children[span["trace_id"]].get(span["span_id"], []))
            seen, intervals = {span["span_id"]}, []
            left, right = span["start_time_us"], span["start_time_us"]+span["duration_us"]
            while pending:
                item = pending.pop()
                visits += 1
                if visits > MAX_VISITS:
                    exhausted = True
                    break
                if item["span_id"] in seen:
                    raise ValueError("cyclic trace in descriptive projection")
                seen.add(item["span_id"])
                pending.extend(children[span["trace_id"]].get(item["span_id"], []))
                if item["service"] == service and item.get("span_kind") == "CLIENT":
                    a, b = max(left,item["start_time_us"]), min(right,item["start_time_us"]+item["duration_us"])
                    if b > a:
                        intervals.append((a,b))
            if exhausted:
                break
            observed_wait = min(span["duration_us"], union(intervals))
            wait.append(observed_wait)
            exclusive.append(span["duration_us"]-observed_wait)
        unresolved = sum(bool(s.get("parent_span_id")) and s["parent_span_id"] not in by_trace[s["trace_id"]] for s in local)
        result[service] = {
            "unit": "microseconds", "selection": "SERVER_SPANS" if servers else "ALL_KINDS_NO_SERVER_OBSERVED",
            "timed_spans": len(timed), "median_us": quantile(durations,.5),
            "p90_us": quantile(durations,.9), "max_us": max(durations) if durations else None,
            "observed_client_wait_median_us": quantile(wait,.5) if servers and not exhausted else None,
            "observed_exclusive_median_us": quantile(exclusive,.5) if servers and not exhausted else None,
            "wait_state": "BUDGET_EXCEEDED" if exhausted else "OBSERVED_SERVER_DECOMPOSITION" if servers else "NO_SERVER_SPANS",
            "unresolved_parent_spans": unresolved,
            "meaning": "OBSERVED_WALL_TIME_NOT_CPU_OR_CAUSAL_PROOF_SAMPLING_UNKNOWN",
        }
    return result
