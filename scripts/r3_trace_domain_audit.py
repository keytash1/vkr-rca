"""Audit existing canonical trace roles and feature support; no fitting."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/product-research/r3-live-red-v1/trace-domain-audit.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    run = ROOT / "external-data/m13/runs/development-v1"
    manifest = json.loads((ROOT / "ml/models/m13/corpus-manifest.json").read_text())
    index = run / "telemetry-index.jsonl"
    if sha(index) != manifest["telemetry_index_sha256"]:
        raise ValueError("development source index drift")
    healthy = run / "healthy/baseline.json"
    healthy_kinds = Counter(s.get("span_kind", "MISSING") for s in json.loads(healthy.read_text())["traces"])
    kinds = Counter(); cases = []
    for line in index.read_text().splitlines():
        item = json.loads(line); path = run / item["telemetry_path"]
        if sha(path) != item["sha256"]:
            raise ValueError("development capture drift")
        payload = json.loads(path.read_text())
        counts = Counter(s.get("span_kind", "MISSING") for s in payload["traces"])
        kinds.update(counts)
        cases.append({"incident_id": item["incident_id"], "span_kinds": dict(counts)})
    cache = ROOT / "docs/product-research/r3-ml-temporal-v1/truth-free-features.json"
    rows = json.loads(cache.read_text())
    support = {}
    for feature in ("trace_error_rate_shift", "trace_exclusive_median_us_shift", "trace_downstream_wait_ratio_shift",
                    "exclusive_duration_support", "downstream_wait_support"):
        values = [r["features"][feature] for incident in rows.values() for r in incident]
        support[feature] = {"rows": len(values), "nonzero": sum(v != 0 for v in values), "minimum": min(values), "maximum": max(values)}
    live = {}
    for path in sorted((ROOT / "artifacts/r3-live-red-v1").glob("g-*/window.json")):
        payload = json.loads(path.read_text())
        live[path.parent.name] = {"span_kinds": dict(Counter(s.get("span_kind", "MISSING") for s in payload["traces"])),
            "by_service": {service: {
                "server_errors": sum(s["service"] == service and s.get("span_kind") == "SERVER" and bool(s.get("error")) for s in payload["traces"]),
                "client_errors": sum(s["service"] == service and s.get("span_kind") == "CLIENT" and bool(s.get("error")) for s in payload["traces"]),
            } for service in ("gateway", "orders", "payment")}}
    result = {"role": "USED_DEVELOPMENT_AND_CONTROLLED_PILOT_DIAGNOSTIC_NOT_CAUSAL_PROOF",
        "healthy_sha256": sha(healthy), "development_index_sha256": sha(index), "feature_cache_sha256": sha(cache),
        "healthy_span_kinds": dict(healthy_kinds), "development_span_kinds": dict(kinds), "cases": cases,
        "cached_feature_support": support, "live_pilot": live, "ranking_fits": 0,
        "limit": "Raw historical Jaeger payloads are not available here; cannot attribute UNKNOWN to upstream instrumentation versus conversion."}
    with OUT.open("x") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
    print(json.dumps({"development_cases": len(cases), "healthy_kinds": healthy_kinds,
                      "development_kinds": kinds, "support": support}, indent=2))


if __name__ == "__main__": main()
