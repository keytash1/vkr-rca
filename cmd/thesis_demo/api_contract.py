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
                  "end_unix": {"type": "number", "exclusiveMinimum": 0},
                  "force_refresh": {"type": "boolean", "default": False}},
                 ("profile_id", "start_unix", "end_unix"))
LIVE_INPUT["description"] = "Unix seconds UTC; end > start, duration <= 3600 s, end not in future. Both metric boundaries inclusive."

SCHEMAS = {
    "HttpObservationsStatus": obj({
        "version": {"const": "service-http-observations-v1"},
        "status": {"enum": ["complete", "partial", "unavailable"]},
        "reason": STRING, "config_sha256": HASH, "model_input": {"const": False},
        "lookback_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
        "collected_at_unix": NUMBER,
        "services": {"type": "object", "additionalProperties": {"enum": [
            "OBSERVED", "NO_ACTIVITY", "PARTIAL", "INCOMPLETE", "UNAVAILABLE"]}},
    }, ("status", "reason")),
    "IncidentContextStatus": obj({
        "services": {"type":"object", "additionalProperties":{"enum":["available", "truncated", "unavailable", "not_configured"]}},
        "assistant_categories_enabled":{"type":"boolean"},
        "raw_fields_disclosure":{"const":"LOCAL_ONLY"},
        "status":{"const":"projection_unavailable"},
    }),
    "BaselineApplicability": obj({
        "version": {"const": "baseline-applicability-v1"},
        "state": {"enum": ["REVIEW_REQUIRED", "REFERENCE_ONLY"]},
        "temporal_relation": {"enum": ["UNKNOWN", "PRECEDES", "AFTER", "OVERLAPS"]},
        **{name: {"type": ["number", "null"]} for name in ("healthy_start_unix", "healthy_end_unix", "reference_rps", "current_rps", "rps_ratio")},
        **{name: {"enum": ["unknown", "profile_constant", "measured_interval_mean"]} for name in ("reference_source", "current_source")},
        "load_relation": {"enum": ["UNKNOWN", "SAME_REFERENCE_RPS", "DIFFERENT_REFERENCE_RPS"]},
        "reasons": ARRAY_STRING,
        "meaning": {"const": "PROVENANCE_CHECK_NOT_MODEL_CONFIDENCE_OR_CAUSAL_PROOF"},
    }, ("version", "state", "temporal_relation", "healthy_start_unix", "healthy_end_unix", "reference_rps", "current_rps", "rps_ratio", "reference_source", "current_source", "load_relation", "reasons", "meaning")),
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
        "trace_api": {"enum": ["jaeger-http-json","jaeger-v3-json"]}, "trace_tested_version": STRING,
        "trace_query_services": ARRAY_STRING, "input_sha256": HASH,
        "trace_search_completeness": {"const": "unknown_backend_search_depth_sampling_and_retention"},
        "baseline_binding": obj({"state": {"enum": ["active", "needs_review", "draft"]},
            "reason": STRING, "profile_contract_sha256": HASH,
            "healthy_end_unix": {"type": ["number", "null"]}}, ("state", "reason")),
        "elapsed_seconds": {"type": "number", "minimum": 0},
        "workload_source":{"enum":["profile_constant", "measured_interval_mean"]},
        "incident_context":ref("IncidentContextStatus"),
        "context_collection_seconds":{"type":"number", "minimum":0},
        "http_observations": ref("HttpObservationsStatus"),
        "http_collection_seconds": {"type": "number", "minimum": 0},
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
        "workspace_status": {"enum": ["saved", "unavailable"], "description": "Present only with optional local workspace; rank does not depend on storage."},
        "delivery": obj({"cache_hit": {"type": "boolean"}, "joined_inflight": {"type": "boolean"},
            "cache_ttl_seconds": {"type": "number", "minimum": 0},
            "source_age_seconds": {"type": ["number", "null"], "minimum": 0}},
            ("cache_hit", "joined_inflight", "cache_ttl_seconds", "source_age_seconds")),
        "timing": obj({name: {"type": "number", "minimum": 0} for name in (
            "collection_seconds", "calculation_seconds", "total_seconds")},
            ("collection_seconds", "calculation_seconds", "total_seconds")),
    }, ("schema_version", "result_id", "incident_id", "start_unix", "end_unix", "method",
        "model_version", "model_count", "candidate_count", "causal_status", "input_sha256",
        "baseline_sha256", "feature_schema_sha256", "candidates")),
    "Profile": obj({"id": STRING, "title": STRING, "version": STRING,
                    "candidate_count": {"type": "integer", "minimum": 1}, "status": {"const": "configured"}},
                   ("id", "title", "version", "candidate_count", "status")),
    "Observation": obj({"id": {"type": "string", "pattern": "^obs-[0-9a-f]{32}$"},
        "service": STRING, "kind": {"enum": ["metric", "traces", "dependencies", "context"]},
        "start_unix": NUMBER, "end_unix": NUMBER, "values": {"type": "object"},
        "source_links": {"type": "array", "items": obj({"kind": STRING,
            "url": {"type": "string", "format": "uri"}}, ("kind", "url"))}},
        ("id", "service", "kind", "start_unix", "end_unix", "values", "source_links")),
    "EvidenceCatalog": obj({"schema_version": {"const": "2.0"},
        "catalog_version": {"enum": ["evidence-v1", "evidence-v2-source-timings", "evidence-v3-incident-context", "evidence-v4-service-http"]},
        "analysis_id": {"type": "string", "format": "uuid"},
        "profile_id": {"type": ["string", "null"]}, "profile_version": {"type": ["string", "null"]},
        "input_sha256": HASH, "baseline_sha256": HASH, "feature_schema_sha256": HASH,
        "model_version": STRING, "start_unix": NUMBER, "end_unix": NUMBER,
        "services": ARRAY_STRING, "requests_per_second": NUMBER,
        "source_quality": obj({"baseline_applicability": ref("BaselineApplicability")}, extra=True), "limitations": ARRAY_STRING,
        "observations": {"type": "array", "items": ref("Observation")},
        "checks": {"type": "array", "items": obj({"service": STRING, "code": STRING,
            "evidence_ids": ARRAY_STRING, "text": STRING, "status": {"const": "PROPOSED_NOT_EXECUTED"}},
            ("service", "code", "evidence_ids", "text", "status"))}},
        ("schema_version", "catalog_version", "analysis_id", "profile_id", "profile_version",
         "input_sha256", "baseline_sha256", "feature_schema_sha256", "model_version",
         "start_unix", "end_unix", "services", "requests_per_second", "source_quality",
         "limitations", "observations", "checks")),
}

RECORD_TEXT = {"type":"string","maxLength":2000}
SCHEMAS.update({
    "InvestigationRequest": obj({"analysis_id":STRING,"mode":{"enum":["B","C","D"]},
        "question":{"type":"string","minLength":1,"maxLength":2000},
        "idempotency_key":{"type":"string","pattern":"^[A-Za-z0-9_-]{1,128}$"}},
        ("analysis_id","mode","question","idempotency_key")),
    "InvestigationRecord": obj({"title":{"type":"string","maxLength":200},"symptoms":RECORD_TEXT,
        "impact":RECORD_TEXT,"conclusion":RECORD_TEXT,
        "metadata":obj({"owner":{"type":"string","maxLength":200},"incident":{"type":"string","maxLength":200},"category":{"type":"string","maxLength":100}},("owner","incident","category")),
        "approval":obj({"record_sha256":HASH,"reviewed_at_unix":NUMBER},("record_sha256","reviewed_at_unix")),
        "timeline":{"type":"array","maxItems":50,"items":obj({"time_unix":NUMBER,"description":RECORD_TEXT,"evidence_ids":ARRAY_STRING},("time_unix","description","evidence_ids"))},
        "causes":{"type":"array","maxItems":10,"items":obj({"service":STRING,"statement":RECORD_TEXT,
            "status":{"enum":["hypothesis","confirmed","discarded"]},"verification":RECORD_TEXT,"evidence_ids":ARRAY_STRING},
            ("service","statement","status","verification","evidence_ids"))},
        "action_items":{"type":"array","maxItems":20,"items":obj({"id":STRING,"title":RECORD_TEXT,
            "owner":{"type":"string","maxLength":200},"due_unix":{"type":["number","null"]},
            "status":{"enum":["proposed","planned","in_progress","verification_pending","verified","not_verified"]},
            "importance":{"enum":["low","normal","high"]},"effort":{"enum":["small","medium","large","unknown"]},
            "verification":RECORD_TEXT,"evidence_ids":ARRAY_STRING,
            "purpose":{"enum":["unspecified","mitigation","corrective","preventive"]},"service":STRING,
            "rationale":RECORD_TEXT,"verification_plan":RECORD_TEXT,"ticket":{"type":"string","maxLength":200}},
            ("id","title","owner","due_unix","status","importance","effort","verification","evidence_ids"))}},
        ("title","symptoms","impact","conclusion","timeline","causes","action_items")),
    "Investigation": obj({"id":STRING,"analysis_id":STRING,"project":STRING,
        "state":{"enum":["queued","running","cancelling","completed","partial","failed","cancelled","interrupted"]},
        "created":NUMBER,"updated":NUMBER,"revision":{"type":"integer","minimum":0},
        "request":{"type":"object"},"outcome":{"type":["object","null"]},"record":ref("InvestigationRecord"),
        "turns":{"type":"array","maxItems":10,"items":obj({"number":{"type":"integer","minimum":1},"state":STRING,
            "created":NUMBER,"updated":NUMBER,"request":{"type":"object"},"outcome":{"type":["object","null"]}},
            ("number","state","created","updated","request","outcome"))}},
        ("id","analysis_id","project","state","created","updated","revision","request","outcome","record","turns")),
})


def response(schema, description):
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def document():
    errors = {str(status): response(ref("Error"), description) for status, description in (
        (400, "INVALID_REQUEST or INVALID_INTERVAL"), (403, "HOST_NOT_ALLOWED or ORIGIN_NOT_ALLOWED"), (404, "PROFILE_UNKNOWN or NOT_FOUND"),
        (408, "REQUEST_TIMEOUT; incomplete client body"),
        (413, "PAYLOAD_TOO_LARGE"), (415, "MEDIA_TYPE_UNSUPPORTED"), (429, "REQUEST_BUSY; retry later"),
        (502, "TELEMETRY_UNAVAILABLE or TELEMETRY_INVALID; missing or unusable required telemetry"),
        (504, "SOURCE_TIMEOUT"), (500, "INTERNAL_ERROR"))}
    return {
        "openapi": "3.1.0", "info": {"title": "Service diagnostic ranking API", "version": "1.2.0"},
        "servers": [{"url": "/"}],
        "paths": {
            "/healthz": {"get": {"operationId": "coreReadiness", "summary": "Non-sensitive core readiness; no source I/O or workspace content",
                "responses": {str(code): response(obj({"status": {"type": "string", "enum": [state]}}, ("status",)), state)
                              for code, state in ((200, "ready"), (503, "not_configured"))}}},
            "/api/health": {"get": {"operationId": "health", "summary": "Model/setup status, not a source connectivity check",
                "responses": {"200": response({"type": "object"}, "Application status")}}},
            "/api/profiles": {"get": {"operationId": "profiles", "summary": "Installed usable systems",
                "responses": {"200": response({"type": "array", "items": ref("Profile")}, "Systems")}}},
            "/api/analyze": {"post": {"operationId": "analyze", "summary": "Collect and rank, or replay a saved input",
                "description": "Read-only synchronous operation. One live owner plus at most one identical joining request; other concurrent requests return 429. Complete eligible results are reused in memory up to 15 seconds; force_refresh bypasses reuse and creates a new result. No stale fallback after a source error. Replay has its own single in-flight guard. Maximum body 24 MiB. Sources and queries are operator-installed, never caller supplied. Live collection has a 120-second budget; timing is measured, not an SLA.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": ref("AnalysisRequest")}}},
                "responses": {"200": response(ref("AnalysisResult"), "Full ranking; inspect warnings and coverage"), **errors}}},
            "/api/v2/analyses/{analysis_id}/evidence": {"get": {
                "operationId": "analysisEvidence", "summary": "Bounded observations and proposed checks, not a causal conclusion",
                "description": "No source I/O. Default: in-memory retention 30 minutes, 16 catalogues, 32 MiB total/4 MiB each. Optional loopback workspace retains live snapshots for its configured TTL and supplies a durable fallback. Missing/expired IDs return 404. Source links can require separate authentication and are not sent to LLM by default.",
                "parameters": [{"name": "analysis_id", "in": "path", "required": True,
                    "schema": {"type": "string", "format": "uuid"}}],
                "responses": {"200": response(ref("EvidenceCatalog"), "Versioned facts, full inventory in neutral order"),
                    "404": response(ref("Error"), "EVIDENCE_NOT_FOUND")}}},
            "/api/examples": {"get": {"operationId": "replayExamples", "tags": ["Optional research"],
                "responses": {"200": response({"type": "array", "items": obj({"id": STRING, "title": STRING}, ("id", "title"))}, "Empty when replay is not installed")}}},
            "/api/results": {"get": {"operationId": "researchResults", "tags": ["Optional research"],
                "responses": {"200": response({"type": "object"}, "Independent experiment summary"),
                              "404": response(ref("Error"), "Experiment is not installed")}}},
            "/api/openapi.json": {"get": {"operationId": "openapi", "responses": {"200": response({"type": "object"}, "This OpenAPI document")}}},
            **workspace_paths(),
        }, "components": {"schemas": SCHEMAS,"securitySchemes":{
            "workspaceCookie":{"type":"apiKey","in":"cookie","name":"rca_workspace_session"},
            "workspaceCSRF":{"type":"apiKey","in":"header","name":"X-RCA-CSRF"}}},
    }


def workspace_paths():
    """Optional local extension. Disabled deployments return 404 for these URIs."""
    error_responses={str(c):response(ref("Error"),m) for c,m in ((400,"Invalid fields/business validation"),
        (401,"Session required"),(403,"Host/Origin/CSRF or profile transmission policy rejected"),
        (404,"Object unavailable or extension disabled"),(409,"Idempotency/revision conflict"),
        (413,"Maximum body 32 KiB"),(429,"Bounded queue/storage, turn or rolling assistant job allowance exceeded"),(503,"Workspace unavailable"))}
    security=[{"workspaceCookie":[],"workspaceCSRF":[]}]
    def operation(name,summary,*,post=False,body=None,result=None):
        value={"operationId":name,"summary":summary,"tags":["Optional trusted-loopback workspace"],
            "description":"One local installation, not multi-tenant authentication. Admin settings are CLI-only. Mutations require exact local Origin, session cookie and X-RCA-CSRF. No source queries or side effects on monitored services.",
            "security":security if post else [{"workspaceCookie":[]}],
            "responses":{"200":response(result or ref("Investigation"),"Current state"),**error_responses}}
        if post:
            value["requestBody"]={"required":True,"content":{"application/json":{"schema":body or obj({})}}}
        return value
    create=operation("createInvestigation","Create deterministic or approved assistant investigation; retry same idempotency key",post=True,body=ref("InvestigationRequest"))
    create["responses"]["202"]=response(ref("Investigation"),"Enqueued; one running/one waiting, no rank lock")
    follow=operation("followUpInvestigation","Bounded follow-up on the same immutable snapshot; preserve human record and prior turns",post=True,
        body=obj({"mode":{"enum":["B","C","D"]},"question":{"type":"string","minLength":1,"maxLength":2000},
            "idempotency_key":{"type":"string","pattern":"^[A-Za-z0-9_-]{1,128}$"}},("mode","question","idempotency_key")))
    follow["responses"]["202"]=response(ref("Investigation"),"New turn enqueued; earlier answers and human record retained")
    history=operation("listInvestigations","Filter human records before limit; period is card creation time, not incident time",result={"type":"object"})
    history["parameters"]=[{"name":name,"in":"query","required":False,"schema":schema}
        for name,schema in (("project",STRING),("service",STRING),("category",{"type":"string","maxLength":100}),
            ("after",{"type":"number","minimum":0}),("before",{"type":"number","minimum":0}),
            ("action_status",{"enum":["proposed","planned","in_progress","verification_pending","verified","not_verified","overdue"]}),
            ("limit",{"type":"integer","minimum":1,"maximum":100,"default":30}))]
    return {
        "/api/v2/workspace":{"get":{"operationId":"workspaceSession","summary":"Start local browser session and inspect configured capabilities",
            "tags":["Optional trusted-loopback workspace"],"responses":{"200":response({"type":"object"},"CSRF token; HttpOnly SameSite=Strict session cookie"),**error_responses}}},
        "/api/v2/investigations":{"get":history,"post":create},
        "/api/v2/investigations/{investigation_id}":{"parameters":[{"name":"investigation_id","in":"path","required":True,"schema":STRING}],
            "get":operation("getInvestigation","Read current job, outcome and human record")},
        "/api/v2/investigations/{investigation_id}/cancel":{"parameters":[{"name":"investigation_id","in":"path","required":True,"schema":STRING}],
            "post":operation("cancelInvestigation","Request cancellation; poll until terminal state",post=True)},
        "/api/v2/investigations/{investigation_id}/record":{"parameters":[{"name":"investigation_id","in":"path","required":True,"schema":STRING}],
            "post":operation("saveInvestigationRecord","Optimistic revision update; human hypotheses/causes/actions, not LLM confirmation",post=True,
                body=obj({"expected_revision":{"type":"integer","minimum":0},"record":ref("InvestigationRecord")},("expected_revision","record")))},
        "/api/v2/investigations/{investigation_id}/messages":{"parameters":[{"name":"investigation_id","in":"path","required":True,"schema":STRING}],
            "post":follow},
        "/api/v2/investigations/{investigation_id}/review":{"parameters":[{"name":"investigation_id","in":"path","required":True,"schema":STRING}],
            "post":operation("reviewInvestigationRecord","Human review of saved record revision; not automatic confirmation of causes/actions",post=True,
                body=obj({"expected_revision":{"type":"integer","minimum":0}},("expected_revision",)))},
        "/api/v2/analyses/{analysis_id}/snapshot":{"parameters":[{"name":"analysis_id","in":"path","required":True,"schema":STRING}],
            "get":operation("readSnapshot","Read immutable stored result/catalog with provenance; no recollection",result={"type":"object"})},
        "/api/v2/analyses/{analysis_id}/delete":{"parameters":[{"name":"analysis_id","in":"path","required":True,"schema":STRING}],
            "post":operation("deleteSnapshot","Cancel dependent work and logically delete snapshot and investigations; baseline untouched",post=True,result=obj({"deleted":{"type":"boolean"}},("deleted",)))},
    }
