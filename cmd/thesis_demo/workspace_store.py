"""One-installation SQLite workspace, bounded retention and object scope.

No credentials, raw spans, model reasoning or research labels belong here.
SQLite is on a private local volume, not an NFS share or a tenant isolation API.
"""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
import uuid

SCHEMA_VERSION = 3
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_OUTCOME_BYTES = 128 * 1024
TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}
ACTIVE = {"queued", "running", "cancelling"}


class StoreError(ValueError):
    pass


def pack(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest(value):
    return hashlib.sha256(pack(value).encode()).hexdigest()


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise StoreError("STORE_IDENTIFIER_INVALID")
    return value


def _text(value, maximum=2000, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
    ):
        raise StoreError("STORE_TEXT_INVALID")
    return value


class WorkspaceStore:
    def __init__(
        self,
        directory,
        *,
        retention_seconds=7 * 86400,
        max_snapshots=128,
        max_investigations=256,
        max_bytes=64 * 1024 * 1024,
        assistant_daily_jobs=20,
        clock=time.time,
    ):
        self.directory = Path(directory).absolute()
        if self.directory.is_symlink():
            raise StoreError("STORE_DIRECTORY_UNSAFE")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.stat()
        if (
            info.st_uid != os.getuid()
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise StoreError("STORE_DIRECTORY_UNSAFE")
        if (
            not 60 <= retention_seconds <= 30 * 86400
            or not 1 <= max_snapshots <= 1000
            or not 1 <= max_investigations <= 2000
            or not 1024 <= max_bytes <= 128 * 1024 * 1024
            or type(assistant_daily_jobs) is not int
            or not 1 <= assistant_daily_jobs <= 200
        ):
            raise StoreError("STORE_LIMIT_INVALID")
        self.retention, self.max_snapshots = retention_seconds, max_snapshots
        self.max_investigations, self.max_bytes, self.clock = (
            max_investigations,
            max_bytes,
            clock,
        )
        self.path = self.directory / "workspace.sqlite3"
        self.assistant_daily_jobs = assistant_daily_jobs
        self.lock = threading.RLock()
        try:
            fd = os.open(
                self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
        except FileExistsError:
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_nlink != 1
            ):
                raise StoreError("STORE_DATABASE_UNSAFE") from None
        with self._db(write=True) as db, ExitStack() as guards:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2, SCHEMA_VERSION}:
                raise StoreError("STORE_SCHEMA_UNSUPPORTED")
            if version < SCHEMA_VERSION:
                guards.enter_context(self._migration_guard())
            if version == 0:
                db.execute(
                    "CREATE TABLE snapshots (id TEXT PRIMARY KEY, project TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, payload TEXT NOT NULL, sha TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE investigations (id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE, idempotency_key TEXT NOT NULL, request_sha TEXT NOT NULL, request TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, outcome TEXT, revision INTEGER NOT NULL DEFAULT 0, record TEXT NOT NULL, UNIQUE(analysis_id,idempotency_key))"
                )
                db.execute(
                    "CREATE INDEX investigation_analysis ON investigations(analysis_id)"
                )
                db.execute("PRAGMA user_version=1")
            if version < 2:
                db.execute(
                    "CREATE TABLE investigation_turns (investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE, number INTEGER NOT NULL, idempotency_key TEXT NOT NULL, request_sha TEXT NOT NULL, request TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, outcome TEXT, PRIMARY KEY(investigation_id,number), UNIQUE(investigation_id,idempotency_key))"
                )
                db.execute(
                    "INSERT INTO investigation_turns SELECT id,1,idempotency_key,request_sha,request,state,created,updated,outcome FROM investigations"
                )
                db.execute("PRAGMA user_version=2")
            if version < 3:
                # No FK: deleting an investigation must not reset the daily
                # allowance. Only opaque job keys/timestamps, never its text.
                db.execute(
                    "CREATE TABLE assistant_reservations (job TEXT PRIMARY KEY, created REAL NOT NULL)"
                )
                cutoff = self.clock() - 86400
                rows = db.execute(
                    "SELECT investigation_id,number,request,created FROM investigation_turns WHERE created>?",
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    if json.loads(row["request"]).get("mode") != "B":
                        db.execute(
                            "INSERT INTO assistant_reservations VALUES(?,?)",
                            (f"{row['investigation_id']}:{row['number']}", row["created"]),
                        )
                db.execute("PRAGMA user_version=3")

    @contextmanager
    def _migration_guard(self):
        # An older running worker would not reserve its future LLM jobs. Do
        # not migrate under it, even though ordinary SQLite writes serialize.
        fd = os.open(self.directory / "worker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise StoreError("STORE_MIGRATION_LOCK_UNSAFE")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StoreError("STORE_MIGRATION_WORKSPACE_RUNNING") from None
            yield
        finally:
            os.close(fd)

    @contextmanager
    def _db(self, *, write=False):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=3, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                db.execute("PRAGMA secure_delete=ON")
                db.execute("PRAGMA max_page_count=32768")
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db
                db.execute("COMMIT")
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
            finally:
                db.close()

    def _purge(self, db):
        db.execute("DELETE FROM snapshots WHERE expires<=?", (self.clock(),))
        db.execute(
            "DELETE FROM assistant_reservations WHERE created<=?", (self.clock() - 86400,)
        )

    def _reserve_assistant(self, db, job, request):
        if request.get("mode") == "B":
            return
        count = db.execute(
            "SELECT COUNT(*) FROM assistant_reservations WHERE created>?",
            (self.clock() - 86400,),
        ).fetchone()[0]
        if count >= self.assistant_daily_jobs:
            raise StoreError("STORE_ASSISTANT_DAILY_LIMIT")
        db.execute("INSERT INTO assistant_reservations VALUES(?,?)", (job, self.clock()))

    def assistant_budget_status(self):
        with self._db() as db:
            count, oldest = db.execute(
                "SELECT COUNT(*),MIN(created) FROM assistant_reservations WHERE created>?",
                (self.clock() - 86400,),
            ).fetchone()
            return {
                "window_seconds": 86400,
                "limit_jobs": self.assistant_daily_jobs,
                "reserved_jobs": count,
                "remaining_jobs": max(0, self.assistant_daily_jobs - count),
                "next_expiry_unix": oldest + 86400 if oldest is not None else None,
                "basis": "RESERVED_JOBS_NOT_TOKEN_USAGE_OR_INVOICE",
            }

    def _used(self, db):
        total = 0
        for table, columns in (
            ("snapshots", ("payload",)),
            ("investigations", ("request", "outcome", "record")),
            ("investigation_turns", ("request", "outcome")),
        ):
            for column in columns:
                total += db.execute(
                    f"SELECT COALESCE(SUM(LENGTH(CAST({column} AS BLOB))),0) FROM {table}"
                ).fetchone()[0]
        active = db.execute(
            "SELECT COUNT(*) FROM investigations WHERE state IN ('queued','running','cancelling')"
        ).fetchone()[0]
        return total + active * MAX_OUTCOME_BYTES * 2

    def put_snapshot(self, catalog, analysis, *, project):
        _identifier(project)
        identifier = _identifier(catalog["analysis_id"])
        if (
            identifier != analysis["result_id"]
            or catalog["input_sha256"] != analysis["input_sha256"]
            or set(catalog["services"])
            != {r["service"] for r in analysis["candidates"]}
        ):
            raise StoreError("STORE_SNAPSHOT_MISMATCH")
        # Only application-owned projections, not the uploaded raw window.
        payload = pack({"catalog": catalog, "analysis": analysis})
        size = len(payload.encode())
        if size > MAX_SNAPSHOT_BYTES:
            raise StoreError("STORE_SNAPSHOT_BUDGET")
        sha = hashlib.sha256(payload.encode()).hexdigest()
        with self._db(write=True) as db:
            self._purge(db)
            existing = db.execute(
                "SELECT sha,project FROM snapshots WHERE id=?", (identifier,)
            ).fetchone()
            if existing:
                if existing["sha"] != sha or existing["project"] != project:
                    raise StoreError("STORE_IMMUTABLE_SNAPSHOT")
                return identifier
            count = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            used = self._used(db)
            if count >= self.max_snapshots or used + size > self.max_bytes:
                raise StoreError("STORE_CAPACITY")
            now = self.clock()
            db.execute(
                "INSERT INTO snapshots VALUES(?,?,?,?,?,?)",
                (identifier, project, now, now + self.retention, payload, sha),
            )
        return identifier

    def get_snapshot(self, identifier, *, project=None):
        _identifier(identifier)
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM snapshots WHERE id=? AND expires>?",
                (identifier, self.clock()),
            ).fetchone()
            if row is None or (project is not None and project != row["project"]):
                return None
            if hashlib.sha256(row["payload"].encode()).hexdigest() != row["sha"]:
                raise StoreError("STORE_SNAPSHOT_CORRUPT")
            return json.loads(row["payload"]) | {
                "project": row["project"],
                "expires_at_unix": row["expires"],
                "snapshot_sha256": row["sha"],
            }

    def create_investigation(self, analysis_id, request, *, idempotency_key):
        _identifier(analysis_id)
        _identifier(idempotency_key)
        text = pack(request)
        if len(text.encode()) > 8192:
            raise StoreError("STORE_REQUEST_BUDGET")
        request_sha = digest(request)
        with self._db(write=True) as db:
            self._purge(db)
            if not db.execute(
                "SELECT 1 FROM snapshots WHERE id=?", (analysis_id,)
            ).fetchone():
                raise StoreError("STORE_SNAPSHOT_NOT_FOUND")
            old = db.execute(
                "SELECT id,request_sha FROM investigations WHERE analysis_id=? AND idempotency_key=?",
                (analysis_id, idempotency_key),
            ).fetchone()
            if old:
                if old["request_sha"] != request_sha:
                    raise StoreError("STORE_IDEMPOTENCY_CONFLICT")
                return old["id"], False
            if (
                db.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
                >= self.max_investigations
            ):
                raise StoreError("STORE_CAPACITY")
            if (
                self._used(db) + len(text.encode()) * 2 + MAX_OUTCOME_BYTES * 2 + 32768
                > self.max_bytes
            ):
                raise StoreError("STORE_CAPACITY")
            identifier, now = str(uuid.uuid4()), self.clock()
            self._reserve_assistant(db,f"{identifier}:1",request)
            record = {
                "title": "",
                "symptoms": "",
                "impact": "",
                "timeline": [],
                "causes": [],
                "action_items": [],
                "conclusion": "",
            }
            db.execute(
                "INSERT INTO investigations(id,analysis_id,idempotency_key,request_sha,request,state,created,updated,record) VALUES(?,?,?,?,?,'queued',?,?,?)",
                (
                    identifier,
                    analysis_id,
                    idempotency_key,
                    request_sha,
                    text,
                    now,
                    now,
                    pack(record),
                ),
            )
            db.execute(
                "INSERT INTO investigation_turns VALUES(?,1,?,?,?,'queued',?,?,NULL)",
                (identifier, idempotency_key, request_sha, text, now, now),
            )
            return identifier, True

    def add_turn(self, identifier, request, *, idempotency_key):
        _identifier(identifier)
        _identifier(idempotency_key)
        text = pack(request)
        if len(text.encode()) > 8192:
            raise StoreError("STORE_REQUEST_BUDGET")
        sha = digest(request)
        with self._db(write=True) as db:
            self._purge(db)
            current = db.execute(
                "SELECT state FROM investigations WHERE id=?", (identifier,)
            ).fetchone()
            if current is None:
                raise StoreError("STORE_INVESTIGATION_NOT_FOUND")
            old = db.execute(
                "SELECT number,request_sha FROM investigation_turns WHERE investigation_id=? AND idempotency_key=?",
                (identifier, idempotency_key),
            ).fetchone()
            if old:
                if old["request_sha"] != sha:
                    raise StoreError("STORE_IDEMPOTENCY_CONFLICT")
                return old["number"], False
            if current["state"] in ACTIVE:
                raise StoreError("STORE_TURN_IN_PROGRESS")
            number = db.execute(
                "SELECT COALESCE(MAX(number),0)+1 FROM investigation_turns WHERE investigation_id=?",
                (identifier,),
            ).fetchone()[0]
            if number > 10:
                raise StoreError("STORE_TURN_LIMIT")
            if (
                self._used(db) + len(text.encode()) + MAX_OUTCOME_BYTES * 2
                > self.max_bytes
            ):
                raise StoreError("STORE_CAPACITY")
            now = self.clock()
            self._reserve_assistant(db,f"{identifier}:{number}",request)
            db.execute(
                "INSERT INTO investigation_turns VALUES(?,?,?,?,?,'queued',?,?,NULL)",
                (identifier, number, idempotency_key, sha, text, now, now),
            )
            db.execute(
                "UPDATE investigations SET state='queued',outcome=NULL,updated=? WHERE id=?",
                (now, identifier),
            )
            return number, True

    def find_idempotent(self, analysis_id, request, *, idempotency_key):
        _identifier(analysis_id)
        _identifier(idempotency_key)
        with self._db() as db:
            row = db.execute(
                "SELECT i.id,i.request_sha FROM investigations i JOIN snapshots s ON s.id=i.analysis_id WHERE i.analysis_id=? AND i.idempotency_key=? AND s.expires>?",
                (analysis_id, idempotency_key, self.clock()),
            ).fetchone()
            if row is None:
                return None
            if row["request_sha"] != digest(request):
                raise StoreError("STORE_IDEMPOTENCY_CONFLICT")
            return row["id"]

    def find_turn_idempotent(self, identifier, request, *, idempotency_key):
        _identifier(identifier)
        _identifier(idempotency_key)
        with self._db() as db:
            old = db.execute(
                "SELECT number,request_sha FROM investigation_turns WHERE investigation_id=? AND idempotency_key=?",
                (identifier, idempotency_key),
            ).fetchone()
            if old is None:
                return None
            if old["request_sha"] != digest(request):
                raise StoreError("STORE_IDEMPOTENCY_CONFLICT")
            return old["number"]

    def list_investigations(self, *, project=None, limit=30, service=None,
                            category=None, after=None, before=None, action_status=None):
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise StoreError("STORE_LIST_LIMIT_INVALID")
        if project is not None:
            _identifier(project)
        if service is not None:
            _text(service, 200)
        if category is not None:
            _text(category, 100)
        for value in (after, before):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or not 0 <= value <= 253402300799):
                raise StoreError("STORE_HISTORY_FILTER_INVALID")
        if after is not None and before is not None and after > before:
            raise StoreError("STORE_HISTORY_FILTER_INVALID")
        if action_status not in {None, "proposed", "planned", "in_progress",
                                 "verification_pending", "verified", "not_verified", "overdue"}:
            raise StoreError("STORE_HISTORY_FILTER_INVALID")
        with self._db() as db:
            rows = db.execute(
                "SELECT i.id,i.analysis_id,s.project,i.state,i.created,i.updated,i.record FROM investigations i JOIN snapshots s ON s.id=i.analysis_id WHERE s.expires>? AND (? IS NULL OR s.project=?) AND (? IS NULL OR i.created>=?) AND (? IS NULL OR i.created<=?) ORDER BY i.updated DESC,i.id",
                (self.clock(), project, project, after, after, before, before),
            ).fetchall()
            result = []
            for row in rows:
                record = json.loads(row["record"])
                actions = record["action_items"]
                # Human-entered hypotheses/actions only, never the ML rank or
                # full candidate inventory. A hypothesis is not confirmation.
                mentioned = {i["service"] for i in record["causes"]} | {
                    i["service"] for i in actions if i.get("service")}
                metadata = record.get("metadata", {})
                if service is not None and service not in mentioned:
                    continue
                if category is not None and metadata.get("category", "") != category:
                    continue
                matching = actions if service is None else [a for a in actions if a.get("service") == service]
                overdue = lambda a: a["due_unix"] is not None and a["due_unix"] < self.clock() and a["status"] in {"planned", "in_progress", "verification_pending"}
                if action_status is not None and not any(
                    overdue(a) if action_status == "overdue" else a["status"] == action_status for a in matching):
                    continue
                result.append({k: row[k] for k in ("id", "analysis_id", "project", "state", "created", "updated")} | {
                    "title": record["title"], "category": metadata.get("category", ""),
                    "mentioned_services": sorted(mentioned),
                    "confirmed_services": sorted({c["service"] for c in record["causes"] if c["status"] == "confirmed"}),
                    "action_count": len(actions), "overdue_action_count": sum(overdue(a) for a in actions),
                })
                if len(result) >= limit:
                    break
            return result

    def purge_expired(self):
        with self._db(write=True) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM snapshots WHERE expires<=?", (self.clock(),)
            ).fetchone()[0]
            self._purge(db)
            return count

    def get_investigation(self, identifier):
        _identifier(identifier)
        with self._db() as db:
            row = db.execute(
                "SELECT i.*,s.project,s.expires FROM investigations i JOIN snapshots s ON s.id=i.analysis_id WHERE i.id=? AND s.expires>?",
                (identifier, self.clock()),
            ).fetchone()
            if row is None:
                return None
            result = {
                k: row[k]
                for k in (
                    "id",
                    "analysis_id",
                    "project",
                    "state",
                    "created",
                    "updated",
                    "revision",
                )
            }
            result.update(
                {
                    k: json.loads(row[k]) if row[k] is not None else None
                    for k in ("request", "outcome", "record")
                }
            )
            turns = db.execute(
                "SELECT * FROM investigation_turns WHERE investigation_id=? ORDER BY number",
                (identifier,),
            ).fetchall()
            result["turns"] = [
                {k: t[k] for k in ("number", "state", "created", "updated")}
                | {
                    "request": json.loads(t["request"]),
                    "outcome": json.loads(t["outcome"]) if t["outcome"] else None,
                }
                for t in turns
            ]
            if turns:
                result["request"] = json.loads(turns[-1]["request"])
            return result

    def transition(self, identifier, *, expected, state, outcome=None):
        _identifier(identifier)
        if state not in ACTIVE | TERMINAL or not set(expected) <= ACTIVE | TERMINAL:
            raise StoreError("STORE_STATE_INVALID")
        text = pack(outcome) if outcome is not None else None
        if text is not None and len(text.encode()) > MAX_OUTCOME_BYTES:
            raise StoreError("STORE_OUTCOME_BUDGET")
        with self._db(write=True) as db:
            placeholders = ",".join("?" for _ in expected)
            count = db.execute(
                f"UPDATE investigations SET state=?,updated=?,outcome=COALESCE(?,outcome) WHERE id=? AND state IN ({placeholders})",
                (state, self.clock(), text, identifier, *expected),
            ).rowcount
            if count:
                db.execute(
                    "UPDATE investigation_turns SET state=?,updated=?,outcome=COALESCE(?,outcome) WHERE investigation_id=? AND number=(SELECT MAX(number) FROM investigation_turns WHERE investigation_id=?)",
                    (state, self.clock(), text, identifier, identifier),
                )
            return bool(count)

    def recover_interrupted(self):
        with self._db(write=True) as db:
            outcome = pack(
                {
                    "status": "interrupted",
                    "stop_reason": "APPLICATION_RESTARTED",
                    "report": None,
                    "usage": {"accounting_complete": False},
                    "remote_generation_stopped": "UNKNOWN",
                }
            )
            db.execute(
                "UPDATE investigation_turns SET state='interrupted',updated=?,outcome=? WHERE state IN ('queued','running','cancelling')",
                (self.clock(), outcome),
            )
            return db.execute(
                "UPDATE investigations SET state='interrupted',updated=?,outcome=? WHERE state IN ('queued','running','cancelling')",
                (self.clock(), outcome),
            ).rowcount

    def save_record(self, identifier, record, *, expected_revision):
        current = self.get_investigation(identifier)
        if current is None:
            raise StoreError("STORE_INVESTIGATION_NOT_FOUND")
        snapshot = self.get_snapshot(current["analysis_id"])
        # Approval is server-computed, never accepted from the client or LLM.
        if not isinstance(record, dict):
            raise StoreError("RECORD_FIELDS_INVALID")
        record = json.loads(pack(record))
        record.pop("approval", None)
        validate_record(record, snapshot["catalog"])
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise StoreError("STORE_REVISION_INVALID")
        with self._db(write=True) as db:
            previous = db.execute("SELECT record FROM investigations WHERE id=? AND revision=?",
                                  (identifier, expected_revision)).fetchone()
            if previous is None:
                raise StoreError("STORE_REVISION_CONFLICT")
            approval = json.loads(previous["record"]).get("approval")
            if approval and approval["record_sha256"] == digest(record):
                record["approval"] = approval
            if self._used(db) + len(pack(record).encode()) > self.max_bytes:
                raise StoreError("STORE_CAPACITY")
            updated = db.execute(
                "UPDATE investigations SET record=?,revision=revision+1,updated=? WHERE id=? AND revision=?",
                (pack(record), self.clock(), identifier, expected_revision),
            ).rowcount
            if not updated:
                raise StoreError("STORE_REVISION_CONFLICT")
        return self.get_investigation(identifier)

    def review_record(self, identifier, *, expected_revision):
        _identifier(identifier)
        if type(expected_revision) is not int or expected_revision < 0:
            raise StoreError("STORE_REVISION_INVALID")
        with self._db(write=True) as db:
            row = db.execute("SELECT i.record,s.payload FROM investigations i JOIN snapshots s ON s.id=i.analysis_id WHERE i.id=? AND i.revision=? AND s.expires>?",
                             (identifier,expected_revision,self.clock())).fetchone()
            if row is None:
                raise StoreError("STORE_REVISION_CONFLICT")
            record = json.loads(row["record"])
            record.pop("approval",None)
            validate_record(record,json.loads(row["payload"])["catalog"])
            if not record.get("metadata",{}).get("owner","").strip() or not record["conclusion"].strip():
                raise StoreError("RECORD_REVIEW_OWNER_CONCLUSION_REQUIRED")
            record["approval"]={"record_sha256":digest(record),"reviewed_at_unix":self.clock()}
            if self._used(db)+len(pack(record).encode()) > self.max_bytes:
                raise StoreError("STORE_CAPACITY")
            db.execute("UPDATE investigations SET record=?,revision=revision+1,updated=? WHERE id=? AND revision=?",
                       (pack(record),self.clock(),identifier,expected_revision))
        return self.get_investigation(identifier)

    def delete_snapshot(self, identifier):
        _identifier(identifier)
        with self._db(write=True) as db:
            return bool(
                db.execute("DELETE FROM snapshots WHERE id=?", (identifier,)).rowcount
            )


def validate_record(record, catalog):
    fields = {
        "title",
        "symptoms",
        "impact",
        "timeline",
        "causes",
        "action_items",
        "conclusion",
    }
    if not isinstance(record, dict) or not fields <= set(record) <= fields | {"metadata", "approval"}:
        raise StoreError("RECORD_FIELDS_INVALID")
    if "approval" in record:
        approval = record["approval"]
        body = {k:v for k,v in record.items() if k != "approval"}
        if (not isinstance(approval, dict) or set(approval) != {"record_sha256", "reviewed_at_unix"}
                or approval["record_sha256"] != digest(body)
                or isinstance(approval["reviewed_at_unix"],bool)
                or not isinstance(approval["reviewed_at_unix"],(int,float))
                or not math.isfinite(approval["reviewed_at_unix"])
                or not 0 <= approval["reviewed_at_unix"] <= 253402300799):
            raise StoreError("RECORD_APPROVAL_INVALID")
    if "metadata" in record:
        metadata = record["metadata"]
        if not isinstance(metadata, dict) or set(metadata) != {"owner", "incident", "category"}:
            raise StoreError("RECORD_METADATA_INVALID")
        for key in metadata:
            _text(metadata[key], 100 if key == "category" else 200, empty=True)
    for field in ("title", "symptoms", "impact", "conclusion"):
        _text(record[field], 200 if field == "title" else 2000, empty=True)
    services, ids = set(catalog["services"]), {f["id"] for f in catalog["observations"]}

    def references(items):
        if (
            not isinstance(items, list)
            or len(items) > 24
            or any(not isinstance(i, str) or i not in ids for i in items)
        ):
            raise StoreError("RECORD_EVIDENCE_OUTSIDE_SCOPE")

    def timestamp(value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 253402300799
        ):
            raise StoreError("RECORD_TIME_INVALID")

    for name, maximum in (("timeline", 50), ("causes", 10), ("action_items", 20)):
        if not isinstance(record[name], list) or len(record[name]) > maximum:
            raise StoreError("RECORD_LIST_BUDGET")
    for item in record["timeline"]:
        if not isinstance(item, dict) or set(item) != {
            "time_unix",
            "description",
            "evidence_ids",
        }:
            raise StoreError("RECORD_TIMELINE_INVALID")
        timestamp(item["time_unix"])
        _text(item["description"])
        references(item["evidence_ids"])
    for item in record["causes"]:
        if (
            not isinstance(item, dict)
            or set(item)
            != {"service", "statement", "status", "verification", "evidence_ids"}
            or item["service"] not in services
            or item["status"] not in {"hypothesis", "confirmed", "discarded"}
        ):
            raise StoreError("RECORD_CAUSE_INVALID")
        if item["status"] != "hypothesis" and (
            not isinstance(item["verification"], str)
            or not item["verification"].strip()
        ):
            raise StoreError("RECORD_CAUSE_VERIFICATION_REQUIRED")
        _text(item["statement"])
        _text(item["verification"], empty=item["status"] == "hypothesis")
        references(item["evidence_ids"])
    action_ids = set()
    for item in record["action_items"]:
        keys = {
            "id",
            "title",
            "owner",
            "due_unix",
            "status",
            "importance",
            "effort",
            "verification",
            "evidence_ids",
        }
        extra = {"purpose", "rationale", "verification_plan", "ticket", "service"}
        if not isinstance(item, dict) or not keys <= set(item) <= keys | extra:
            raise StoreError("RECORD_ACTION_INVALID")
        if "purpose" in item and item["purpose"] not in {"mitigation", "corrective", "preventive", "unspecified"}:
            raise StoreError("RECORD_ACTION_PURPOSE_INVALID")
        if "service" in item and item["service"] not in services:
            raise StoreError("RECORD_ACTION_SERVICE_INVALID")
        for key in ("rationale", "verification_plan", "ticket"):
            if key in item:
                _text(item[key], 200 if key == "ticket" else 2000, empty=True)
        _identifier(item["id"])
        if item["id"] in action_ids:
            raise StoreError("RECORD_ACTION_DUPLICATE")
        action_ids.add(item["id"])
        if (
            item["status"]
            not in {
                "proposed",
                "planned",
                "in_progress",
                "verification_pending",
                "verified",
                "not_verified",
            }
            or item["importance"] not in {"low", "normal", "high"}
            or item["effort"] not in {"small", "medium", "large", "unknown"}
        ):
            raise StoreError("RECORD_ACTION_STATUS_INVALID")
        _text(item["title"])
        if item["status"] != "proposed" and (
            not isinstance(item["owner"], str) or not item["owner"].strip()
        ):
            raise StoreError("RECORD_ACTION_OWNER_REQUIRED")
        _text(item["owner"], 200, empty=item["status"] == "proposed")
        if item["due_unix"] is not None:
            timestamp(item["due_unix"])
        elif item["status"] != "proposed":
            raise StoreError("RECORD_ACTION_DUE_REQUIRED")
        if item["status"] in {"verified", "not_verified"} and (
            not isinstance(item["verification"], str)
            or not item["verification"].strip()
        ):
            raise StoreError("RECORD_ACTION_VERIFICATION_REQUIRED")
        _text(
            item["verification"],
            empty=item["status"] not in {"verified", "not_verified"},
        )
        references(item["evidence_ids"])
    return record
