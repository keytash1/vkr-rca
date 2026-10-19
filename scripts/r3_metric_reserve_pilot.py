"""One prospective Petclinic reserve pilot, without ranker fitting or tuning."""
from __future__ import annotations

import copy
import argparse
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT.parent / "rca-workbench"
sys.path[:0] = [str(ROOT / "ml"), str(PRODUCT / "cmd/thesis_demo"), str(ROOT / "scripts")]
import numpy as np
from live_sources import LiveProfile, collect
from profile_runtime import ProfileTransferRuntime
from rca_ml.m12_adapter import robust_baseline
from rca_ml.m13_features import fit_healthy_baseline
from rca_ml.m13_protocol import rank_scores, ranking_metrics, truth_rank
from rca_ml.r3_red import UNITS, evidence
from rca_ml.r3_red_reserve import reserve
from r3_metric_reserve_preflight import OUT, PRIVATE, PORTS, SERVICES, get, query, red_window, save, sha, protected

SOURCE_OUT = OUT
OUT = SOURCE_OUT / "pilot-v2"
TARGETS = ("customers-service", "visits-service", "vets-service")
DIRECT = {"customers-service": "/owners", "visits-service": "/pets/visits?petId=1", "vets-service": "/vets"}


def post(service, path, data=None):
    body = json.dumps(data or {}).encode()
    with urlopen(Request(f"http://127.0.0.1:{PORTS[service]}/actuator/chaosmonkey/" + path,
                         data=body, headers={"Content-Type": "application/json"}), timeout=10) as response:
        payload = response.read(65537)
    if len(payload) > 65536:
        raise ValueError("fault controller response too large")
    return payload.decode()


def reset():
    errors = []
    for service in TARGETS:
        try:
            post(service, "disable")
            post(service, "assaults", {"latencyActive": False, "exceptionsActive": False,
                 "killApplicationActive": False, "memoryActive": False, "cpuActive": False})
        except OSError as error:
            errors.append(service + ": " + str(error))
    if errors:
        raise OSError("; ".join(errors))


def wait_until(deadline):
    while time.time() < deadline:
        time.sleep(min(1, deadline-time.time()))


def bootstrap(challenger, control, truth):
    groups = {}
    for name, item in truth.items():
        key = (item["root_service"], item["fault_family"])
        groups.setdefault(key, []).append(name)
    delta = np.asarray([np.mean([1/truth_rank(challenger[i], truth[i]["root_service"]) -
                                1/truth_rank(control[i], truth[i]["root_service"]) for i in ids])
                        for ids in groups.values()])
    sample = np.random.default_rng(20261020).integers(0, len(delta), size=(2000, len(delta)))
    return {"delta_mrr": float(delta.mean()), "ci95": np.quantile(delta[sample].mean(axis=1), [.025, .975]).tolist(),
            "groups": len(delta), "resamples": 2000}


def old_go_diagnostic():
    old_private = ROOT / "artifacts/r3-live-red-v1"
    old_public = ROOT / "docs/product-research/r3-live-red-v1"
    load = lambda path: json.loads(path.read_text())
    baseline = load(old_private / "baseline/red-baseline.json")
    edges = load(old_private / "baseline/healthy-baseline.json")["expected_edges"]
    old = load(old_public / "predictions.json")
    predictions = {}
    for name in old["truth_evaluation_only"]:
        raw = load(old_private / name / "red.json")
        records = []
        for channel, unit in UNITS.items():
            for series in raw[channel]:
                for timestamp, value in series["values"]:
                    number = float(value)
                    records.append({"service": series["metric"]["service"], "channel": channel,
                                    "unit": unit, "timestamp": timestamp,
                                    "value": number if math.isfinite(number) else None})
        states = load(old_public / (name + ".json"))["source_states"]
        original = old["predictions"]["no_traces"]["frozen_m13"][name]
        result = reserve(original, records, baseline, tuple(sorted(baseline)), states, edges, traces_available=False)
        predictions[name] = result["ranking"]
    save(OUT / "go-development-diagnostic.json", {"role": "USED_DEVELOPMENT_NOT_TEST", "fits": 0,
         "predictions": predictions, "metrics": ranking_metrics(predictions, old["truth_evaluation_only"]),
         "no_coefficient_or_threshold_changes": True})


def run(resume=False):
    if not json.loads((SOURCE_OUT / "source-results.json").read_text())["gate"]:
        raise ValueError("source gate is not passed")
    if resume:
        if not OUT.is_dir():
            raise ValueError("no stopped pilot to resume")
    else:
        OUT.mkdir(exist_ok=False)
    cases = [{"id": f"p-{i+1:03}", "root_service": service, "fault_family": mechanism,
              "intensity": intensity, "latency_ms": (100 if intensity == "low" else 300) if mechanism == "latency" else 0,
              "level": 2 if mechanism == "exception" and intensity == "low" else 1}
             for i, (intensity, service, mechanism) in enumerate(
                 (i, s, m) for i in ("low", "high") for s in TARGETS for m in ("latency", "exception"))]
    protocol = ROOT / "docs/R3_METRIC_RESERVE_PROTOCOL.md"
    reg = {"role": "PROSPECTIVE_CONTROLLED_TRANSFER_PILOT", "cases_evaluation_only": cases,
           "protocol_sha256": sha(protocol), "runner_sha256": sha(__file__),
           "reserve_sha256": sha(ROOT / "ml/rca_ml/r3_red_reserve.py"),
           "red_sha256": sha(ROOT / "ml/rca_ml/r3_red.py"),
           "preflight_sha256": sha(ROOT / "scripts/r3_metric_reserve_preflight.py"),
           "healthy_window_sha256": sha(PRIVATE / "healthy-window.json"),
           "red_baseline_sha256": sha(PRIVATE / "red-baseline.json"),
           "protected_files": protected(), "ranker_fits": 0,
           "product_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PRODUCT, text=True).strip()}
    if resume:
        old_registration = json.loads((OUT / "fault-registration.json").read_text())
        for key in ("cases_evaluation_only", "reserve_sha256", "red_sha256", "preflight_sha256",
                    "healthy_window_sha256", "red_baseline_sha256", "protected_files", "product_head"):
            assert reg[key] == old_registration[key], "resume changes experiment inputs: " + key
        reg["original_registration_sha256"] = sha(OUT / "fault-registration.json")
        save(OUT / "resume-registration.json", reg)
    else:
        save(OUT / "fault-registration.json", reg)
        old_go_diagnostic()  # known development only, never coefficient selection
    window = json.loads((PRIVATE / "healthy-window.json").read_text())
    healthy = {"segments": [{"start_unix": window["start_unix"], "end_unix": window["end_unix"],
                             "requests_per_second": window["requests_per_second"]}],
               "metrics": window["metrics"], "traces": window["traces"]}
    baseline = fit_healthy_baseline(healthy, SERVICES)
    if any(e["source"] not in SERVICES or e["target"] not in SERVICES for e in baseline["expected_edges"]):
        raise ValueError("healthy topology contains unmapped services")
    for path, value in ((PRIVATE / "baseline/healthy-baseline.json", baseline),
                        (PRIVATE / "baseline/legacy-metric-baseline.json", robust_baseline(window["metrics"]))):
        if path.exists():
            assert json.loads(path.read_text()) == value, "reused healthy derivation differs"
        else:
            save(path, value)
    red_baseline = json.loads((PRIVATE / "red-baseline.json").read_text())
    runtime = ProfileTransferRuntime(ROOT, PRIVATE / "baseline", SERVICES)
    profile = LiveProfile.load(PRIVATE / "profile.json", ROOT)
    topology = {"edges": baseline["expected_edges"], "windows": baseline["windows"]}
    if resume:
        assert json.loads((OUT / "healthy-topology.json").read_text()) == topology
    else:
        save(OUT / "healthy-topology.json", topology)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("25 min pilot deadline")))
    signal.alarm(1500)
    predictions = {v: {} for v in ("m13_full", "m13_masked", "red_only", "reserve_masked")}
    truths, results = {}, []
    completed = set()
    if resume:
        # Completed captures/predictions/oracles are immutable; never repeat p-001.
        for case in cases:
            name = case["id"]
            oracle_path = OUT / (name + "-oracle.json")
            prediction_path = OUT / (name + "-predictions.json")
            if oracle_path.exists() != prediction_path.exists():
                raise ValueError("partial case cannot be silently repeated")
            if not oracle_path.exists():
                continue
            detail = json.loads(oracle_path.read_text())
            assert detail["case_evaluation_only"] == case
            methods = json.loads(prediction_path.read_text())["methods"]
            for method, ranking in methods.items():
                predictions[method][name] = ranking
            truths[name] = {"root_service": case["root_service"], "fault_family": case["fault_family"],
                            "intensity": case["intensity"], "system": "Petclinic-R3-I"}
            results.append(detail)
            completed.add(name)
        assert completed == {"p-001"}, "only registered technical stop may resume"
    try:
        reset()
        for service in TARGETS:
            post(service, "watchers", {"controller": False, "restController": True,
                 "service": False, "repository": False, "component": False})
            status = get(f"http://127.0.0.1:{PORTS[service]}/actuator/chaosmonkey/status")
            if status.get("enabled") is not False:
                raise ValueError("fault reset not confirmed")
        for case in cases:
            if case["id"] in completed:
                continue
            reset()
            service, mechanism, name = case["root_service"], case["fault_family"], case["id"]
            post(service, "assaults", {"level": case["level"], "deterministic": True, "latencyActive": mechanism == "latency",
                 "latencyRangeStart": case["latency_ms"] or 100, "latencyRangeEnd": case["latency_ms"] or 100,
                 "exceptionsActive": mechanism == "exception", "killApplicationActive": False,
                 "memoryActive": False, "cpuActive": False})
            post(service, "enable")
            if get(f"http://127.0.0.1:{PORTS[service]}/actuator/chaosmonkey/status").get("enabled") is not True:
                raise ValueError("fault enable not confirmed")
            start = int(time.time())+35
            end = start+35
            print(name, service, mechanism, case["intensity"], "measure", start, end, flush=True)
            wait_until(end+5)
            current, source = collect(profile, start, end)
            records, sources, raw = red_window(start, end)
            save(PRIVATE / name / "window.json", current)
            save(PRIVATE / name / "source.json", source)
            save(PRIVATE / name / "red.json", raw)
            save(PRIVATE / name / "red-records.json", records)
            # All predictions fixed before oracle requests and truth joins.
            full = runtime.rank_all(current)["frozen_m13"]
            masked = copy.deepcopy(current)
            masked["traces"] = []
            masked["traces_collected"] = False
            original = runtime.rank_all(masked)["frozen_m13"]
            red = evidence(records, red_baseline, SERVICES, sources)
            candidate = reserve(original, records, red_baseline, SERVICES, sources,
                                baseline["expected_edges"], traces_available=False)
            unchanged = reserve(full, records, red_baseline, SERVICES, sources,
                                baseline["expected_edges"], traces_available=True)
            assert unchanged["ranking"] == full and not unchanged["applied"]
            methods = {"m13_full": full, "m13_masked": original,
                       "red_only": rank_scores(red["scores"]), "reserve_masked": candidate["ranking"]}
            save(OUT / (name + "-predictions.json"), {"methods": methods, "reserve": candidate,
                                                       "full_trace_unchanged": True})
            statuses, elapsed = [], []
            for _ in range(10):
                began = time.monotonic()
                try:
                    with urlopen(f"http://127.0.0.1:{PORTS[service]}" + DIRECT[service], timeout=5) as response:
                        code = response.status
                        response.read(1024 * 1024)
                except HTTPError as error:
                    code = error.code
                    error.close()
                statuses.append(code)
                elapsed.append(time.monotonic()-began)
            channel = "latency_p95" if mechanism == "latency" else "error_ratio"
            root_values = [r["value"] for r in records if r["service"] == service and r["channel"] == channel and r["value"] is not None]
            root_observation = float(np.median(root_values)) if root_values else None
            if mechanism == "latency":
                effect = all(code == 200 for code in statuses) and np.median(elapsed) >= .8*case["latency_ms"]/1000 and root_observation is not None and root_observation >= (.07 if case["intensity"] == "low" else .24)
            else:
                failed = sum(500 <= code <= 599 for code in statuses)
                effect = failed >= (1 if case["level"] == 2 else 8) and root_observation is not None and root_observation >= (.1 if case["level"] == 2 else .7)
            valid = bool(effect and set(sources.values()) == {"available"} and source["traces"] == "available" and current["traces"])
            truths[name] = {"root_service": service, "fault_family": mechanism, "intensity": case["intensity"], "system": "Petclinic-R3-I"}
            detail = {"case_evaluation_only": case, "valid": valid, "statuses": statuses,
                      "median_elapsed_seconds": float(np.median(elapsed)), "target_observation": root_observation,
                      "sources": sources, "spans": len(current["traces"]), "reserve_applied": candidate["applied"],
                      "root_ranks": {method: truth_rank(ranking, service) for method, ranking in methods.items()}}
            save(OUT / (name + "-oracle.json"), detail)
            results.append(detail)
            for method, ranking in methods.items():
                predictions[method][name] = ranking
            print(name, "valid", valid, detail["root_ranks"], flush=True)
        reset()
        protected()
        assert reg["protocol_sha256"] == sha(protocol)
        assert reg["reserve_sha256"] == sha(ROOT / "ml/rca_ml/r3_red_reserve.py")
        assert reg["runner_sha256"] == sha(__file__)
        metrics = {method: ranking_metrics(rows, truths) for method, rows in predictions.items()}
        comparisons = {control: bootstrap(predictions["reserve_masked"], predictions[control], truths)
                       for control in ("m13_masked", "red_only")}
        guards = {"all_valid": all(r["valid"] for r in results),
                  "full_trace_unchanged": True, "protected_assets_unchanged": True,
                  "mrr_and_ci_vs_both": all(v["delta_mrr"] >= .03 and v["ci95"][0] > 0 for v in comparisons.values()),
                  "ac3_noninferior": all(metrics["reserve_masked"]["ac_at_3"] >= metrics[c]["ac_at_3"] for c in comparisons)}
        save(OUT / "predictions.json", {"truth_evaluation_only": truths, "predictions": predictions})
        save(OUT / "results.json", {"role": "SMALL_CONTROLLED_PROSPECTIVE_PILOT_NOT_UNIVERSAL_ACCURACY",
             "valid_cases": sum(r["valid"] for r in results), "total_cases": len(results),
             "metrics_all_registered_cases": metrics, "comparisons": comparisons, "guards": guards,
             "verdict": "SIGNAL_FOR_LIMITED_INTEGRATION" if all(guards.values()) else "NOT_PROMOTED",
             "ranker_fits": 0})
        print("pilot completed", guards, flush=True)
    finally:
        signal.alarm(0)
        reset()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    run(parser.parse_args().resume)
