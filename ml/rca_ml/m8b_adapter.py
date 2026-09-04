"""Truth-isolated RCAEval Parquet adapter for the locked M8B protocol."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

PROTOCOL_VERSION = "m8b-v1"
REQUIRED_COLUMNS = (
    "traceID",
    "spanID",
    "parentSpanID",
    "serviceName",
    "methodName",
    "operationName",
    "startTime",
    "duration",
    "statusCode",
)
_UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_INTEGER = re.compile(r"^[0-9]+$")


def canonical_operation(method_name: object, operation_name: object) -> str:
    value = _text(method_name) or _text(operation_name)
    value = value.split("?", 1)[0].strip()
    if not value:
        return "unknown"
    parts = value.split("/")
    normalized = ["{uuid}" if _UUID.fullmatch(part) else "{id}" if _INTEGER.fullmatch(part) else part for part in parts]
    return "/".join(normalized)


def audit_schema(path: str | Path) -> dict:
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    missing = sorted(set(REQUIRED_COLUMNS) - set(schema.names))
    if missing:
        raise ValueError(f"unsupported trace schema; missing columns: {missing}")
    return {
        "rows": parquet.metadata.num_rows,
        "columns": [{"name": field.name, "type": str(field.type), "nullable": field.nullable} for field in schema],
    }


def run_adapter(
    trace_path: str | Path,
    *,
    external_case_id: str,
    inject_unix: int,
    mode: str,
    binary: str | Path,
) -> dict:
    if mode not in {"fault", "healthy"}:
        raise ValueError("mode must be fault or healthy")
    audit_schema(trace_path)
    start_us = (inject_unix - 600) * 1_000_000
    end_us = (inject_unix + (600 if mode == "fault" else 0)) * 1_000_000
    process = subprocess.Popen(
        [str(binary), "--ndjson"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None
    process.stdin.write(
        json.dumps(
            {"external_case_id": external_case_id, "inject_unix": int(inject_unix), "mode": mode},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    parquet = pq.ParquetFile(trace_path)
    for batch in parquet.iter_batches(batch_size=65_536, columns=list(REQUIRED_COLUMNS)):
        starts = batch.column(batch.schema.get_field_index("startTime"))
        mask = pc.and_(pc.greater_equal(starts, start_us), pc.less(starts, end_us))
        filtered = batch.filter(mask)
        columns = filtered.to_pydict()
        for index in range(filtered.num_rows):
            record = {
                "trace_id": _text(columns["traceID"][index]),
                "span_id": _text(columns["spanID"][index]),
                "parent_span_id": _text(columns["parentSpanID"][index]),
                "service": _text(columns["serviceName"][index]),
                "operation": canonical_operation(columns["methodName"][index], columns["operationName"][index]),
                "start_unix_us": int(columns["startTime"][index]),
                "duration_us": int(columns["duration"][index]),
            }
            status = columns["statusCode"][index]
            if status is not None:
                record["status_code"] = int(status)
            process.stdin.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    process.stdin.close()
    assert process.stdout is not None and process.stderr is not None
    stdout = process.stdout.read()
    stderr = process.stderr.read()
    process.stdout.close()
    process.stderr.close()
    return_code = process.wait()
    if return_code:
        raise RuntimeError(f"offline RCA failed ({return_code}): {stderr.strip()}")
    result = json.loads(stdout)
    if result.get("protocol_version") != PROTOCOL_VERSION or result.get("external_case_id") != external_case_id:
        raise ValueError("offline RCA returned the wrong protocol or case ID")
    return result


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
