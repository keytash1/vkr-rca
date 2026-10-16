"""Read-only HTTP application for profile-based incident analysis.

Saved incidents are an optional research replay mode. The ordinary application
collects observations for a configured system and interval; it never retrains
or changes the sealed model.
"""

from __future__ import annotations

import argparse
import ipaddress
from collections import defaultdict
import hashlib
import json
import math
import mimetypes
from statistics import median
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from live_sources import LiveProfile, collect
from profile_runtime import ProfileTransferRuntime
from rca_ml.m13_features import build_candidate_rows
from rca_ml.m13_runtime import M13Runtime
from rca_ml.m14_runtime import FrozenM13TransferRuntime


FORBIDDEN_INPUT = frozenset({
    "root", "root_service", "ground_truth", "truth", "label", "fault", "fault_type",
    "fault_family", "dataset", "system", "workload_result", "expected_top1",
})
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
MAX_BROWSER_DATE_UNIX = 8_640_000_000_000


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class DiagnosticApplication:
    def __init__(self, root: Path, profiles_dir: Path | None = None):
        self.root = root.resolve()
        profiles_dir = profiles_dir or self.root / "deploy/profiles"
        self.profiles = {}
        for path in sorted(profiles_dir.glob("*.json")):
            profile = LiveProfile.load(path, self.root)
            if profile.id in self.profiles:
                raise ValueError(f"duplicate telemetry profile: {profile.id}")
            self.profiles[profile.id] = profile
        self.profile_runtimes = {
            profile_id: ProfileTransferRuntime(self.root, profile.artifact_dir, profile.services)
            for profile_id, profile in self.profiles.items()
        }
        self.run_dir = self.root / "external-data/m14/runs/locked-v1"
        self.static_dir = Path(__file__).resolve().parent / "static"
        evaluation_path = self.root / "ml/models/m14/evaluation.json"
        self.evaluation = json.loads(evaluation_path.read_text()) if evaluation_path.is_file() else None
        replay_files = (
            self.root / "ml/models/m14/healthy-baseline.json",
            self.root / "ml/models/m14/legacy-metric-baseline.json",
            self.root / "deploy/m14/config.json",
        )
        self.runtime = FrozenM13TransferRuntime(self.root) if all(p.is_file() for p in replay_files) else None
        if not self.profile_runtimes and self.runtime is None:
            raise ValueError("no installed system profile or replay runtime")
        index_path = self.run_dir / "locked/telemetry-index.jsonl"
        self.examples = {}
        if self.runtime is not None and index_path.is_file():
            for line in index_path.read_text().splitlines():
                if not line:
                    continue
                entry = json.loads(line)
                case_id = entry["incident_id"]
                if not isinstance(case_id, str) or not case_id.startswith("m14-") or case_id in self.examples:
                    raise ValueError("invalid example index")
                relative = Path(entry["telemetry_path"])
                path = (self.run_dir / relative).resolve()
                if not path.is_relative_to(self.run_dir) or not path.is_file():
                    raise ValueError("example telemetry is missing or outside run directory")
                self.examples[case_id] = (path, entry["sha256"])

    def example(self, case_id: str) -> dict:
        if case_id not in self.examples:
            raise ValueError("unknown incident")
        path, expected_hash = self.examples[case_id]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError("incident data checksum mismatch")
        return json.loads(data)

    def analyze(self, incident: dict, runtime: FrozenM13TransferRuntime | None = None) -> dict:
        runtime = runtime or self.runtime
        if runtime is None:
            raise ValueError("replay mode is not installed")
        if not isinstance(incident, dict):
            raise ValueError("diagnostic window must be an object")
        forbidden = FORBIDDEN_INPUT.intersection(incident)
        if forbidden:
            raise ValueError("diagnostic window contains evaluation labels or identifiers")
        expected = tuple(runtime.services)
        if tuple(incident.get("candidate_services", ())) != expected:
            raise ValueError("candidate services do not match the configured system")
        start = incident.get("start_unix")
        end = incident.get("end_unix")
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or abs(start) > MAX_BROWSER_DATE_UNIX
                or abs(end) > MAX_BROWSER_DATE_UNIX
                or end <= start):
            raise ValueError("diagnostic window has invalid time boundaries")
        clean = dict(incident)
        ranked = runtime.rank_all(clean)["frozen_m13"]
        rows = build_candidate_rows(clean, runtime.baseline, expected)
        by_service = {row["service"]: row["features"] for row in rows}
        observations = self._observation_summary(clean, expected)
        candidates = [
            M13Runtime._evidence(item, by_service[item["service"]])
            | {"observations": observations[item["service"]]}
            for item in ranked
        ]
        if len(candidates) != len(expected):
            raise RuntimeError("incomplete candidate ranking")
        return {
            "incident_id": str(incident.get("incident_id", "uploaded-window")),
            "start_unix": start,
            "end_unix": end,
            "method": "Диагностическое ранжирование сервисов",
            "model_version": runtime.freeze["version"],
            "model_count": len(runtime.models),
            "candidate_count": len(candidates),
            "causal_status": "DIAGNOSTIC_RANKING_ONLY",
            "candidates": candidates,
        }

    @staticmethod
    def _observation_summary(incident: dict, services: tuple[str, ...]) -> dict:
        """Small, checkable source summaries; never interpreted as model weights."""
        metrics = defaultdict(lambda: defaultdict(list))
        units = {}
        for item in incident["metrics"]:
            service = item["service"]
            if service in services:
                family = item["family"]
                value = float(item["value"])
                if math.isfinite(value):
                    metrics[service][family].append(value)
                    units[(service, family)] = item["unit"]
        spans = {service: {"count": 0, "errors": 0} for service in services}
        for span in incident["traces"]:
            service = span.get("service")
            if service in spans:
                spans[service]["count"] += 1
                spans[service]["errors"] += int(bool(span.get("error", False)))
        return {
            service: {
                "metrics": {
                    family: {
                        "samples": len(values), "min": min(values),
                        "median": median(values), "max": max(values),
                        "unit": units[(service, family)],
                    }
                    for family, values in sorted(metrics[service].items())
                },
                "traces": spans[service],
            }
            for service in services
        }

    def analyze_live(self, profile_id: str, start: float, end: float) -> dict:
        profile = self.profiles.get(profile_id)
        if profile is None:
            raise ValueError("unknown telemetry profile")
        window, source_status = collect(profile, start, end)
        runtime = self.profile_runtimes[profile_id]
        result = self.analyze(window, runtime)
        result.update({"profile_id": profile.id, "profile_version": profile.version, "source_status": source_status})
        return result

    def public_results(self) -> dict:
        if self.evaluation is None or self.runtime is None:
            raise ValueError("independent experiment is not installed")
        pooled = self.evaluation["pooled"]
        return {
            "system": "OpenTelemetry Astronomy Shop",
            "incidents": 50,
            "candidate_count": len(self.runtime.services),
            "method": pooled["frozen_m13"],
            "metric_comparator": pooled["metric_heuristic"],
            "limitations": [
                "Оценка относится к одной контролируемой системе и пяти видам отказа.",
                "Балл задаёт порядок проверки, но не вероятность и не доказательство причины.",
                "Пороги точности для первых трёх и пяти позиций не достигнуты.",
            ],
        }


def make_handler(app: DiagnosticApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RCADiagnostics/1.0"

        def _json(self, code: HTTPStatus, value: object):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/health":
                runtime = next(iter(app.profile_runtimes.values()), app.runtime)
                return self._json(HTTPStatus.OK, {
                    "status": "model_loaded", "sources": "not_checked",
                    "model_count": len(runtime.models),
                    "profiles": len(app.profiles), "examples": len(app.examples),
                    "experiment_available": app.evaluation is not None and app.runtime is not None,
                })
            if path == "/api/examples":
                return self._json(HTTPStatus.OK, [{"id": key, "title": f"Инцидент {n:02d}"} for n, key in enumerate(app.examples, 1)])
            if path == "/api/profiles":
                return self._json(HTTPStatus.OK, [
                    {"id": profile.id, "title": profile.title, "version": profile.version,
                     "candidate_count": len(profile.services)}
                    for profile in app.profiles.values()
                ])
            if path == "/api/results":
                if app.evaluation is None or app.runtime is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "independent experiment is not installed"})
                return self._json(HTTPStatus.OK, app.public_results())
            file_name = "index.html" if path == "/" else path.removeprefix("/")
            target = (app.static_dir / file_name).resolve()
            if not target.is_relative_to(app.static_dir) or not target.is_file():
                return self.send_error(HTTPStatus.NOT_FOUND)
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if urlsplit(self.path).path != "/api/analyze":
                return self.send_error(HTTPStatus.NOT_FOUND)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_UPLOAD_BYTES:
                    raise ValueError("invalid or oversized request")
                payload = json.loads(self.rfile.read(length))
                if set(payload) == {"example_id"}:
                    source = app.example(payload["example_id"])
                    source = {key: value for key, value in source.items() if key != "workload_result"}
                elif set(payload) == {"incident"}:
                    source = payload["incident"]
                elif set(payload) == {"profile_id", "start_unix", "end_unix"}:
                    return self._json(HTTPStatus.OK, app.analyze_live(
                        payload["profile_id"], payload["start_unix"], payload["end_unix"]
                    ))
                else:
                    raise ValueError("select a system and interval, or use the replay mode")
                return self._json(HTTPStatus.OK, app.analyze(source))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except OSError as error:
                self.log_error("telemetry source failed: %s", error)
                return self._json(HTTPStatus.BAD_GATEWAY, {"error": "telemetry source is unavailable; inspect server log"})
            except Exception as error:
                self.log_error("analysis failed: %s", error)
                return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "analysis failed; inspect server log"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostic application for distributed services")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18100)
    parser.add_argument("--unsafe-public", action="store_true",
                        help="Allow non-loopback binding only behind an independently secured proxy")
    args = parser.parse_args()
    if not is_loopback_host(args.host) and not args.unsafe_public:
        parser.error("non-loopback binding requires --unsafe-public and a secured reverse proxy")
    app = DiagnosticApplication(args.root)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"Диагностическая система: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
