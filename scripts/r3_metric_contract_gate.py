"""Offline C1 engineering gate. Reads existing captures, never targets/rankings.

Run once with PYTHONPATH=ml:scripts python scripts/r3_metric_contract_gate.py.
Writes exclusive receipt/features, never overwrites an earlier run.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from rca_ml import r3_metric_contract as contract

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "artifacts/r3-metric-contract-v1"
PUBLIC = ROOT / "docs/product-research/r3-metric-contract-v1"


def sha(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256")
    return digest.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read(path, ledger):
    ledger[str(path.relative_to(ROOT))] = sha(path)
    return json.loads(path.read_text())


def protected():
    # Read bytes for integrity only, not old test labels/predictions as features.
    paths = [p for folder in ("m10c-v2", "m11", "m12", "m13", "m14")
             for p in (ROOT / "ml/models" / folder).glob("*.json")]
    paths += [ROOT / "ml/rca_ml" / name for name in
              ("m9b_features.py", "m10c_features.py", "m13_features.py")]
    paths += [ROOT / "cmd/thesis_demo/live_sources.py",
              ROOT / "reports/ВКР_RCA_РЯБЕЦ_V59_ПОЛНЫЙ_С_КОММЕНТАРИЯМИ.docx"]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def verify_queries(base, kind, ledger):
    profile = read(base / "profile.json", ledger)
    queries = profile["metrics"]["queries"]
    expected = {"cpu": "sum by (service) (rca_container_cpu_cores)",
                "memory": "sum by (service) (rca_container_memory_working_set_bytes)"}
    if any(queries[k] != v for k, v in expected.items()) or profile["metrics"]["query_step_seconds"] != 2:
        raise ValueError("RESOURCE_QUERY_OR_CADENCE_CHANGED")
    if kind == "go":
        spec = read(ROOT / "deploy/acceptance/red-queries.json", ledger)
        channels = spec["channels"]
        expected_http = {
            "request_rate": "sum by (service) (rate(rca_http_server_requests_total[30s]))",
            "error_ratio": 'sum by (service) (rate(rca_http_server_requests_total{status_class="5xx"}[30s])) / sum by (service) (rate(rca_http_server_requests_total[30s]))',
            "latency_p95": "histogram_quantile(0.95, sum by (service, le) (rate(rca_http_server_request_duration_seconds_bucket[30s])))"}
        actual = {k: v["query"] for k, v in channels.items()}
        if spec["window_seconds"] != 30 or actual != expected_http:
            raise ValueError("GO_HTTP_QUERY_CHANGED")
        proof = "deploy/acceptance/red-queries.json"
    else:
        proof = "docs/product-research/r3-metric-reserve-v1/source-registration.json"
        registration = read(ROOT / proof, ledger)
        scope = 'job="business-http-red",uri!~"/actuator.*"'
        total = f'sum by(service) (rate(http_server_requests_seconds_count{{{scope}}}[30s]))'
        errors = f'sum by(service) (rate(http_server_requests_seconds_count{{{scope},status=~"5.."}}[30s]))'
        expected_http = {"request_rate": total,
                         "error_ratio": f'({errors} or on(service) (0 * {total})) / {total}',
                         "latency_p95": 'histogram_quantile(0.95, sum by(service,le) '
                                        f'(rate(http_server_requests_seconds_bucket{{{scope}}}[30s])))'}
        if registration["queries"] != expected_http:
            raise ValueError("PETCLINIC_HTTP_QUERY_CHANGED")
    return profile["candidate_services"], proof


def matrix(rows, services, start, end, step):
    """Keep service/time/value only, reject duplicate or off-grid replica series."""
    result, seen = {}, set()
    for row in rows:
        service = row["metric"]["service"]
        if service not in services or service in seen:
            raise ValueError("HTTP_INVENTORY_OR_REPLICA_AGGREGATION_INVALID")
        seen.add(service)
        for stamp, raw in row["values"]:
            stamp = contract.number(stamp)
            slot = (stamp-start)/step
            if stamp < start or stamp > end or not math.isclose(slot, round(slot), abs_tol=1e-7, rel_tol=0):
                raise ValueError("HTTP_POINT_OUTSIDE_GRID")
            key = service, stamp
            if key in result:
                raise ValueError("DUPLICATE_HTTP_POINT")
            value = float(raw)
            result[key] = value if math.isfinite(value) else None
    return result


def decode_capture(window, source, raw, services):
    """Declared source contract plus observed presence, never infer from targets."""
    if set(window["candidate_services"]) != set(services):
        raise ValueError("CAPTURE_INVENTORY_CHANGED")
    start, end, step = window["start_unix"], window["end_unix"], source["query_step_seconds"]
    if step != 2 or set(raw) != {"up", "request_rate", "error_ratio", "latency_p95"}:
        raise ValueError("CAPTURE_LAYOUT_CHANGED")
    records = []
    for row in window["metrics"]:
        if row["family"] not in {"cpu", "memory"}:
            continue  # Network/traffic proxy is deliberately not HTTP activity.
        family = row["family"]
        if row["unit"] != contract.canonical_specs()[family]["unit"]:
            raise ValueError("RESOURCE_UNIT_CHANGED")
        observed = source["metrics"] == "available"
        records.append({k: row[k] for k in ("service", "family", "timestamp")} |
                       dict(state="OBSERVED" if observed else "UNAVAILABLE",
                            value=row["value"] if observed else None))
    channels = {k: matrix(v, services, start, end, step) for k, v in raw.items()}
    if any(v not in (None, 0., 1.) for v in channels["up"].values()):
        raise ValueError("SCRAPE_PRESENCE_INVALID")
    if any(v is not None and v < 0 for v in channels["request_rate"].values()):
        raise ValueError("NEGATIVE_COMPLETED_REQUEST_RATE")
    for service in services:
        for i in range(math.floor((end-start)/step)+1):
            stamp = start+i*step
            key = service, stamp
            presence, rate = channels["up"].get(key), channels["request_rate"].get(key)
            for family, channel in (("error", "error_ratio"), ("latency", "latency_p95")):
                value = channels[channel].get(key)
                if presence == 0:
                    state = "UNAVAILABLE"
                elif presence is None or rate is None:
                    state = "MISSING"
                elif rate == 0:
                    state = "NO_ACTIVITY"
                else:
                    state = "OBSERVED" if value is not None else "MISSING"
                records.append(dict(service=service, family=family, timestamp=stamp,
                                    state=state, value=value if state == "OBSERVED" else None))
    return contract.normalize_period(start=start, end=end, step=step, services=services,
                                     specs=contract.canonical_specs(), records=records)


def capture(base, case, kind, services, ledger):
    healthy = case == "healthy"
    folder = base if healthy else base / case
    names = ("healthy-window.json", "healthy-status.json" if kind == "go" else "healthy-source.json",
             "healthy-red.json") if healthy else ("window.json", "source.json", "red.json")
    return decode_capture(*(read(folder / name, ledger) for name in names), services)


def metadata_audit():
    import pyarrow.parquet as pq  # Research env only, no new product dependency.
    audits = []
    for system in ("ob", "ss", "tt"):
        path = sorted((ROOT / "external-data/rcaeval").glob(f"re1{system}_*/metrics.parquet"))[0]
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
        metadata = {key.decode(): value.decode() for key, value in (schema.metadata or {}).items()}
        # Schema metadata is pandas column/index dtype info, not a unit declaration.
        channel_names = [name for name in schema.names if name.endswith(
            ("_cpu", "_mem", "_error", "_latency", "_latency-50", "_latency-90"))]
        audits.append(dict(system=system, path=str(path.relative_to(ROOT)), rows=parquet.metadata.num_rows,
                           column_count=len(schema.names), channel_names=channel_names,
                           schema_sha256=hashlib.sha256(schema.serialize().to_pybytes()).hexdigest(),
                           metadata_keys=sorted(metadata), metadata_sha256=contract.digest(metadata),
                           values_decoded=False, source_supported=False,
                           reason="UNIT_STATISTIC_POPULATION_AND_AGGREGATION_NOT_DECLARED"))
    return audits


def main():
    if PRIVATE.exists() or PUBLIC.exists():
        raise ValueError("RUN_ALREADY_EXISTS_DO_NOT_OVERWRITE_OR_REPEAT")
    before, ledger, summaries, outputs = protected(), {}, [], {}
    for kind, name, prefix, size in (("go", "r3-live-red-v1", "g", 6),
                                     ("petclinic", "r3-metric-reserve-v1", "p", 12)):
        base = ROOT / "artifacts" / name
        services, proof = verify_queries(base, kind, ledger)
        healthy = capture(base, "healthy", kind, services, ledger)
        ref = contract.fit_reference(healthy)
        for i in range(1, size+1):
            case = f"{prefix}-{i:03d}"
            incident = capture(base, case, kind, services, ledger)
            result = contract.extract(ref, incident)
            outputs[kind+"-"+case] = result
            summaries.append(dict(system=kind, case=case, candidate_count=len(result["rows"]),
                                  columns=len(result["columns"]),
                                  states=dict(Counter(r[3] for r in incident.records)),
                                  healthy_gap_seconds=incident.start-healthy.end,
                                  schema_sha256=result["schema_sha256"], semantic_sha256=result["semantic_sha256"],
                                  saturated_observations=result["saturated_observations"], source_proof=proof))
    audit = metadata_audit()
    if protected() != before:
        raise ValueError("PROTECTED_ASSET_CHANGED")
    if len({s["semantic_sha256"] for s in summaries}) != 1:
        raise ValueError("CROSS_SOURCE_SEMANTICS_DIFFER")
    code = [Path(__file__), ROOT / "ml/rca_ml/r3_metric_contract.py",
            ROOT / "scripts/test_r3_metric_contract.py", ROOT / "docs/R3_METRIC_CONTRACT_PROTOCOL.md"]
    receipt = dict(role="ENGINEERING_SUPPORT_GATE_USED_DEVELOPMENT", version=contract.VERSION,
                   decision="LIVE_CONTRACT_READY_TRAINING_SOURCE_NOT_SUPPORTED", next_fit="NO_FIT",
                   new_model_fits=0, predictions=0, provider_calls=0, downloads=0,
                   protected_unchanged=True, protected_files=before, input_files=ledger,
                   code_files={str(p.relative_to(ROOT)): sha(p) for p in code},
                   cases=summaries, re1_metadata_audit=audit,
                   feature_file_sha256={key: contract.digest(value) for key, value in outputs.items()},
                   feature_digest_definition="SHA256 canonical JSON, not pretty-printed file bytes",
                   disclosure="Unit semantics established for two retained instrumentations, not arbitrary Prometheus profiles. No accuracy or generalization result.")
    for key, value in outputs.items():
        save(PRIVATE / (key+".json"), value)
    save(PUBLIC / "receipt.json", receipt)
    print(json.dumps(dict(decision=receipt["decision"], cases=len(summaries),
                          candidate_rows=sum(s["candidate_count"] for s in summaries),
                          columns=28, fits=0, protected_unchanged=True)))


if __name__ == "__main__":
    main()
