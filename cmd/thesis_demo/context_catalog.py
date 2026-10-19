"""Local source assertions and an enum-only, explicitly opted-in projection."""
import copy
import hashlib
import json

CATEGORIES = frozenset({"PERMISSION_RESPONSE", "CONNECTION_REFUSED", "OPERATION_TIMEOUT",
    "DEPLOYMENT_EVENT", "CONFIGURATION_EVENT", "RESTART_EVENT", "OOM_EVENT", "OTHER_ERROR"})


def category(fields):
    if fields.get("http.response.status_code") in (401, 403): return "PERMISSION_RESPONSE"
    error = fields.get("error.type", fields.get("exception.type"))
    if error in {"ConnectionRefusedError", "ConnectionRefused", "ECONNREFUSED"}: return "CONNECTION_REFUSED"
    if error in {"TimeoutError", "Timeout", "SocketTimeoutException"}: return "OPERATION_TIMEOUT"
    event = fields.get("event.name")
    known = {"deployment":"DEPLOYMENT_EVENT", "configuration_change":"CONFIGURATION_EVENT",
             "restart":"RESTART_EVENT", "oom":"OOM_EVENT"}.get(event)
    if known: return known
    code = fields.get("http.response.status_code")
    if error or event == "error" or (type(code) is int and code >= 400): return "OTHER_ERROR"
    return None  # A version string or an HTTP 200 alone is not an error.


def assistant_projection(values):
    """No raw messages, source IDs, versions, hashes or exception identifiers."""
    if values.get("assistant_categories_enabled") is not True:
        return None
    state, status = values.get("state"), values.get("source_status")
    if state not in {"OBSERVED", "NOT_OBSERVED", "UNAVAILABLE"} or status not in {"available", "truncated", "unavailable", "not_configured"}:
        raise ValueError("INVALID_CONTEXT_STATE")
    categories = values.get("categories", [])
    if not isinstance(categories, list) or len(categories) > len(CATEGORIES) or any(not isinstance(c, str) or c not in CATEGORIES for c in categories):
        raise ValueError("INVALID_CONTEXT_CATEGORY")
    counts = {k: values.get(k, 0) for k in ("record_count", "unsupported_entries")}
    if any(type(v) is not int or not 0 <= v <= 100 for v in counts.values()):
        raise ValueError("INVALID_CONTEXT_COUNT")
    return {"state":state, "source_status":status, "categories":sorted(set(categories)), **counts,
            "assistant_categories_enabled": True,
            "coverage":"RETENTION_SAMPLING_AND_DELIVERY_UNKNOWN",
            "interval_semantics":"START_INCLUSIVE_END_EXCLUSIVE",
            "meaning":"SOURCE_ASSERTIONS_SUGGEST_CHECKS_NOT_CAUSAL_PROOF"}


def attach_context(catalog, config, rows):
    """Independent evidence only: never read or alter candidate ranks/features."""
    result = copy.deepcopy(catalog)
    result["catalog_version"] = "evidence-v3-incident-context"
    statuses = {}
    for service in sorted(result["services"]):
        row = rows.get(service, {"status":"unavailable", "reason":"SOURCE_PROBE_FAILED", "records":[]}) if service in config["services"] else {"status":"not_configured", "records":[]}
        status = row["status"]
        records = row.get("records", [])
        values = {"state":"UNAVAILABLE" if status in {"unavailable", "not_configured"} else "OBSERVED" if records else "NOT_OBSERVED",
            "source_status":status, "source_id":config["source_id"], "records":records,
            "categories":sorted({c for record in records if (c := category(record["fields"])) is not None}),
            "record_count":len(records), "unsupported_entries":row.get("unstructured_or_unsupported_entries", 0),
            "reason":row.get("reason"), "observed_at_unix":row.get("observed_at_unix"),
            "assistant_categories_enabled":config.get("assistant_categories", False),
            "coverage":"RETENTION_SAMPLING_AND_DELIVERY_UNKNOWN",
            "interval_semantics":"START_INCLUSIVE_END_EXCLUSIVE",
            "meaning":"SOURCE_ASSERTIONS_SUGGEST_CHECKS_NOT_CAUSAL_PROOF"}
        fact = {"service":service, "kind":"context", "start_unix":result["start_unix"],
                "end_unix":result["end_unix"], "values":values, "source_links":[]}
        fact["id"] = "obs-"+hashlib.sha256(json.dumps(fact,sort_keys=True,allow_nan=False).encode()).hexdigest()[:32]
        result["observations"].append(fact)
        statuses[service] = status
    result["source_quality"]["incident_context"] = {"services":statuses,
        "assistant_categories_enabled":config.get("assistant_categories", False),
        "raw_fields_disclosure":"LOCAL_ONLY"}
    result["limitations"].append("CONTEXT_IS_BOUNDED_SOURCE_ASSERTIONS_NOT_PROOF")
    return result
