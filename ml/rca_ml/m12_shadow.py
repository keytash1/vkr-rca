"""Minimal shadow-mode HTTP API for the frozen M12 inference path."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .m10d_reranker import FORBIDDEN_INFERENCE_KEYS
from .m12_adapter import canonical_features
from .m12_evaluate import rank_candidates


def analyze(payload: dict, root: Path, baseline: dict) -> dict:
    forbidden = FORBIDDEN_INFERENCE_KEYS | {"fault_type"}
    leaked = forbidden & set(payload)
    if leaked:
        raise ValueError(f"truth fields are forbidden: {sorted(leaked)}")
    rows = canonical_features(payload["metrics"], baseline["services"], payload["candidate_services"], payload["edges"])
    ranking = rank_candidates(str(payload["incident_id"]), rows, root)["m11_top5"]
    return {
        "incident_id": payload["incident_id"],
        "candidates": [{
            "service": item["service"], "rank": item["rank"],
            "base_score": item["score"], "evidence_score": item.get("evidence_reranker_score"),
        } for item in ranking],
        "telemetry_coverage": {
            "candidate_services": len(rows),
            "services_with_metrics": sum(item["vector"]["coverage_has_metrics"] > 0 for item in rows),
            "traces": "PARTIAL",
        },
        "limitations": [
            "ranking is associative evidence, not causal verification",
            "scores are not calibrated probabilities",
            "Jaeger collection is available, but the frozen canonical path uses missing-trace semantics",
        ],
    }


def serve(root: Path, baseline_path: Path, port: int) -> None:
    baseline = json.loads(baseline_path.read_text())
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path != "/incidents/analyze":
                self.send_error(404); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                result = analyze(json.loads(self.rfile.read(length)), root, baseline)
                body, status = json.dumps(result).encode(), 200
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                body, status = json.dumps({"error": str(error)}).encode(), 400
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_):
            return
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--baseline", type=Path, default=Path("external-data/m12/runs/locked-v1/healthy/baseline.json"))
    parser.add_argument("--port", type=int, default=18120)
    args = parser.parse_args()
    serve(args.root.resolve(), args.baseline, args.port)
