"""Bounded, per-installation result reuse and identical-request coalescing.

One computation, at most one joining request, no unbounded request queue. Errors
and degraded source responses are never cached; no stale-on-error fallback.
Keys are supplied from the full project/profile/baseline/access binding.
"""

from collections import OrderedDict
import json
import threading
import time

from api_errors import ApiError


class AnalysisRequests:
    def __init__(self, *, ttl=15, byte_limit=16 * 1024 * 1024, entries=4):
        self.ttl, self.byte_limit, self.entries = ttl, byte_limit, entries
        self._lock = threading.Lock()
        self._cache = OrderedDict()
        self._pending = None
        self._deleted = {}

    def delete(self, analysis_id):
        with self._lock:
            now = time.monotonic()
            self._deleted = {
                k: expiry for k, expiry in self._deleted.items() if expiry > now
            }
            self._deleted[analysis_id] = now + 125 + self.ttl
            while len(self._deleted) > 256:
                del self._deleted[next(iter(self._deleted))]
            self._cache = OrderedDict(
                (k, v)
                for k, v in self._cache.items()
                if json.loads(v[1]).get("result_id") != analysis_id
            )

    def _delivery(self, payload, *, cached, shared):
        value = json.loads(payload)
        collected = value.get("source_status", {}).get("collected_at_unix")
        value["delivery"] = {
            "cache_hit": cached,
            "joined_inflight": shared,
            "cache_ttl_seconds": self.ttl,
            "source_age_seconds": max(0.0, time.time() - collected)
            if collected is not None
            else None,
        }
        return value

    def run(self, key, compute, *, refresh=False):
        with self._lock:
            now = time.monotonic()
            self._cache = OrderedDict(
                (k, v) for k, v in self._cache.items() if v[0] > now
            )
            cached = self._cache.get(key)
            if cached is not None and not refresh:
                self._cache.move_to_end(key)
                return self._delivery(cached[1], cached=True, shared=False)
            if refresh:
                self._cache.pop(key, None)
            pending = self._pending
            if pending is not None:
                if pending["key"] != key or pending["joined"]:
                    raise ApiError(
                        "REQUEST_BUSY",
                        "Выполняется другой анализ. Повторите после его завершения.",
                        429,
                    )
                pending["joined"] = True
                owner = False
            else:
                pending = {"key": key, "event": threading.Event(), "joined": False}
                self._pending = pending
                owner = True
        if not owner:
            if not pending["event"].wait(125):
                raise TimeoutError(
                    "identical analysis did not finish within the collection budget"
                )
            if "error" in pending:
                raise pending["error"]
            return self._delivery(pending["payload"], cached=False, shared=True)
        try:
            value = compute()
            payload = json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
            pending["payload"] = payload
            status = value.get("source_status", {})
            usable = (
                status.get("metrics") == "available"
                and status.get("traces") == "available"
                and not status.get("annotations")
            )
            families = status.get("metric_families_by_service", {})
            points = status.get("metric_point_coverage", {})
            usable = (
                usable
                and bool(families)
                and all(len(v) == 4 for v in families.values())
            )
            usable = (
                usable
                and bool(points)
                and all(p >= 0.8 for v in points.values() for p in v.values())
            )
            usable = usable and status.get("span_count",0) > 0
            with self._lock:
                if (
                    usable
                    and len(payload) <= self.byte_limit
                    and value.get("result_id") not in self._deleted
                ):
                    self._cache[key] = (time.monotonic() + self.ttl, payload)
                    self._cache.move_to_end(key)
                    while (
                        len(self._cache) > self.entries
                        or sum(len(v[1]) for v in self._cache.values())
                        > self.byte_limit
                    ):
                        self._cache.popitem(last=False)
            return self._delivery(payload, cached=False, shared=False)
        except BaseException as error:
            pending["error"] = error
            raise
        finally:
            with self._lock:
                self._pending = None
                pending["event"].set()
