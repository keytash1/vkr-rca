"""Healthy-only source gate for registered independent HTTP RED research."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT.parent / "rca-workbench"
sys.path[:0] = [str(ROOT / "ml"), str(PRODUCT / "cmd/thesis_demo")]
from live_sources import LiveProfile, collect, baseline_issues
from rca_ml.r3_red import UNITS, fit_healthy

OUT = ROOT / "docs/product-research/r3-metric-reserve-v1"
PRIVATE = ROOT / "artifacts/r3-metric-reserve-v1"
SERVICES = ("api-gateway", "customers-service", "vets-service", "visits-service")
PORTS = {"api-gateway": 18881, "customers-service": 18882,
         "visits-service": 18883, "vets-service": 18884}
PROM = "http://127.0.0.1:19992"
SCOPE = 'job="business-http-red",uri!~"/actuator.*"'
TOTAL = f'sum by(service) (rate(http_server_requests_seconds_count{{{SCOPE}}}[30s]))'
ERRORS = f'sum by(service) (rate(http_server_requests_seconds_count{{{SCOPE},status=~"5.."}}[30s]))'
QUERIES = {"request_rate": TOTAL,
           "error_ratio": f'({ERRORS} or on(service) (0 * {TOTAL})) / {TOTAL}',
           "latency_p95": 'histogram_quantile(0.95, sum by(service,le) '
                          f'(rate(http_server_requests_seconds_bucket{{{SCOPE}}}[30s])))'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def get(url, *, as_json=True):
    with urlopen(url, timeout=10) as response:
        payload = response.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("source response exceeds research budget")
    return json.loads(payload) if as_json else payload.decode()


def query(expression, start=None, end=None):
    params = {"query": expression}
    endpoint = "query"
    if start is not None:
        endpoint = "query_range"
        params |= {"start": start, "end": end, "step": 2}
    elif end is not None:
        params["time"] = end
    data = get(PROM + "/api/v1/" + endpoint + "?" + urlencode(params))
    if data.get("status") != "success" or data.get("warnings") or data.get("infos"):
        raise ValueError("Prometheus failed or returned annotations")
    return data["data"]["result"]


def red_window(start, end):
    raw = {channel: query(expression, start, end) for channel, expression in QUERIES.items()}
    records = []
    for channel, rows in raw.items():
        seen = set()
        for row in rows:
            service = row["metric"]["service"]
            if service not in SERVICES or service in seen:
                raise ValueError("unexpected or duplicate RED service")
            seen.add(service)
            for timestamp, value in row["values"]:
                number = float(value)
                records.append({"service": service, "channel": channel,
                                "unit": UNITS[channel], "timestamp": timestamp,
                                "value": number if math.isfinite(number) else None})
    raw["up"] = query('up{job="business-http-red"}', start, end)
    sources = dict.fromkeys(SERVICES, "unknown")
    for row in raw["up"]:
        service = row["metric"]["service"]
        if service not in SERVICES or sources[service] != "unknown":
            raise ValueError("unexpected or duplicate scrape service")
        sources[service] = "available" if len(row["values"]) == math.floor((end-start)/2)+1 and all(
            float(value) == 1 for _, value in row["values"]) else "unavailable"
    return records, sources, raw


def protected():
    previous = json.loads((ROOT / "docs/product-research/r3-dependency-overlap-v2/registration.json").read_text())
    files = previous["protected_files"]
    for path, expected in files.items():
        if sha(path) != expected:
            raise ValueError("protected asset changed: " + path)
    return files


def run():
    OUT.mkdir(exist_ok=False)
    PRIVATE.mkdir(parents=True, exist_ok=False)
    reg = {"role": "HEALTHY_SOURCE_GATE_ONLY", "ranking_fits": 0,
           "protocol_sha256": sha(ROOT / "docs/R3_METRIC_RESERVE_PROTOCOL.md"),
           "runner_sha256": sha(__file__), "queries": QUERIES,
           "compose_sha256": sha(ROOT / "deploy/research/red-petclinic/compose.yml"),
           "prometheus_sha256": sha(ROOT / "deploy/research/red-petclinic/prometheus.yml"),
           "protected_files": protected(), "product_head": subprocess.check_output(
               ["git", "rev-parse", "HEAD"], cwd=PRODUCT, text=True).strip()}
    save(OUT / "source-registration.json", reg)
    paths = ("/api/gateway/owners/1", "/api/vet/vets", "/api/customer/owners")
    deadline = time.monotonic() + 180
    while True:
        try:
            for path in paths:
                get("http://127.0.0.1:18881" + path)
            for service in SERVICES:
                get(f"http://127.0.0.1:{PORTS[service]}/actuator/health")
            break
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
    for service in SERVICES[1:]:
        if get(f"http://127.0.0.1:{PORTS[service]}/actuator/chaosmonkey/status") != {"enabled": False}:
            raise ValueError("fault instrument is unexpectedly enabled")
    # Remove startup effects from the 30 s lookback before measuring healthy data.
    start = int(time.time()) + 35
    end = start + 80
    print("healthy source capture", start, end, flush=True)
    while time.time() < end + 5:
        time.sleep(min(1, end + 5-time.time()))
    raw_profile = json.loads((ROOT / "deploy/acceptance/profiles/petclinic.json").read_text())
    raw_profile["id"] = "r3-metric-reserve-petclinic-v1"
    raw_profile["artifact_dir"] = str((PRIVATE / "baseline").relative_to(ROOT))
    raw_profile["metrics"]["url"] = PROM
    raw_profile["traces"]["url"] = "http://127.0.0.1:19688"
    profile_path = PRIVATE / "profile.json"
    save(profile_path, raw_profile)
    profile = LiveProfile.load(profile_path, ROOT, require_artifacts=False)
    window, source = collect(profile, start, end)
    save(PRIVATE / "healthy-window.json", window)
    save(PRIVATE / "healthy-source.json", source)
    issues = baseline_issues(profile, window, source, start, end)
    records, sources, raw = red_window(start, end)
    save(PRIVATE / "healthy-red.json", raw)
    save(PRIVATE / "healthy-red-records.json", records)
    healthy = fit_healthy(records, SERVICES)
    save(PRIVATE / "red-baseline.json", healthy)
    if set(sources.values()) != {"available"}:
        issues.append("HTTP scrape incomplete")
    for service in SERVICES:
        active = [r["value"] for r in records if r["service"] == service and r["channel"] == "request_rate"]
        if not active or min(v for v in active if v is not None) <= 0:
            issues.append(service + " is not active")
    counts = query(f'sum by(service) (http_server_requests_seconds_count{{{SCOPE}}})', end=end)
    infinity = query(f'sum by(service) (http_server_requests_seconds_bucket{{{SCOPE},le="+Inf"}})', end=end)
    mapping = lambda rows: {r["metric"]["service"]: float(r["value"][1]) for r in rows}
    if set(mapping(counts)) != set(SERVICES) or mapping(counts) != mapping(infinity):
        issues.append("counter/+Inf denominator mismatch")
    for name in ("failed", "dropped"):
        rows = query(f'sum(increase(acceptance_requests_{name}_total[80s]))', end=end)
        if len(rows) != 1 or float(rows[0]["value"][1]) != 0:
            issues.append("healthy workload " + name)
    inventory = {}
    for service in SERVICES:
        text = get(f"http://127.0.0.1:{PORTS[service]}/actuator/prometheus", as_json=False)
        with (PRIVATE / (service + "-healthy.prom")).open("x") as stream:
            stream.write(text)
        inventory[service] = [line for line in text.splitlines() if line.startswith("http_server_requests_seconds_count{")]
    protected()
    result = {"gate": not issues, "issues": issues, "source_states": sources,
              "start": start, "end": end, "span_count": len(window["traces"]),
              "resource_samples": len(window["metrics"]), "counts": mapping(counts),
              "counter_inf_equal": mapping(counts) == mapping(infinity),
              "count_inventory": inventory, "ranking_fits": 0,
              "protected_assets_unchanged": True}
    save(OUT / "source-results.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if issues:
        raise ValueError("healthy source gate failed")


if __name__ == "__main__":
    run()
