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
import logging
import math
import mimetypes
import os
import threading
import time
import uuid
from statistics import median
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from typing import TYPE_CHECKING

from live_sources import LiveProfile, TelemetrySourceError, collect
from api_errors import ApiError
from api_contract import document as api_document
from evidence_catalog import EvidenceRegistry, build_catalog
from profile_runtime import ProfileTransferRuntime
from trace_adapters import validate_canonical_spans
from profile_contract import baseline_binding, contract_sha256
from analysis_requests import AnalysisRequests
from rca_ml.m13_features import build_candidate_rows
if TYPE_CHECKING:
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
    def __init__(self, root: Path, profiles_dir: Path | None = None, *, workspace=None, investigations=None, workspace_origin=None):
        self.root = root.resolve()
        self.workspace, self.investigations, self.workspace_http = workspace, investigations, None
        if workspace is not None and investigations is not None:
            from workspace_http import WorkspaceHTTP
            self.workspace_http = WorkspaceHTTP(workspace, investigations,evict_evidence=self._evict_analysis,expected_origin=workspace_origin)
        # Bound memory/CPU and serialize access to shared inference objects.
        # Do not build an unbounded queue of expired incident requests.
        self.analysis_slot = threading.BoundedSemaphore(1)
        self.live_requests = AnalysisRequests()
        self.evidence_registry = EvidenceRegistry()
        profiles_dir = profiles_dir or self.root / "deploy/profiles"
        self.profiles = {}
        self.profile_runtimes = {}
        self.profile_errors = {}
        self.profile_artifact_hashes = {}
        for path in sorted(profiles_dir.glob("*.json")):
            try:
                profile = LiveProfile.load(path, self.root)
                runtime = ProfileTransferRuntime(self.root, profile.artifact_dir, profile.services)
            except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
                self.profile_errors[path.stem] = str(error)
                continue
            if profile.id in self.profiles:
                raise ValueError(f"duplicate telemetry profile: {profile.id}")
            self.profiles[profile.id] = profile
            self.profile_runtimes[profile.id] = runtime
            self.profile_artifact_hashes[profile.id] = {
                name: hashlib.sha256((profile.artifact_dir / name).read_bytes()).hexdigest()
                for name in ("healthy-baseline.json", "legacy-metric-baseline.json")}
        self.run_dir = self.root / "external-data/m14/runs/locked-v1"
        self.static_dir = Path(__file__).resolve().parent / "static"
        evaluation_path = self.root / "ml/models/m14/evaluation.json"
        self.evaluation = json.loads(evaluation_path.read_text()) if evaluation_path.is_file() else None
        replay_files = (
            self.root / "ml/models/m14/healthy-baseline.json",
            self.root / "ml/models/m14/legacy-metric-baseline.json",
            self.root / "deploy/m14/config.json",
        )
        self.runtime = None
        if all(p.is_file() for p in replay_files):
            from rca_ml.m14_runtime import FrozenM13TransferRuntime
            self.runtime = FrozenM13TransferRuntime(self.root)
        index_path = self.run_dir / "locked/telemetry-index.jsonl"
        replay_root = self.run_dir
        if not index_path.is_file():
            replay_root = self.root / "deploy/product/replay"
            index_path = replay_root / "index.jsonl"
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
                path = (replay_root / relative).resolve()
                if not path.is_relative_to(replay_root) or not path.is_file():
                    raise ValueError("example telemetry is missing or outside run directory")
                self.examples[case_id] = (path, entry["sha256"])

    def _evict_analysis(self, identifier):
        self.evidence_registry.delete(identifier)
        self.live_requests.delete(identifier)

    def example(self, case_id: str) -> dict:
        if case_id not in self.examples:
            raise ValueError("unknown incident")
        path, expected_hash = self.examples[case_id]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError("incident data checksum mismatch")
        return json.loads(data)

    def analyze(self, incident: dict, runtime: FrozenM13TransferRuntime | None = None,
                *, profile: LiveProfile | None = None, source_status: dict | None = None) -> dict:
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
        validate_canonical_spans(clean.get("traces",[]))
        ranked = runtime.rank_all(clean)["frozen_m13"]
        rows = build_candidate_rows(clean, runtime.baseline, expected)
        by_service = {row["service"]: row["features"] for row in rows}
        observations = self._observation_summary(clean, expected)
        candidates = [
            ProfileTransferRuntime.evidence(item, by_service[item["service"]])
            | {"observations": observations[item["service"]]}
            for item in ranked
        ]
        if len(candidates) != len(expected):
            raise RuntimeError("incomplete candidate ranking")
        result = {
            "schema_version": "1.0",
            "result_id": str(uuid.uuid4()),
            "incident_id": str(incident.get("incident_id", "uploaded-window")),
            "start_unix": start,
            "end_unix": end,
            "method": "Диагностическое ранжирование сервисов",
            "model_version": runtime.freeze["version"],
            "model_count": len(runtime.models),
            "feature_schema_sha256": hashlib.sha256(json.dumps(runtime.columns, separators=(",", ":")).encode()).hexdigest(),
            "baseline_sha256": hashlib.sha256(json.dumps(
                {"diagnostic": runtime.baseline, "metric_context": runtime.legacy_baseline},
                sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode()).hexdigest(),
            "input_sha256": hashlib.sha256(json.dumps(clean, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "candidate_count": len(candidates),
            "causal_status": "DIAGNOSTIC_RANKING_ONLY",
            "candidates": candidates,
        }
        # An optional presentation projection never feeds back into inference.
        # A projection budget/error must not make a valid v1 ranking unavailable.
        try:
            provenance = {}
            if profile and (profile.artifact_dir / "provenance.json").is_file():
                provenance = json.loads((profile.artifact_dir / "provenance.json").read_text())
            self.evidence_registry.put(build_catalog(clean, result, runtime.baseline,
                profile=profile, source_status=source_status, baseline_provenance=provenance))
        except (ValueError, KeyError, TypeError, OSError) as error:
            logging.getLogger(__name__).warning("evidence_projection_unavailable type=%s", type(error).__name__)
        return result

    @staticmethod
    def _observation_summary(incident: dict, services: tuple[str, ...]) -> dict:
        """Small, checkable source summaries; never interpreted as model weights."""
        metrics = defaultdict(lambda: defaultdict(list))
        units = {}
        for item in incident["metrics"]:
            service = item["service"]
            if service in services and incident["start_unix"] <= float(item["timestamp"]) <= incident["end_unix"]:
                family = item["family"]
                value = float(item["value"])
                if math.isfinite(value):
                    metrics[service][family].append(value)
                    units[(service, family)] = item["unit"]
        spans = {service: {"count": 0, "errors": 0} for service in services}
        for span in incident["traces"]:
            service = span.get("service")
            if service in spans and incident["start_unix"] * 1e6 <= span["start_time_us"] <= incident["end_unix"] * 1e6:
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

    def analyze_live(self, profile_id: str, start: float, end: float, *, force_refresh=False) -> dict:
        if not isinstance(profile_id, str):
            raise ApiError("INVALID_REQUEST", "Выберите подключённую систему.", fields=("profile_id",))
        profile = self.profiles.get(profile_id)
        if profile is None:
            raise ApiError("PROFILE_UNKNOWN", "Система не подключена. Выберите доступную систему или обратитесь к интегратору.",
                           status=HTTPStatus.NOT_FOUND, fields=("profile_id",))
        if not isinstance(force_refresh, bool):
            raise ApiError("INVALID_REQUEST", "force_refresh должен быть логическим значением.")
        # Validate before even considering reuse; do not serve a previous result
        # after baseline files or source credential scope were changed in place.
        baseline_binding(profile)
        for name, expected in self.profile_artifact_hashes[profile.id].items():
            if hashlib.sha256((profile.artifact_dir / name).read_bytes()).hexdigest() != expected:
                raise ApiError("PROFILE_INCOMPATIBLE", "Базовое состояние изменено. Перезапустите приложение после проверки интегратором.", 409)
        key = hashlib.sha256(json.dumps({"profile": profile.id, "version": profile.version,
            "contract": contract_sha256(profile), "baseline": self.profile_artifact_hashes[profile.id],
            "start": start, "end": end,
            "access": [os.environ.get(name, "") if name else "" for name in (profile.metric_token_env,profile.trace_token_env)]},
            sort_keys=True, allow_nan=False).encode()).hexdigest()
        def compute():
            if not self.analysis_slot.acquire(blocking=False):
                raise ApiError("REQUEST_BUSY", "Выполняется другой анализ. Повторите после его завершения.", 429)
            try:
                return self._analyze_live(profile, start, end)
            finally:
                self.analysis_slot.release()
        return self.live_requests.run(key, compute, refresh=force_refresh)

    def _analyze_live(self, profile: LiveProfile, start: float, end: float) -> dict:
        started = time.monotonic()
        window, source_status = collect(profile, start, end)
        runtime = self.profile_runtimes[profile.id]
        calculation_started = time.monotonic()
        result = self.analyze(window, runtime, profile=profile, source_status=source_status)
        result.update({"profile_id": profile.id, "profile_version": profile.version,
                       "source_status": source_status, "input_sha256": source_status["input_sha256"]})
        result["timing"] = {"collection_seconds": round(calculation_started - started, 4),
                            "calculation_seconds": round(time.monotonic() - calculation_started, 4),
                            "total_seconds": round(time.monotonic() - started, 4)}
        if self.workspace is not None:
            try:
                catalog = self.evidence_registry.get(result["result_id"])
                if catalog is None:
                    raise ValueError("EVIDENCE_PROJECTION_UNAVAILABLE")
                result["workspace_status"] = "saved"
                self.workspace.put_snapshot(catalog,result,project=profile.id)
            except Exception as error:
                result["workspace_status"] = "unavailable"
                logging.getLogger(__name__).warning("workspace_snapshot_unavailable type=%s",type(error).__name__)
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


def make_handler(app: DiagnosticApplication, *, allow_proxy_host=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RCADiagnostics/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def end_headers(self):
            # Model/source text is rendered as textContent; CSP is a second
            # boundary, not an excuse to evaluate generated HTML or commands.
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _local_base_guard(self):
            # Loopback binding alone is insufficient against DNS rebinding.
            # Optional workspace enforces its own fixed published origin.
            if app.workspace_http is not None or allow_proxy_host:
                return
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                raise ApiError("HOST_NOT_ALLOWED", "Недопустимый адрес приложения.", 403)
            origin = self.headers.get("Origin")
            if ((origin is not None and origin != "http://"+host)
                    or self.headers.get("Sec-Fetch-Site", "") not in {"", "same-origin", "none"}):
                raise ApiError("ORIGIN_NOT_ALLOWED", "Откройте приложение с локального адреса.", 403)

        def _error(self, status, code, message, fields=()):
            request_id = str(uuid.uuid4())
            self.log_error("request_id=%s code=%s", request_id, code)
            return self._json(status, {"schema_version": "1.0", "code": code,
                                      "error": message, "fields": list(fields),
                                      "request_id": request_id})

        def _json(self, code: HTTPStatus, value: object, *, headers=None):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key,value in (headers or {}).items():
                self.send_header(key,value)
            if code == HTTPStatus.TOO_MANY_REQUESTS:
                self.send_header("Retry-After", "2")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/healthz":
                # Non-sensitive process/core readiness only, no profiles, source
                # requests, cookies or workspace content. Container probes use
                # the internal port, unlike the browser's fixed public origin.
                ready = bool(app.profile_runtimes or app.runtime)
                return self._json(HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                                  {"status": "ready" if ready else "not_configured"})
            try:
                self._local_base_guard()
            except ApiError as error:
                return self._error(error.status,error.code,str(error),error.fields)
            if app.workspace_http is not None:
                try:
                    app.workspace_http.check_local(self)
                    if app.workspace_http.get(self,path):
                        return
                except Exception as error:
                    from workspace_http import public_workspace_error
                    error = public_workspace_error(error)
                    return self._error(error.status,error.code,str(error),error.fields)
            if path == "/api/openapi.json":
                return self._json(HTTPStatus.OK, api_document())
            if path == "/api/health":
                runtime = next(iter(app.profile_runtimes.values()), app.runtime)
                return self._json(HTTPStatus.OK, {
                    "status": "model_loaded" if runtime else "not_configured", "sources": "not_checked",
                    "model_count": len(runtime.models) if runtime else 0,
                    "profiles": len(app.profiles), "examples": len(app.examples),
                    "profile_errors": app.profile_errors,
                    "experiment_available": app.evaluation is not None and app.runtime is not None,
                })
            if path == "/api/examples":
                return self._json(HTTPStatus.OK, [{"id": key, "title": f"Инцидент {n:02d}"} for n, key in enumerate(app.examples, 1)])
            if path == "/api/profiles":
                return self._json(HTTPStatus.OK, [
                    {"id": profile.id, "title": profile.title, "version": profile.version,
                     "candidate_count": len(profile.services), "status": "configured"}
                    for profile in app.profiles.values()
                ])
            if path == "/api/results":
                if app.evaluation is None or app.runtime is None:
                    return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Результаты эксперимента не установлены.")
                return self._json(HTTPStatus.OK, app.public_results())
            if path.startswith("/api/v2/analyses/") and path.endswith("/evidence"):
                parts = path.split("/")
                if len(parts) == 6:
                    catalog = app.evidence_registry.get(parts[4])
                    if catalog is None and app.workspace is not None:
                        try:
                            saved = app.workspace.get_snapshot(parts[4])
                            catalog = saved["catalog"] if saved else None
                        except Exception:
                            catalog = None
                    if catalog is not None:
                        return self._json(HTTPStatus.OK, catalog)
                return self._error(HTTPStatus.NOT_FOUND, "EVIDENCE_NOT_FOUND",
                    "Наблюдения недоступны или срок хранения истёк. Повторите анализ и сохраните результат.")
            if path.startswith("/api/"):
                return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Операция не найдена.")
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
            try:
                self._local_base_guard()
            except ApiError as error:
                return self._error(error.status,error.code,str(error),error.fields)
            if app.workspace_http is not None:
                try:
                    app.workspace_http.check_local(self)
                    if urlsplit(self.path).path.startswith("/api/v2/"):
                        return app.workspace_http.post(self,urlsplit(self.path).path)
                except Exception as error:
                    from workspace_http import public_workspace_error
                    error = public_workspace_error(error)
                    return self._error(error.status,error.code,str(error),error.fields)
            if urlsplit(self.path).path != "/api/analyze":
                return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Операция не найдена.")
            acquired = False
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ApiError("MEDIA_TYPE_UNSUPPORTED", "Передайте JSON с Content-Type: application/json.", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                if self.headers.get("Transfer-Encoding"):
                    raise ApiError("INVALID_REQUEST", "Передайте запрос с Content-Length без Transfer-Encoding.")
                length = int(self.headers.get("Content-Length", "0"))
                if length > MAX_UPLOAD_BYTES:
                    raise ApiError("PAYLOAD_TOO_LARGE", "Размер запроса превышает 24 МиБ.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                if length <= 0:
                    raise ApiError("INVALID_REQUEST", "Тело запроса не должно быть пустым.")
                try:
                    body = self.rfile.read(length)
                except TimeoutError as error:
                    raise ApiError("REQUEST_TIMEOUT", "Не удалось получить полное тело запроса за отведённое время.", HTTPStatus.REQUEST_TIMEOUT) from error
                if len(body) != length:
                    raise ApiError("INVALID_REQUEST", "Передано неполное тело запроса.")
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ApiError("INVALID_REQUEST", "Тело запроса должно быть JSON-объектом.")
                if set(payload) in ({"profile_id", "start_unix", "end_unix"}, {"profile_id", "start_unix", "end_unix", "force_refresh"}):
                    return self._json(HTTPStatus.OK, app.analyze_live(payload["profile_id"], payload["start_unix"], payload["end_unix"],
                        force_refresh=payload.get("force_refresh",False)))
                acquired = app.analysis_slot.acquire(blocking=False)
                if not acquired:
                    raise ApiError("REQUEST_BUSY", "Выполняется другой анализ. Повторите запрос после его завершения.", HTTPStatus.TOO_MANY_REQUESTS)
                if set(payload) == {"example_id"}:
                    source = app.example(payload["example_id"])
                    source = {key: value for key, value in source.items() if key != "workload_result"}
                elif set(payload) == {"incident"}:
                    source = payload["incident"]
                else:
                    raise ApiError("INVALID_REQUEST", "Укажите систему и границы интервала без дополнительных полей либо выберите режим воспроизведения.")
                return self._json(HTTPStatus.OK, app.analyze(source))
            except ApiError as error:
                return self._error(error.status, error.code, str(error), error.fields)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                self.log_error("invalid analysis input: %s", type(error).__name__)
                return self._error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", "Проверьте формат запроса, состав сервисов и входные данные.")
            except TimeoutError:
                return self._error(HTTPStatus.GATEWAY_TIMEOUT, "SOURCE_TIMEOUT", "Источник не ответил вовремя. Повторите запрос или обратитесь к интегратору.")
            except TelemetrySourceError as error:
                self.log_error("telemetry rejected: %s", error.code)
                message = ("Источник вернул непригодные данные. Интегратору необходимо проверить запросы, метки и формат ответа."
                           if error.code == "TELEMETRY_INVALID" else "Источник телеметрии недоступен. Повторите запрос или обратитесь к интегратору.")
                return self._error(HTTPStatus.BAD_GATEWAY, error.code, message)
            except OSError as error:
                self.log_error("telemetry source failed: %s", type(error).__name__)
                return self._error(HTTPStatus.BAD_GATEWAY, "TELEMETRY_UNAVAILABLE", "Не удалось получить корректную телеметрию. Проверьте доступность и настройку источников у интегратора.")
            except Exception as error:
                self.log_error("analysis failed: %s", type(error).__name__)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Расчёт не выполнен. Передайте идентификатор запроса администратору.")
            finally:
                if acquired:
                    app.analysis_slot.release()

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostic application for distributed services")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18100)
    parser.add_argument("--profiles-dir", type=Path,
                        help="Directory containing the system profiles installed for this deployment")
    parser.add_argument("--unsafe-public", action="store_true",
                        help="Allow non-loopback binding only behind an independently secured proxy")
    parser.add_argument("--workspace-dir",type=Path,help="Private local SQLite directory; enables loopback-only investigations")
    parser.add_argument("--workspace-origin",help="Explicit host-loopback origin for isolated container port publishing only")
    parser.add_argument("--workspace-retention-days",type=int,choices=range(1,31),default=7,
                        help="Local snapshot/derived-record TTL, 1–30 days (default 7)")
    parser.add_argument("--assistant-python",type=Path,help="Optional isolated interpreter with assistant dependencies")
    parser.add_argument("--assistant-state-dir",type=Path,help="App-owned OAuth store; never the Codex credential directory")
    parser.add_argument("--assistant-model",help="Explicit previously verified provider model")
    parser.add_argument("--assistant-daily-jobs",type=int,choices=range(1,201),default=20,
                        help="Reserved LLM jobs per rolling 24h, 1–200 (default 20); not a provider token/cost cap")
    parser.add_argument("--allow-assistant-profile",action="append",default=[],help="Profile permitted to send approved aggregates; repeat per profile")
    parser.add_argument("--runbook-corpus",type=Path,help="Explicit approved project-scoped runbook corpus")
    args = parser.parse_args()
    if not is_loopback_host(args.host) and not args.unsafe_public:
        parser.error("non-loopback binding requires --unsafe-public and a secured reverse proxy")
    if args.workspace_origin:
        from workspace_http import validate_local_origin
        try:
            validate_local_origin(args.workspace_origin)
        except ValueError as error:
            parser.error(str(error))
        if not args.workspace_dir:
            parser.error("workspace origin requires a workspace directory")
    if (args.workspace_dir and args.host not in {"127.0.0.1","localhost"} and not args.workspace_origin
            or any((args.assistant_python,args.assistant_state_dir,args.assistant_model,args.allow_assistant_profile,args.runbook_corpus)) and not args.workspace_dir):
        parser.error("workspace/assistant require an explicit private directory and IPv4 loopback binding")
    if any((args.assistant_python,args.assistant_state_dir,args.assistant_model)) and not all((args.assistant_python,args.assistant_state_dir,args.assistant_model)):
        parser.error("assistant requires interpreter, app-owned state directory and explicit model together")
    store,service = None,None
    if args.workspace_dir:
        from workspace_store import WorkspaceStore
        from investigations import InvestigationService
        corpus=None
        if args.runbook_corpus:
            from runbook_corpus import RunbookCorpus
            corpus=RunbookCorpus(args.runbook_corpus)
        store = WorkspaceStore(args.workspace_dir,retention_seconds=args.workspace_retention_days*86400,
            assistant_daily_jobs=args.assistant_daily_jobs)
        service = InvestigationService(store,python_executable=args.assistant_python,state_dir=args.assistant_state_dir,
            model=args.assistant_model,allowed_profiles=args.allow_assistant_profile,runbook_corpus=corpus)
    app = DiagnosticApplication(args.root, args.profiles_dir,workspace=store,investigations=service,workspace_origin=args.workspace_origin)
    if set(args.allow_assistant_profile)-set(app.profiles):
        if service:
            service.close()
        parser.error("assistant allowlist includes an uninstalled or unusable profile")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app,allow_proxy_host=args.unsafe_public))
    print(f"Диагностическая система: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if service:
            service.close()


if __name__ == "__main__":
    main()
