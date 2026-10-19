"""Offline engineering replay of exactly the stored R3-I windows and raw traces.

Never changes the registered pilot results. No new source query, incident,
model training or hidden-test claim. Reports source parsing effects separately.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT.parent / "rca-workbench"
sys.path[:0] = [str(ROOT / "ml"), str(PRODUCT / "cmd/thesis_demo"), str(ROOT / "scripts")]
from trace_adapters import TraceAccumulator, validate_canonical_spans
from rca_ml.m13_trace import canonicalize_jaeger
from rca_ml.m13_protocol import ranking_metrics, truth_rank
from profile_runtime import ProfileTransferRuntime
from r3_metric_reserve_preflight import PRIVATE, OUT as SOURCE_OUT, SERVICES, save, sha, protected

OUT = SOURCE_OUT / "wire-replay-v1"
PILOT = SOURCE_OUT / "pilot-v2"


def load(path):
    return json.loads(path.read_text())


def indexed(spans):
    return {(s["trace_id"], s["span_id"]): s for s in spans}


def run():
    original = load(PILOT / "predictions.json")
    assert len(original["truth_evaluation_only"]) == 12
    OUT.mkdir(exist_ok=False)
    reg = {"role": "ENGINEERING_DECODER_REPLAY_NOT_NEW_INCIDENTS_OR_TEST",
           "runner_sha256": sha(__file__), "trace_adapter_sha256": sha(PRODUCT / "cmd/thesis_demo/trace_adapters.py"),
           "original_results_sha256": sha(PILOT / "results.json"),
           "inputs": {name: {kind: sha(PRIVATE / name / file) for kind, file in
                      (("window", "window.json"), ("raw", "raw-traces.json"))}
                      for name in original["truth_evaluation_only"]},
           "protected_files": protected(), "ranker_fits": 0, "new_incidents": 0}
    save(OUT / "registration.json", reg)
    runtime = ProfileTransferRuntime(ROOT, PRIVATE / "baseline", SERVICES)
    repaired, details = {}, []
    for name, truth in original["truth_evaluation_only"].items():
        window = load(PRIVATE / name / "window.json")
        raw = load(PRIVATE / name / "raw-traces.json")
        assert raw["query_start"] == window["start_unix"] and raw["query_end"] == window["end_unix"]
        accumulator = TraceAccumulator()
        for trace in raw["data"]:
            accumulator.add(trace)
        spans = validate_canonical_spans(canonicalize_jaeger({"data": accumulator.data()}))
        # A later raw search is not assumed to equal the original successful
        # capture: prove equality for those windows, surface any difference.
        same = indexed(window["traces"]) == indexed(spans) if window["traces_collected"] else None
        current = copy.deepcopy(window)
        current["traces"] = spans
        current["traces_collected"] = True
        repaired[name] = runtime.rank_all(current)["frozen_m13"]
        masked = copy.deepcopy(current)
        masked["traces"] = []
        masked["traces_collected"] = False
        assert runtime.rank_all(masked)["frozen_m13"] == original["predictions"]["m13_masked"][name]
        detail = {"id": name, "original_source": load(PRIVATE / name / "source.json")["traces"],
                  "recovered_spans": len(spans), "recovered_errors": sum(s["error"] for s in spans),
                  "unchanged_successful_capture": same,
                  "original_root_rank": truth_rank(original["predictions"]["m13_full"][name], truth["root_service"]),
                  "repaired_root_rank": truth_rank(repaired[name], truth["root_service"]),
                  "masked_ranking_unchanged": True}
        details.append(detail)
        save(OUT / (name + ".json"), detail)
    protected()
    assert reg["original_results_sha256"] == sha(PILOT / "results.json")
    save(OUT / "predictions.json", repaired)
    save(OUT / "results.json", {"role": reg["role"], "cases": details,
         "all_old_successful_captures_equal": all(d["unchanged_successful_capture"] is not False for d in details),
         "restored_windows": sum(d["original_source"] != "available" and d["recovered_spans"] > 0 for d in details),
         "original_full_metrics": ranking_metrics(original["predictions"]["m13_full"], original["truth_evaluation_only"]),
         "repaired_full_metrics": ranking_metrics(repaired, original["truth_evaluation_only"]),
         "masked_rankings_unchanged": True, "original_pilot_unchanged": True,
         "protected_assets_unchanged": True, "ranker_fits": 0,
         "promotion_allowed_by_this_replay": False})
    print(json.dumps({"restored_windows": sum(d["original_source"] != "available" and d["recovered_spans"] > 0 for d in details),
                      "all_old_successful_captures_equal": all(d["unchanged_successful_capture"] is not False for d in details),
                      "ranks": [(d["id"], d["original_root_rank"], d["repaired_root_rank"]) for d in details]}), flush=True)


if __name__ == "__main__":
    run()
