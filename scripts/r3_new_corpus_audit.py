"""Bounded, label-excluding discovery audit; never imports a ranking model."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = "anon-ops/ops-lite"
REVISION = "581eba39d0bfd2d397eded6cd7cbe3303255521a"
MANIFEST_SHA = "b73137ea8daf0e86b7728250d32a48c3334a70f07a0e0028917d31c62d988a0e"
TABLES = tuple(f"{period}_{kind}.parquet" for period in ("normal", "abnormal")
               for kind in ("metrics", "metrics_sum", "metrics_histogram", "traces", "logs"))
CACHE = ROOT / "external-data/r3-openrca2-schema-v1"
OUT = ROOT / "docs/product-research/r3-new-corpus-v1"
LIMIT_FILE = 20 * 1024**2
LIMIT_TOTAL = 100 * 1024**2


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def get(url, limit):
    with urllib.request.urlopen(url, timeout=45) as response:
        if int(response.headers.get("Content-Length", 0)) > limit:
            raise ValueError("download exceeds bound")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("download exceeds bound")
    return raw


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def select_cases(raw):
    # Only these two manifest fields may influence discovery selection.
    cases = [{"name": r["name"], "system": r["system"]}
             for r in map(json.loads, raw.splitlines())]
    if len({r["name"] for r in cases}) != len(cases):
        raise ValueError("duplicate manifest case name")
    if {r["system"] for r in cases} != {"hs", "otel-demo", "ts"}:
        raise ValueError("unexpected source systems")
    if any("/" in r["name"] or "\\" in r["name"] or r["name"] in {".", ".."} for r in cases):
        raise ValueError("unsafe case path")
    selected = [min((r for r in cases if r["system"] == system),
                    key=lambda r: sha(("r3-schema-v1:" + r["name"]).encode()))
                for system in sorted({r["system"] for r in cases})]
    return cases, selected


def metric_identity_counts(rows):
    """Conflicts are retained, never resolved by choosing a value or summing."""
    groups = defaultdict(list)
    for row in rows:
        identity = tuple((k, v) for k, v in sorted(row.items()) if k != "value")
        groups[identity].append(row["value"])
    conflicted = [v for v in groups.values() if len(set(v)) > 1]
    return {"duplicate_identity_groups": sum(len(v) > 1 for v in groups.values()),
            "conflicting_identity_groups": len(conflicted),
            "rows_in_conflicting_groups": sum(map(len, conflicted))}


def acquire():
    base = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/"
    raw = get(base + "manifest.jsonl", 1024**2)
    if sha(raw) != MANIFEST_SHA:
        raise ValueError("manifest hash mismatch")
    cases, selected = select_cases(raw)
    receipt = {"repository": REPO, "revision": REVISION, "manifest_sha256": sha(raw),
               "role": "DISCOVERY_ONLY", "system_counts": dict(Counter(r["system"] for r in cases)),
               "selection": selected, "files": [], "downloaded_bytes": 0,
               "oracle_files_downloaded": [], "fits": 0, "inferences": 0, "llm_calls": 0}
    receipt_path = OUT / "acquisition.json"
    previous = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    previous_files = {r["path"]: r for r in previous.get("files", [])}
    for case in selected:
        prefix = "cases/" + case["name"] + "/"
        tree = json.loads(get(f"https://huggingface.co/api/datasets/{REPO}/tree/{REVISION}/{prefix}?limit=100", 1024**2))
        indexed = {r["path"]: r for r in tree}
        for name in TABLES:
            source = prefix + name
            item = indexed[source]
            expected = int(item["size"])
            if expected > LIMIT_FILE or receipt["downloaded_bytes"] + expected > LIMIT_TOTAL:
                raise ValueError("registered data budget exceeded")
            path = CACHE / source
            prior = previous_files.get(source)
            if path.exists():
                data = path.read_bytes()
                if not prior or sha(data) != prior["sha256"]:
                    raise ValueError("unreceipted or changed cached source")
            else:
                data = get(base + source, LIMIT_FILE)
                if len(data) != expected:
                    raise ValueError("size differs from pinned tree")
                # HF LFS digest is the raw-content SHA-256, unlike git blob oid.
                lfs = item.get("lfs", {})
                if lfs.get("oid") and sha(data) != lfs["oid"]:
                    raise ValueError("HF LFS checksum mismatch")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            receipt["downloaded_bytes"] += len(data)
            receipt["files"].append({"path": source, "system": case["system"],
                                     "bytes": len(data), "sha256": sha(data)})
            dump(receipt_path, receipt)
        print(case["system"], "downloaded", flush=True)
    print(json.dumps({"files": len(receipt["files"]), "bytes": receipt["downloaded_bytes"]}))


def audit():
    import pyarrow.parquet as pq
    receipt = json.loads((OUT / "acquisition.json").read_text())
    records = []
    for item in receipt["files"]:
        path = CACHE / item["path"]
        if sha(path.read_bytes()) != item["sha256"]:
            raise ValueError("source changed since acquisition")
        file = pq.ParquetFile(path)
        records.append({"system": item["system"], "table": path.name,
                        "rows": file.metadata.num_rows, "schema": str(file.schema_arrow),
                        "columns": file.schema_arrow.names})
    dump(OUT / "schema.json", {"source": REPO, "revision": REVISION, "role": "DISCOVERY_ONLY",
                               "tables": records})
    for record in records:
        print(record["system"], record["table"], record["rows"], record["columns"])


def semantic_audit():
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    receipt = json.loads((OUT / "acquisition.json").read_text())
    profiles = []
    interesting = {"container.cpu.usage", "container.memory.working_set", "k8s.pod.network.io",
                   "traces.span.metrics.calls", "app.frontend.requests", "hubble_http_requests_total"}
    for selected in receipt["selection"]:
        directory = CACHE / "cases" / selected["name"]
        profile = {"system": selected["system"], "periods": {}}
        for period in ("normal", "abnormal"):
            details = {"tables": {}, "metric_signals": {}}
            for kind in ("metrics", "metrics_sum", "metrics_histogram", "traces", "logs"):
                path = directory / f"{period}_{kind}.parquet"
                source = next(r for r in receipt["files"] if r["path"] == str(path.relative_to(CACHE)))
                if sha(path.read_bytes()) != source["sha256"]:
                    raise ValueError("source changed")
                # Log messages/templates/operation names are not read or exported.
                file = pq.ParquetFile(path)
                columns = [c for c in file.schema_arrow.names
                           if c not in {"message", "attr.log_template", "span_name"}]
                table = file.read(columns=columns)
                stamps = pc.cast(table["time"], "int64").to_pylist()
                content = table.drop(["time"]).to_pylist()
                rows = [dict(row, time_ns=stamp) for row, stamp in zip(content, stamps, strict=True)]
                summary = {"rows": len(rows), "time_min_ns": min(stamps), "time_max_ns": max(stamps),
                           "empty_service_rows": sum(not r.get("service_name") for r in rows),
                           "services": sorted({r["service_name"] for r in rows if r.get("service_name")}),
                           "unit_metadata_present": "unit" in columns or bool(table.schema.metadata)}
                if kind.startswith("metrics"):
                    summary["metric_names"] = sorted({r["metric"] for r in rows})
                if kind in {"metrics", "metrics_sum"}:
                    for metric in sorted(interesting & set(summary["metric_names"])):
                        subset = [r for r in rows if r["metric"] == metric]
                        values = [r["value"] for r in subset]
                        details["metric_signals"][metric] = {
                            "table": kind, "rows": len(subset),
                            "services": sorted({r["service_name"] for r in subset if r.get("service_name")}),
                            "missing_service_rows": sum(not r["service_name"] for r in subset),
                            "nonfinite_values": sum(v is None or not math.isfinite(v) for v in values),
                            **metric_identity_counts(subset),
                            "available_dimensions": [k for k in columns if k.startswith("attr.")],
                        }
                if kind == "traces":
                    by_id = defaultdict(list)
                    for row in rows:
                        by_id[(row["trace_id"], row["span_id"])].append(row)
                    summary.update({
                        "span_kinds": dict(Counter(r["attr.span_kind"] for r in rows)),
                        "statuses": dict(Counter(r["attr.status_code"] for r in rows)),
                        "duplicate_span_identity_groups": sum(len(v) > 1 for v in by_id.values()),
                        "missing_parent_nonroot": sum(bool(r["parent_span_id"]) and
                              (r["trace_id"], r["parent_span_id"]) not in by_id for r in rows),
                        "duration_field_unit": "UNDECLARED",
                        "zero_duration_spans": sum(r["duration"] == 0 for r in rows),
                        "http_5xx_without_otel_error": sum((r.get("attr.http.response.status_code") or 0) >= 500
                                      and r["attr.status_code"] != "Error" for r in rows),
                    })
                    edges = Counter()
                    for row in rows:
                        parent = by_id.get((row["trace_id"], row["parent_span_id"]), [])
                        if len(parent) == 1 and parent[0]["attr.span_kind"] == "Client" and row["attr.span_kind"] == "Server":
                            edges[(parent[0]["service_name"], row["service_name"])] += 1
                    summary["observed_client_server_edge_count"] = len(edges)
                    summary["observed_paired_server_spans"] = sum(edges.values())
                details["tables"][kind] = summary
            profile["periods"][period] = details
        normal = profile["periods"]["normal"]["tables"]
        abnormal = profile["periods"]["abnormal"]["tables"]
        last_normal = max(t["time_max_ns"] for t in normal.values())
        first_abnormal = min(t["time_min_ns"] for t in abnormal.values())
        profile["normal_precedes_abnormal"] = last_normal < first_abnormal
        profile["normal_end_to_abnormal_start_gap_ns"] = first_abnormal - last_normal
        trace_normal = set(normal["traces"]["services"])
        trace_abnormal = set(abnormal["traces"]["services"])
        profile["normal_trace_services_absent_abnormal"] = sorted(trace_normal - trace_abnormal)
        profile["abnormal_trace_services_absent_normal"] = sorted(trace_abnormal - trace_normal)
        profile["verdict"] = "ADAPTER_REQUIRED_NOT_READY_FOR_TRAINING"
        profiles.append(profile)
    dump(OUT / "semantics.json", {"role": "DISCOVERY_ONLY", "profiles": profiles,
          "no_source_rows_exported": True, "ranking_inferences": 0, "ranking_fits": 0,
          "all_other_cases_role": "UNASSIGNED", "license_redistribution": "UNRESOLVED"})
    for profile in profiles:
        print(profile["system"], "normal_precedes_abnormal", profile["normal_precedes_abnormal"])
        for period, details in profile["periods"].items():
            print(period, "trace_services", len(details["tables"]["traces"]["services"]),
                  "network", details["metric_signals"].get("k8s.pod.network.io", {}))


def overlap_audit():
    import pyarrow.parquet as pq
    receipt = json.loads((OUT / "acquisition.json").read_text())
    new_ids = set()
    for item in receipt["files"]:
        if not item["path"].endswith("_traces.parquet"):
            continue
        path = CACHE / item["path"]
        if sha(path.read_bytes()) != item["sha256"]:
            raise ValueError("source changed")
        new_ids.update(pq.read_table(path, columns=["trace_id"])["trace_id"].to_pylist())
    result = {}
    for name, relative in (
        ("M13_used_development", "external-data/m13/runs/development-v1/telemetry"),
        ("M14_used_test", "external-data/m14/runs/locked-v1/locked/telemetry"),
    ):
        paths = sorted((ROOT / relative).glob("*.json"))
        if not paths:
            raise ValueError("expected historical telemetry missing")
        ranges, old_ids = [], set()
        for path in paths:
            # No old truth, predictions, or accuracy numbers are read.
            window = json.loads(path.read_text())
            ranges.append((window["start_unix"], window["end_unix"]))
            old_ids.update(span["trace_id"] for span in window["traces"])
        result[name] = {"windows": len(paths), "min_start_unix": min(x[0] for x in ranges),
                        "max_end_unix": max(x[1] for x in ranges),
                        "trace_ids": len(old_ids), "overlap_trace_ids": len(new_ids & old_ids)}
    historical = json.loads((ROOT / "docs/product-research/r3-ml-temporal-v1/audit.json").read_text())
    seals = {}
    for part in ("frozen_seals", "protected_reports"):
        for relative, expected in historical[part].items():
            if sha((ROOT / relative).read_bytes()) != expected:
                raise ValueError("protected asset changed: " + relative)
            seals[relative] = expected
    dump(OUT / "overlap-and-protected.json", {
        "scope": "Three discovery cases versus local M13/M14 canonical snapshots only",
        "new_discovery_trace_ids": len(new_ids), "historical": result,
        "campaign_independence": "NOT_ESTABLISHED_FOR_FULL_SOURCE",
        "rcaeval_capture_overlap": "NOT_ESTABLISHED",
        "protected_assets_sha256": seals,
        "reports_and_frozen_models_unchanged": True})
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("acquire", "schema", "semantics", "overlap"))
    args = parser.parse_args()
    {"acquire": acquire, "schema": audit, "semantics": semantic_audit,
     "overlap": overlap_audit}[args.stage]()
