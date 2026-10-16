"""OpenAPI 3.1 description of the same-origin, read-only diagnostic API."""
from __future__ import annotations


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def obj(properties, required=(), *, extra=False):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": extra}


STRING = {"type": "string"}
NUMBER = {"type": "number"}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
COVERAGE = {"type": "number", "minimum": 0, "maximum": 1}
ARRAY_STRING = {"type": "array", "items": STRING}
LIVE_INPUT = obj({"profile_id": {"type": "string", "minLength": 1},
                  "start_unix": {"type": "number", "exclusiveMinimum": 0},
                  "end_unix": {"type": "number", "exclusiveMinimum": 0}},
                 ("profile_id", "start_unix", "end_unix"))
LIVE_INPUT["description"] = "Unix seconds UTC; end > start, duration <= 3600 s, end not in future. Both metric boundaries inclusive."

SCHEMAS = {
    "LiveAnalysisRequest": LIVE_INPUT,
    "AnalysisRequest": {"oneOf": [ref("LiveAnalysisRequest"),
        obj({"example_id": STRING}, ("example_id",)),
        obj({"incident": {"type": "object"}}, ("incident",))],
        "description": "Replay variants require a separately installed research replay runtime."},
    "Error": obj({"schema_version": {"const": "1.0"}, "code": STRING,
                  "error": STRING, "fields": ARRAY_STRING,
                  "request_id": {"type": "string", "format": "uuid"}},
                 ("schema_version", "code", "error", "fields", "request_id")),
    "Coverage": obj({name: COVERAGE for name in ("metrics", "traces", "topology")},
                    ("metrics", "traces", "topology")),
    "Evidence": obj({**{name: NUMBER for name in ("metric_support", "trace_local_support",
                        "propagation_support", "dependency_wait_support", "disappearance_support")},
                     "coverage": ref("Coverage")}, ("coverage",), extra=True),
    "MetricObservation": obj({"samples": {"type": "integer", "minimum": 1}, "min": NUMBER,
                              "median": NUMBER, "max": NUMBER, "unit": {"enum": ["cores", "bytes", "bytes_per_second"]}},
                             ("samples", "min", "median", "max", "unit")),
    "Observations": obj({"metrics": {"type": "object", "additionalProperties": ref("MetricObservation")},
                         "traces": obj({"count": {"type": "integer", "minimum": 0},
                                        "errors": {"type": "integer", "minimum": 0}}, ("count", "errors"))},
                        ("metrics", "traces")),
    "Candidate": obj({"service": STRING, "rank": {"type": "integer", "minimum": 1},
                      "model_score": NUMBER, "evidence": ref("Evidence"), "observations": ref("Observations")},
                     ("service", "rank", "model_score", "evidence", "observations"), extra=True),
    "SourceStatus": obj({
        "metrics": {"const": "available"}, "traces": {"enum": ["available", "unavailable"]},
        "trace_error": {"type": ["string", "null"]},
        "metric_families_by_service": {"type": "object", "additionalProperties": {"type": "array", "items": {"enum": ["cpu", "memory", "network", "traffic_rate"]}}},
        "metric_point_coverage": {"type": "object", "additionalProperties": obj({name: COVERAGE for name in ("cpu", "memory", "network", "traffic_rate")}, ("cpu", "memory", "network", "traffic_rate"))},
        "metric_sample_count": {"type": "integer", "minimum": 0},
        "span_count": {"type": "integer", "minimum": 0},
        "services_without_spans": ARRAY_STRING,
        "annotations": {"type": "array", "items": obj({"source": {"const": "metrics"}, "family": STRING,
                        "level": {"enum": ["warnings", "infos"]}, "message": STRING}, ("source", "family", "level", "message"))},
        "collected_at_unix": NUMBER, "query_step_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
        "trace_api": {"const": "jaeger-http-json"}, "trace_tested_version": STRING,
        "trace_query_services": ARRAY_STRING, "input_sha256": HASH,
        "elapsed_seconds": {"type": "number", "minimum": 0},
    }, ("metrics", "traces", "trace_error", "metric_families_by_service", "metric_point_coverage",
        "metric_sample_count", "span_count", "services_without_spans", "annotations", "collected_at_unix",
        "query_step_seconds", "trace_api", "trace_tested_version", "trace_query_services", "input_sha256", "elapsed_seconds")),
    "AnalysisResult": obj({
        "schema_version": {"const": "1.0"}, "result_id": {"type": "string", "format": "uuid"},
        "incident_id": STRING, "start_unix": NUMBER, "end_unix": NUMBER,
        "method": STRING, "model_version": STRING, "model_count": {"type": "integer", "minimum": 1},
        "candidate_count": {"type": "integer", "minimum": 1},
        "causal_status": {"const": "DIAGNOSTIC_RANKING_ONLY"},
        "input_sha256": HASH, "baseline_sha256": HASH, "feature_schema_sha256": HASH,
        "candidates": {"type": "array", "minItems": 1, "items": ref("Candidate")},
        "profile_id": STRING, "profile_version": STRING,
        "source_status": ref("SourceStatus"),
        "timing": obj({name: {"type": "number", "minimum": 0} for name in (
            "collection_seconds", "calculation_seconds", "total_seconds")},
            ("collection_seconds", "calculation_seconds", "total_seconds")),
    }, ("schema_version", "result_id", "incident_id", "start_unix", "end_unix", "method",
        "model_version", "model_count", "candidate_count", "causal_status", "input_sha256",
        "baseline_sha256", "feature_schema_sha256", "candidates")),
    "Profile": obj({"id": STRING, "title": STRING, "version": STRING,
                    "candidate_count": {"type": "integer", "minimum": 1}, "status": {"const": "configured"}},
                   ("id", "title", "version", "candidate_count", "status")),
}


def response(schema, description):
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def document():
    errors = {str(status): response(ref("Error"), description) for status, description in (
        (400, "INVALID_REQUEST or INVALID_INTERVAL"), (404, "PROFILE_UNKNOWN or NOT_FOUND"),
        (408, "REQUEST_TIMEOUT; incomplete client body"),
        (413, "PAYLOAD_TOO_LARGE"), (415, "MEDIA_TYPE_UNSUPPORTED"), (429, "REQUEST_BUSY; retry later"),
        (502, "TELEMETRY_UNAVAILABLE or TELEMETRY_INVALID; missing or unusable required telemetry"),
        (504, "SOURCE_TIMEOUT"), (500, "INTERNAL_ERROR"))}
    return {
        "openapi": "3.1.0", "info": {"title": "Service diagnostic ranking API", "version": "1.0.0"},
        "servers": [{"url": "/"}],
        "paths": {
            "/api/health": {"get": {"operationId": "health", "summary": "Model/setup status, not a source connectivity check",
                "responses": {"200": response({"type": "object"}, "Application status")}}},
            "/api/profiles": {"get": {"operationId": "profiles", "summary": "Installed usable systems",
                "responses": {"200": response({"type": "array", "items": ref("Profile")}, "Systems")}}},
            "/api/analyze": {"post": {"operationId": "analyze", "summary": "Collect and rank, or replay a saved input",
                "description": "Read-only synchronous operation. One in-flight analysis per application process; no queue. Maximum body 24 MiB. Sources and queries are operator-installed, never caller supplied. Live collection has a 120-second budget; response timing is measured, not an SLA.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": ref("AnalysisRequest")}}},
                "responses": {"200": response(ref("AnalysisResult"), "Full ranking; inspect warnings and coverage"), **errors}}},
            "/api/examples": {"get": {"operationId": "replayExamples", "tags": ["Optional research"],
                "responses": {"200": response({"type": "array", "items": obj({"id": STRING, "title": STRING}, ("id", "title"))}, "Empty when replay is not installed")}}},
            "/api/results": {"get": {"operationId": "researchResults", "tags": ["Optional research"],
                "responses": {"200": response({"type": "object"}, "Independent experiment summary"),
                              "404": response(ref("Error"), "Experiment is not installed")}}},
            "/api/openapi.json": {"get": {"operationId": "openapi", "responses": {"200": response({"type": "object"}, "This OpenAPI document")}}},
        }, "components": {"schemas": SCHEMAS},
    }
