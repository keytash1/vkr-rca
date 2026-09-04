"""Label-blind RCAEval sequence adapter for frozen detector-v2 evaluation."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from .detector_v2 import Config, detect_service, finite_output
from .m8b_adapter import canonical_operation

COLUMNS = ("traceID", "spanID", "parentSpanID", "serviceName", "methodName", "operationName",
           "startTime", "duration", "statusCode")


def evaluate_case(trace_path: Path, inject_unix: int, config: Config) -> dict:
    frame = pd.read_parquet(trace_path, columns=list(COLUMNS))
    start = int(inject_unix) * 1_000_000
    frame = frame[(frame["startTime"] >= start - 600_000_000) & (frame["startTime"] < start + 600_000_000)].copy()
    servers, coverage = infer_servers(frame)
    fault = detect_window(servers, start - 600_000_000, start, start, start + 600_000_000, config)
    healthy = detect_window(servers, start - 600_000_000, start - 300_000_000,
                            start - 300_000_000, start, config)
    result = {"fault": fault, "healthy": healthy, "coverage": coverage}
    if not finite_output(result):
        raise ValueError("non-finite temporal detector output")
    return result


def infer_servers(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    parents = frame[["traceID", "spanID", "serviceName"]].drop_duplicates(["traceID", "spanID"]).rename(
        columns={"spanID": "parentSpanID", "serviceName": "parentService"})
    merged = frame.merge(parents, how="left", on=["traceID", "parentSpanID"], sort=False, validate="many_to_one")
    parent_empty = merged["parentSpanID"].isna() | (merged["parentSpanID"].astype(str).str.strip() == "")
    cross_service = merged["parentService"].notna() & (merged["parentService"] != merged["serviceName"])
    servers = merged[parent_empty | cross_service].copy()
    nonempty = ~parent_empty
    parent_match = float(merged.loc[nonempty, "parentService"].notna().mean()) if nonempty.any() else 1.0
    return servers, {"input_spans": len(frame), "server_spans": len(servers), "parent_match_rate": parent_match,
                     "kind_inferred": True}


def detect_window(servers: pd.DataFrame, baseline_start: int, baseline_end: int,
                  current_start: int, current_end: int, config: Config) -> dict:
    selected = servers[(servers["startTime"] >= baseline_start) & (servers["startTime"] < current_end)].copy()
    method = selected["methodName"].fillna("").astype(str).str.strip()
    operation = selected["operationName"].fillna("").astype(str)
    raw = method.where(method != "", operation)
    mapping = {value: canonical_operation(value, value) for value in raw.unique()}
    selected["operation"] = raw.map(mapping)
    selected.sort_values(["startTime", "spanID"], inplace=True)
    services: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "baseline_latency_ms": [], "current_latency_ms": [], "baseline_failed": [], "current_failed": []}))
    status_known = 0
    for row in selected.itertuples(index=False):
        timestamp = int(row.startTime)
        phase = "baseline" if baseline_start <= timestamp < baseline_end else (
            "current" if current_start <= timestamp < current_end else None)
        if phase is None:
            continue
        status = _failed(row.statusCode)
        status_known += status is not None and phase == "current"
        values = services[str(row.serviceName)][str(row.operation)]
        values[f"{phase}_latency_ms"].append(float(row.duration) / 1000.0)
        values[f"{phase}_failed"].append(status)
    output = []
    for service, operations in sorted(services.items()):
        for values in operations.values():
            if len(values["baseline_latency_ms"]) > 1000:
                values["baseline_latency_ms"] = values["baseline_latency_ms"][-1000:]
                values["baseline_failed"] = values["baseline_failed"][-1000:]
        output.append({"service": service, **detect_service(operations, config)})
    anomalous = [value["service"] for value in output if value["anomalous"]]
    current_count = sum(len(values["current_latency_ms"]) for operations in services.values() for values in operations.values())
    return {
        "detector_version": "detector-v2", "config_sha256": config.digest(),
        "incident_detected": bool(anomalous), "anomalous_services": anomalous, "services": output,
        "current_error_evidence_coverage": status_known / current_count if current_count else 0.0,
        "error_channel_available": status_known > 0,
    }


def _failed(value) -> bool | None:
    if pd.isna(value):
        return None
    code = int(value)
    if code == 0:
        return False
    return (1 <= code <= 16) or code >= 400
