"""Bounded read-only structured context source; never part of ML inputs.

Operator-owned configuration fixes the source and service mapping. Raw bodies,
arbitrary labels and credentials are never emitted. This is not a universal log
scrubber; selected error identifiers can still be sensitive. No external LLM
disclosure is enabled by this probe.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import math
import multiprocessing
import os
from queue import Empty
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

MAX_BYTES = 256 * 1024
MAX_LINE_BYTES = 8192
MAX_RECORDS = 100
LABEL = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,127}\Z")
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
EVENTS = {"deployment", "configuration_change", "restart", "oom", "error"}


class ContextError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ContextError("REDIRECT_NOT_ALLOWED")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ContextError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContextError("NONFINITE_JSON")))
    except (ValueError, UnicodeError, RecursionError):
        raise ContextError("INVALID_JSON") from None


def _stamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContextError("INVALID_INTERVAL")
    try:
        valid = math.isfinite(value) and 0 < value < 10**11
    except OverflowError:
        valid = False
    if not valid:
        raise ContextError("INVALID_INTERVAL")
    return int(Decimal(str(value)) * 1_000_000_000)


def _identifier(value):
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else None


class LokiContextSource:
    def __init__(self, config, *, opener=None, clock=time.monotonic, wall_clock=time.time):
        required = {"source_id", "url", "service_label", "services", "labels"}
        if not isinstance(config, dict) or not required <= set(config) or set(config) - required - {"token_env", "assistant_categories"}:
            raise ContextError("INVALID_SOURCE_CONFIG")
        if type(config.get("assistant_categories", False)) is not bool:
            raise ContextError("INVALID_DISCLOSURE_CONFIG")
        source_id, url = config["source_id"], config["url"]
        if not _identifier(source_id) or not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 for c in url):
            raise ContextError("INVALID_SOURCE_CONFIG")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise ContextError("INVALID_SOURCE_URL") from None
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or (port is not None and port <= 0):
            raise ContextError("INVALID_SOURCE_URL")
        label, services, labels = config["service_label"], config["services"], config["labels"]
        if not isinstance(label, str) or not LABEL.fullmatch(label):
            raise ContextError("INVALID_SERVICE_LABEL")
        if not isinstance(services, dict) or not 1 <= len(services) <= 20:
            raise ContextError("INVALID_INVENTORY")
        if not isinstance(labels, dict) or len(labels) > 8 or label in labels:
            raise ContextError("INVALID_LABEL_SCOPE")
        for key, value in services.items():
            if not _identifier(key) or not isinstance(value, str) or not value or len(value) > 128:
                raise ContextError("INVALID_INVENTORY")
        for key, value in labels.items():
            if not isinstance(key, str) or not LABEL.fullmatch(key) or not isinstance(value, str) or not value or len(value) > 128:
                raise ContextError("INVALID_LABEL_SCOPE")
        token_env = config.get("token_env")
        if token_env is not None and (not isinstance(token_env, str) or not LABEL.fullmatch(token_env)):
            raise ContextError("INVALID_AUTH_CONFIG")
        if token_env and parts.scheme != "https" and parts.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ContextError("AUTH_REQUIRES_TLS")
        self.source_id, self.url = source_id, url.rstrip("/")
        self.label, self.services, self.labels = label, dict(services), dict(labels)
        self.token_env = token_env
        self.opener = opener or build_opener(NoRedirect())
        self.clock, self.wall_clock = clock, wall_clock

    def collect(self, service, start, end, *, limit=MAX_RECORDS):
        if not isinstance(service, str) or service not in self.services:
            raise ContextError("SERVICE_OUTSIDE_INSTALLED_SCOPE")
        left, right = _stamp(start), _stamp(end)
        if not 0 < right - left <= 3600 * 1_000_000_000 or end > self.wall_clock():
            raise ContextError("INVALID_INTERVAL")
        if type(limit) is not int or not 1 <= limit <= MAX_RECORDS:
            raise ContextError("INVALID_LIMIT")
        scope = self.labels | {self.label: self.services[service]}
        selector = "{" + ",".join(key + "=" + json.dumps(value, ensure_ascii=False) for key, value in sorted(scope.items())) + "}"
        query = urlencode({"query": selector, "start": str(left), "end": str(right),
                           "limit": limit, "direction": "forward"})
        envelope = {"schema_version": "context-source-v1",
                    "assistant_disclosure": "RAW_FIELDS_LOCAL_ONLY",
                    "source_id": self.source_id, "service": service,
                    "start_unix": start, "end_unix": end,
                    "interval_semantics": "START_INCLUSIVE_END_EXCLUSIVE",
                    "coverage": "BACKEND_RETENTION_AND_SAMPLING_UNKNOWN",
                    "status": "unavailable", "records": [],
                    "meaning": "SOURCE_ASSERTIONS_NOT_VERIFIED_CAUSAL_FACTS"}
        headers = {"Accept": "application/json"}
        if self.token_env:
            token = os.environ.get(self.token_env)
            if not token or "\r" in token or "\n" in token:
                return envelope | {"reason": "SOURCE_AUTH_UNAVAILABLE"}
            headers["Authorization"] = "Bearer " + token
        try:
            deadline = self.clock() + 5
            with self.opener.open(Request(self.url + "/loki/api/v1/query_range?" + query, headers=headers), timeout=5) as response:
                if response.status != 200:
                    raise ContextError("UNUSABLE_HTTP_STATUS")
                if response.headers.get_content_type() != "application/json":
                    raise ContextError("UNEXPECTED_CONTENT_TYPE")
                chunks, size = [], 0
                while True:
                    if self.clock() >= deadline:
                        raise ContextError("SOURCE_TIMEOUT")
                    read = getattr(response, "read1", response.read)
                    chunk = read(min(16 * 1024, MAX_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk); size += len(chunk)
                    if size > MAX_BYTES:
                        raise ContextError("SOURCE_BYTE_LIMIT")
                data = _json(b"".join(chunks))
            records, seen, skipped = self._normalize(data, service, scope, left, right, limit)
            return envelope | {"status": "truncated" if seen >= limit else "available",
                               "records": records, "entries_seen": seen,
                               "unstructured_or_unsupported_entries": skipped,
                               "observed_at_unix": self.wall_clock(),
                               "completeness": "NOT_ESTABLISHED"}
        except HTTPError as error:
            error.close()
            return envelope | {"reason": "SOURCE_HTTP_ERROR", "http_status": error.code}
        except (URLError, OSError, TimeoutError):
            return envelope | {"reason": "SOURCE_UNAVAILABLE"}
        except ContextError as error:
            return envelope | {"reason": str(error)}

    def _normalize(self, data, service, scope, left, right, limit):
        if not isinstance(data, dict) or data.get("status") != "success" or data.get("warnings") or data.get("errors"):
            raise ContextError("UNUSABLE_SOURCE_RESPONSE")
        body = data.get("data")
        if not isinstance(body, dict) or body.get("resultType") != "streams" or not isinstance(body.get("result"), list):
            raise ContextError("UNEXPECTED_RESULT_TYPE")
        records, seen, skipped, identities = [], 0, 0, set()
        for stream in body["result"]:
            if not isinstance(stream, dict) or not isinstance(stream.get("stream"), dict) or not isinstance(stream.get("values"), list):
                raise ContextError("INVALID_STREAM")
            if any(stream["stream"].get(key) != value for key, value in scope.items()):
                raise ContextError("STREAM_OUTSIDE_INSTALLED_SCOPE")
            for entry in stream["values"]:
                seen += 1
                if seen > limit:
                    raise ContextError("SOURCE_RECORD_LIMIT")
                if not isinstance(entry, list) or len(entry) < 2 or not isinstance(entry[0], str) or not re.fullmatch(r"[0-9]{1,20}", entry[0]) or not isinstance(entry[1], str):
                    raise ContextError("INVALID_LOG_ENTRY")
                stamp, line = int(entry[0]), entry[1]
                if not left <= stamp < right:
                    raise ContextError("ENTRY_OUTSIDE_REQUESTED_INTERVAL")
                if len(line.encode()) > MAX_LINE_BYTES:
                    skipped += 1
                    continue
                try:
                    fields = _json(line)
                except ContextError:
                    skipped += 1
                    continue
                if not isinstance(fields, dict):
                    skipped += 1
                    continue
                selected = {}
                for key in ("error.type", "exception.type", "service.version"):
                    value = _identifier(fields.get(key))
                    if value:
                        selected[key] = value
                event = fields.get("event.name")
                if isinstance(event, str) and event in EVENTS:
                    selected["event.name"] = event
                code = fields.get("http.response.status_code")
                if type(code) is int and 100 <= code <= 599:
                    selected["http.response.status_code"] = code
                if not selected:
                    skipped += 1
                    continue
                origin_hash = hashlib.sha256(line.encode()).hexdigest()
                identity = (stamp, origin_hash)
                if identity in identities:
                    continue
                identities.add(identity)
                identifier = hashlib.sha256(json.dumps([self.source_id, service, stamp, origin_hash, selected], sort_keys=True).encode()).hexdigest()[:32]
                records.append({"id": "ctx-" + identifier, "service": service,
                                "source_timestamp_ns": str(stamp),
                                "timestamp_semantics": "LOKI_ENTRY_TIME_EVENT_CLOCK_NOT_VERIFIED",
                                "source_line_sha256": origin_hash, "fields": selected})
        return sorted(records, key=lambda r: (int(r["source_timestamp_ns"]), r["id"])), seen, skipped


def _worker(config, service, start, end, results):
    try:
        results.put(LokiContextSource(config).collect(service, start, end))
    except Exception:
        results.put({"schema_version": "context-source-v1",
                     "status": "unavailable", "reason": "SOURCE_PROBE_FAILED", "records": [],
                     "assistant_disclosure": "RAW_FIELDS_LOCAL_ONLY"})


def bounded_probe(config, service, start, end, *, timeout=10):
    """One disposable child bounds DNS, headers and slow-drip I/O as a whole.

    A socket idle timeout alone is not a wall-clock deadline. No unbounded pool
    or retry is started, and the child has no mutation/provider tools.
    """
    if not 0 < timeout <= 10:
        raise ContextError("INVALID_PROBE_DEADLINE")
    context = multiprocessing.get_context("spawn")
    results = context.Queue(maxsize=1)
    worker = context.Process(target=_worker, args=(config, service, start, end, results), daemon=True)
    worker.start()
    try:
        return results.get(timeout=timeout)
    except Empty:
        return {"schema_version": "context-source-v1",
                "status": "unavailable", "reason": "SOURCE_DEADLINE_EXCEEDED", "records": [],
                "assistant_disclosure": "RAW_FIELDS_LOCAL_ONLY"}
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(2)
        if worker.is_alive():
            worker.kill(); worker.join(2)
        results.close(); results.join_thread()


def _batch_worker(config, services, start, end, results):
    rows = {}
    try:
        source = LokiContextSource(config)
        remaining = MAX_RECORDS
        for service in sorted(services):
            if remaining <= 0:
                rows[service] = {"status": "unavailable", "reason": "GLOBAL_RECORD_LIMIT", "records": []}
                continue
            rows[service] = source.collect(service, start, end, limit=remaining)
            remaining -= rows[service].get("entries_seen", 0)
        results.put(rows)
    except Exception:
        results.put({service: {"status": "unavailable", "reason": "SOURCE_PROBE_FAILED", "records": []}
                     for service in services})


def collect_context(config, services, start, end, *, timeout=10):
    """One process/total deadline; at most 20 queries and 100 total entries.

    Inventory ordering is independent of rank. On timeout the whole batch is
    unavailable, never misrepresented as a complete partial collection.
    """
    selected = sorted(set(services) & set(config["services"]))
    if not selected:
        return {}
    context = multiprocessing.get_context("spawn")
    results = context.Queue(maxsize=1)
    worker = context.Process(target=_batch_worker, args=(config, selected, start, end, results), daemon=True)
    worker.start()
    try:
        return results.get(timeout=timeout)
    except Empty:
        return {service: {"status": "unavailable", "reason": "SOURCE_DEADLINE_EXCEEDED", "records": []}
                for service in selected}
    finally:
        if worker.is_alive(): worker.terminate()
        worker.join(2)
        if worker.is_alive(): worker.kill(); worker.join(2)
        results.close(); results.join_thread()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--start", type=float, required=True, help="Unix seconds UTC")
    parser.add_argument("--end", type=float, required=True, help="Exclusive end, Unix seconds UTC")
    args = parser.parse_args()
    try:
        with open(args.config, "rb") as source:
            config = source.read(64 * 1024 + 1)
        if len(config) > 64 * 1024:
            raise ContextError("CONFIG_BYTE_LIMIT")
        config = _json(config)
        LokiContextSource(config)  # Configuration validation before child creation.
        result = bounded_probe(config, args.service, args.start, args.end)
    except (ContextError, OSError) as error:
        parser.exit(2, str(error) if isinstance(error, ContextError) else "SOURCE_CONFIG_UNAVAILABLE")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
