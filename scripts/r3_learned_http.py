"""One bounded Go training capture and one fixed Petclinic transfer screen."""
from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import json
import math
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "scripts"), str(ROOT / "cmd/thesis_demo")]
import numpy as np
import xgboost as xgb
from rca_ml import r3_metric_contract as c
from rca_ml.m13_protocol import ranking_metrics, rank_scores, truth_rank
from rca_ml.m13_features import fit_healthy_baseline
from rca_ml.m12_adapter import robust_baseline
from live_sources import LiveProfile, collect, baseline_issues
from profile_runtime import ProfileTransferRuntime
from r3_live_red import SERVICES, PORTS, PATHS, DOCKER, http, query, red_window, reset, wait_until
from r3_metric_contract_gate import capture, decode_capture, protected, read, save, sha, verify_queries

PRIVATE = ROOT / "artifacts/r3-learned-http-v1"
PUBLIC = ROOT / "docs/product-research/r3-learned-http-v1"
PROTOCOL = PUBLIC / "protocol.json"


def planned_cases():
    cases = [dict(service=s, family=f, intensity=i, value=v)
             for s in SERVICES for f, values in (("latency", (100, 300)), ("error", (.5, 1.)))
             for i, v in enumerate(values)]
    random.Random(20261020).shuffle(cases)
    return [dict(id=f"train-{i+1:03d}", **case) for i, case in enumerate(cases)]


def matrix(features):
    if features["columns"] != list(c.COLUMNS) or features["schema_sha256"] != c.schema_digest():
        raise ValueError("SCHEMA_CHANGED")
    if features["semantic_sha256"] != c.validate_specs(c.canonical_specs()):
        raise ValueError("SEMANTICS_CHANGED")
    rows = features["rows"]
    if not rows or len({r["service"] for r in rows}) != len(rows):
        raise ValueError("CANDIDATE_INVENTORY_INVALID")
    values = np.asarray([r["vector"] for r in rows], dtype=np.float32)
    if values.shape != (len(rows), 28) or not np.isfinite(values).all():
        raise ValueError("NUMERIC_MATRIX_INVALID")
    return values


def red_ranking(features):
    matrix(features)
    indexes = [c.COLUMNS.index(f"{f}_signed_median_shift") for f in ("error", "latency")]
    return rank_scores({r["service"]: max(0., *(r["vector"][i] for i in indexes))
                        for r in features["rows"]})


def predict(model, features):
    values = model.predict(xgb.DMatrix(matrix(features), feature_names=list(c.COLUMNS)))
    return rank_scores({r["service"]: float(v) for r, v in zip(features["rows"], values, strict=True)})


def mask_cpu(period):
    return replace(period, records=tuple((r[0], r[1], r[2], "MISSING", None) if r[1] == "cpu" else r
                                        for r in period.records))


def fit_once(features, truths, protocol):
    matrices, targets, groups = [], [], []
    if len(features) != protocol["training"]["cases"] or set(features) != set(truths):
        raise ValueError("TRAINING_DENOMINATOR_INCOMPLETE")
    for case, payload in sorted(features.items()):
        data = matrix(payload)
        labels = [int(r["service"] == truths[case]["root_service"]) for r in payload["rows"]]
        if sum(labels) != 1:
            raise ValueError("ONE_CONFIRMED_ROOT_PER_INCIDENT_REQUIRED")
        matrices.append(data); targets.extend(labels); groups.append(len(labels))
    data = xgb.DMatrix(np.concatenate(matrices), label=np.asarray(targets), feature_names=list(c.COLUMNS))
    data.set_group(np.asarray(groups))
    parameters = dict(protocol["model"])
    rounds = parameters.pop("rounds")
    # Reserve before xgb.train; a failed fit must not be silently repeated.
    save(PUBLIC / "fit-reservation.json", dict(maximum_fits=1, attempts=1, rounds=rounds,
          training_feature_sha256=c.digest(features), training_labels_sha256=c.digest(truths),
          runner_sha256=sha(Path(__file__)), protocol_sha256=sha(PROTOCOL)))
    return xgb.train(parameters, data, num_boost_round=rounds, verbose_eval=False)


def collect_training():
    if PRIVATE.exists() or (PUBLIC / "registration.json").exists():
        raise ValueError("EXISTING_CAPTURE_DO_NOT_REPEAT")
    protocol = json.loads(PROTOCOL.read_text())
    before = protected()
    # Only the teaching project may be started/stopped; product is a different project.
    running = subprocess.check_output(DOCKER + ["ps", "--status", "running", "--quiet"], text=True).strip()
    if running:
        raise ValueError("TEACHING_PROJECT_ALREADY_RUNNING_DO_NOT_TAKE_OWNERSHIP")
    registration = dict(protocol_sha256=sha(PROTOCOL), runner_sha256=sha(Path(__file__)),
                        transform_sha256=sha(ROOT / "ml/rca_ml/r3_metric_contract.py"),
                        decoder_sha256=sha(ROOT / "scripts/r3_metric_contract_gate.py"),
                        query_sha256=sha(ROOT / "deploy/acceptance/red-queries.json"),
                        compose_sha256=sha(ROOT / "deploy/acceptance/compose.yml"),
                        planned_cases_evaluation_only=planned_cases(), protected_files=before,
                        code_head=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    registration["training_image_ids"] = subprocess.check_output(
        DOCKER[:3] + ["image", "inspect", *(f"vkr-rca-{s}:latest" for s in SERVICES),
                      "vkr-rca/resource-exporter:acceptance-v1", "--format", "{{.Id}}"], text=True).splitlines()
    save(PUBLIC / "registration.json", registration)
    PRIVATE.mkdir(parents=True)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("collection budget exceeded")))
    signal.alarm(protocol["safety"]["maximum_collection_wall_seconds"])
    started = False
    try:
        started = True
        subprocess.run(DOCKER + ["up", "-d", "--no-build", "--pull", "never"], check=True, timeout=90)
        print("teaching project started; waiting for sources", flush=True)
        for _ in range(45):
            try:
                if all(http(f"http://127.0.0.1:{PORTS[s]}/health")["status"] == "ok" for s in SERVICES):
                    query("up"); break
            except (OSError, KeyError, ValueError):
                pass
            wait_until(time.time()+2)
        else:
            raise ValueError("SOURCE_BOOT_FAILED")
        raw_profile = json.loads((ROOT / "deploy/acceptance/profiles/local-three.json").read_text())
        raw_profile.update(id="r3-learned-http-v1", artifact_dir="artifacts/r3-learned-http-v1/baseline")
        save(PRIVATE / "profile.json", raw_profile)
        verify_queries(PRIVATE, "go", {})
        profile = LiveProfile.load(PRIVATE / "profile.json", ROOT, require_artifacts=False)
        reset()
        wait_until(time.time()+35)
        start = int(time.time())+2; end = start+60
        print("healthy", start, end, flush=True); wait_until(end+4)
        window, source = collect(profile, start, end)
        _, _, raw = red_window(start, end)
        save(PRIVATE / "healthy-window.json", window); save(PRIVATE / "healthy-status.json", source)
        save(PRIVATE / "healthy-red.json", raw)
        issues = baseline_issues(profile, window, source, start, end)
        if issues:
            raise ValueError("HEALTHY_SOURCE_INVALID:" + str(issues))
        healthy = decode_capture(window, source, raw, SERVICES)
        reference = c.fit_reference(healthy)
        if any(f == "error" and value != 0 for _, f, _, state, value in healthy.records if state == "OBSERVED"):
            raise ValueError("HEALTHY_HAS_5XX")
        totals = query("sum by(service) (rca_http_server_requests_total)", end=end)
        counts = query("rca_http_server_request_duration_seconds_count", end=end)
        infinity = query('rca_http_server_request_duration_seconds_bucket{le="+Inf"}', end=end)
        def by_service(rows):
            values = {r["metric"]["service"]: float(r["value"][1]) for r in rows}
            if len(values) != len(rows) or set(values) != set(SERVICES):
                raise ValueError("DENOMINATOR_INVENTORY_INVALID")
            return values
        if not by_service(totals) == by_service(counts) == by_service(infinity):
            raise ValueError("HTTP_COUNTER_HISTOGRAM_DENOMINATOR_DIFFERS")
        save(PUBLIC / "healthy-gate.json", dict(ready=True, schema_sha256=c.schema_digest(),
                                               semantic_sha256=healthy.semantic_sha256,
                                               counter_histogram_denominator_equal=True))
        features, truths = {}, {}
        for index, case in enumerate(planned_cases()):
            reset()
            if index:
                wait_until(time.time()+35)
            control = dict(latency_ms=case["value"] if case["family"] == "latency" else 0,
                           error_rate=case["value"] if case["family"] == "error" else 0)
            configured = http(f"http://127.0.0.1:{PORTS[case['service']]}/debug/fault", control)
            if configured != control:
                raise ValueError("FAULT_CONFIG_READBACK_MISMATCH")
            start = int(time.time())+35; end = start+20
            print(case["id"], case["service"], case["family"], case["value"], "capture", start, end, flush=True)
            wait_until(end+4)
            window, source = collect(profile, start, end)
            _, _, raw = red_window(start, end)
            folder = PRIVATE / case["id"]
            save(folder / "window.json", window); save(folder / "source.json", source); save(folder / "red.json", raw)
            period = decode_capture(window, source, raw, SERVICES)
            payload = c.extract(reference, period)
            save(folder / "features.json", payload)  # Persist numeric inputs before oracle join.
            began = time.monotonic()
            try:
                with urlopen(f"http://127.0.0.1:{PORTS[case['service']]}{PATHS[case['service']]}", timeout=4) as response:
                    code = response.status; response.read(1024*1024)
            except HTTPError as error:
                code = error.code; error.close()
            elapsed = time.monotonic()-began
            family = "latency" if case["family"] == "latency" else "error"
            observed = [v for s, f, _, state, v in period.records
                        if s == case["service"] and f == family and state == "OBSERVED"]
            effect = (observed and np.median(observed) >= case["value"]/1000*.7 and
                      code == 200 and elapsed >= case["value"]/1000*.8) if family == "latency" else (
                          observed and np.median(observed) >= case["value"]*.5)
            valid = bool(effect) and source["metrics"] == "available" and source["traces"] == "available" and bool(window["traces"])
            valid &= all(state not in {"MISSING", "UNAVAILABLE"} for _, _, _, state, _ in period.records)
            save(PUBLIC / (case["id"]+"-oracle.json"), dict(case=case, valid=bool(valid),
                                                          direct_code=code, direct_seconds=elapsed))
            if not valid:
                raise ValueError("CASE_ORACLE_OR_SOURCE_INVALID:" + case["id"])
            features[case["id"]] = payload
            truths[case["id"]] = dict(root_service=case["service"], fault_family=case["family"])
            if sum(p.stat().st_size for p in PRIVATE.rglob("*.json")) > 100*1024**2:
                raise ValueError("RAW_BUDGET_EXCEEDED")
        save(PRIVATE / "training-features.json", features)
        save(PRIVATE / "training-labels.json", truths)
        if protected() != before:
            raise ValueError("PROTECTED_CHANGED")
        save(PUBLIC / "collection.json", dict(valid_cases=12, fit_allowed=True, protected_unchanged=True))
        print("training collection complete: 12 valid cases, no fit yet", flush=True)
    except BaseException as error:
        save(PUBLIC / "collection-stopped.json", dict(decision="NO_FIT", reason=str(error)))
        raise
    finally:
        signal.alarm(0)
        if started:
            try:
                reset()
            finally:
                subprocess.run(DOCKER + ["stop"], check=True, timeout=60)


def evaluate():
    protocol = json.loads(PROTOCOL.read_text())
    if not json.loads((PUBLIC / "collection.json").read_text())["fit_allowed"]:
        raise ValueError("NO_COMPLETE_TRAINING")
    if (PUBLIC / "fit-reservation.json").exists():
        raise ValueError("FIT_ALREADY_RESERVED_NO_REPEAT")
    before = protected()
    features = json.loads((PRIVATE / "training-features.json").read_text())
    truths = json.loads((PRIVATE / "training-labels.json").read_text())
    model = fit_once(features, truths, protocol)
    model.save_model(PRIVATE / "challenger.json")
    base = ROOT / "artifacts/r3-metric-reserve-v1"
    ledger = {}
    services, _ = verify_queries(base, "petclinic", ledger)
    healthy = capture(base, "healthy", "petclinic", services, ledger)
    reference = c.fit_reference(healthy)
    window = read(base / "healthy-window.json", ledger)
    legacy = {"segments": [dict(start_unix=window["start_unix"], end_unix=window["end_unix"],
                                requests_per_second=window["requests_per_second"])],
              "metrics": window["metrics"], "traces": window["traces"]}
    baseline = PRIVATE / "petclinic-baseline"
    save(baseline / "healthy-baseline.json", fit_healthy_baseline(legacy, services))
    save(baseline / "legacy-metric-baseline.json", robust_baseline(window["metrics"]))
    runtime = ProfileTransferRuntime(ROOT, baseline, tuple(sorted(services)))
    predictions = {mode: {name: {} for name in ("learned", "red", "champion")}
                   for mode in ("no_traces", "no_traces_missing_cpu")}
    for i in range(1, 13):
        case = f"p-{i:03d}"
        period = capture(base, case, "petclinic", services, ledger)
        payload = read(base / case / "window.json", ledger)
        for mode in predictions:
            p = mask_cpu(period) if mode.endswith("missing_cpu") else period
            frame = c.extract(reference, p)
            predictions[mode]["learned"][case] = predict(model, frame)
            predictions[mode]["red"][case] = red_ranking(frame)
            raw = copy.deepcopy(payload)
            raw.update(traces=[], traces_collected=False)
            if mode.endswith("missing_cpu"):
                raw["metrics"] = [r for r in raw["metrics"] if r["family"] != "cpu"]
            predictions[mode]["champion"][case] = runtime.rank_all(raw)["frozen_m13"]
    save(PUBLIC / "transfer-predictions.json", dict(predictions=predictions, input_sha256=ledger,
                                                  model_sha256=sha(PRIVATE / "challenger.json")))
    # Only after all transfer rankings are persisted may labels be opened.
    labels = json.loads((ROOT / "docs/product-research/r3-metric-reserve-v1/pilot-v2/predictions.json").read_text())
    # Historical file layout is explicit and checked before scoring.
    truth = labels["truth_evaluation_only"]
    if set(truth) != set(predictions["no_traces"]["learned"]):
        raise ValueError("TRANSFER_LABEL_DENOMINATOR_MISMATCH")
    metrics = {mode: {method: ranking_metrics(values, truth) for method, values in methods.items()}
               for mode, methods in predictions.items()}
    gates = {}
    for control in ("red", "champion"):
        a, b = metrics["no_traces"]["learned"], metrics["no_traces"][control]
        deltas = [1/truth_rank(predictions["no_traces"]["learned"][case], truth[case]["root_service"])
                  - 1/truth_rank(predictions["no_traces"][control][case], truth[case]["root_service"]) for case in truth]
        gates[control] = dict(delta_mrr=a["mrr"]-b["mrr"],
                              net_case_wins=sum(v > 1e-9 for v in deltas)-sum(v < -1e-9 for v in deltas),
                              top1_not_lower=a["ac_at_1"] >= b["ac_at_1"],
                              missing_cpu_not_lower=metrics["no_traces_missing_cpu"]["learned"]["mrr"] >=
                                                    metrics["no_traces_missing_cpu"][control]["mrr"])
    passed = all(v["delta_mrr"] >= .05 and v["net_case_wins"] >= 2 and v["top1_not_lower"] and
                 v["missing_cpu_not_lower"] for v in gates.values())
    if protected() != before:
        raise ValueError("PROTECTED_CHANGED")
    save(PUBLIC / "result.json", dict(role=protocol["role"], fit_attempts=1, training_cases=12,
                                      transfer_cases=12, metrics=metrics, gates=gates,
                                      decision="REGISTER_FRESH_C3" if passed else "KEEP_CHAMPION_STOP_THIS_BRANCH",
                                      promotion_allowed=False, protected_unchanged=True))
    print(json.dumps(dict(metrics=metrics, gates=gates, passed=passed)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("collect", "evaluate"))
    args = parser.parse_args()
    collect_training() if args.phase == "collect" else evaluate()
