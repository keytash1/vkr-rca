"""One trusted local workspace: bounded queue, cancellation and human records."""

from __future__ import annotations

import fcntl
import json
import os
import queue
import re
import stat
import threading
import time

from assistant_privacy import prepare_outbound_aggregates
from assistant_supervisor import run_in_worker
from assistant_runner import DEFAULT_QUESTION
from assistant_contract import validate_report


class InvestigationError(ValueError):
    pass


def restore_report_identity(outcome, mapping):
    """Only declared report fields are relinked; never blindly replace text IDs.

    Keep the provider's pseudonymous prose unchanged, with an explicit local
    legend for display. Replacing substrings could alter numeric statements.
    """
    reverse_services = {v: k for k, v in mapping["services"].items()}
    reverse_ids = {v: k for k, v in mapping["observations"].items()}
    result = json.loads(json.dumps(outcome, ensure_ascii=False, allow_nan=False))
    if result.get("report"):
        for h in result["report"]["hypotheses"]:
            h["service"] = reverse_services[h["service"]]
            for name in ("supporting_evidence_ids", "contradicting_evidence_ids"):
                h[name] = [reverse_ids[i] for i in h[name]]
            for check in h["next_checks"]:
                check["evidence_ids"] = [reverse_ids[i] for i in check["evidence_ids"]]
        for item in result["report"].get("action_proposals", []):
            item["service"] = reverse_services[item["service"]]
            item["evidence_ids"] = [reverse_ids[i] for i in item["evidence_ids"]]
    result["local_identity_legend"] = {
        "services": reverse_services,
        "observations": reverse_ids,
    }
    return result


def previous_discussion(turns, mapping, clean_catalog):
    """At most two validated prior answers from this immutable snapshot only."""
    result = []
    names, ids = mapping["services"], mapping["observations"]
    for turn in turns:
        outcome = turn.get("outcome") or {}
        if turn.get("state") != "completed" or not outcome.get("report"):
            continue
        report = json.loads(
            json.dumps(outcome["report"], ensure_ascii=False, allow_nan=False)
        )
        for h in report["hypotheses"]:
            h["service"] = names[h["service"]]
            for key in ("supporting_evidence_ids", "contradicting_evidence_ids"):
                h[key] = [ids[i] for i in h[key]]
            for check in h["next_checks"]:
                check["evidence_ids"] = [ids[i] for i in check["evidence_ids"]]
        for item in report.get("action_proposals", []):
            item["service"] = names[item["service"]]
            item["evidence_ids"] = [ids[i] for i in item["evidence_ids"]]
        validate_report(report, clean_catalog)
        question = turn["request"]["question"]
        for source, target in sorted(names.items(), key=lambda pair: -len(pair[0])):
            question = re.sub(
                r"(?<![\w-])" + re.escape(source) + r"(?![\w-])",
                lambda _: target,
                question,
            )
        result.append(
            {"question": question, "report": report, "mode": turn["request"]["mode"]}
        )
    return result[-2:]


def outbound_question(question, mapping):
    for source, target in sorted(
        (mapping["services"] | mapping["observations"]).items(),
        key=lambda pair: -len(pair[0]),
    ):
        question = re.sub(
            r"(?<![\w-])" + re.escape(source) + r"(?![\w-])", lambda _: target, question
        )
    return question


class InvestigationService:
    def __init__(
        self,
        store,
        *,
        python_executable=None,
        state_dir=None,
        model=None,
        allowed_profiles=(),
        runbooks=(),
        runbook_corpus=None,
        runner=run_in_worker,
    ):
        self.store = store
        self.python_executable, self.state_dir, self.model = (
            python_executable,
            state_dir,
            model,
        )
        self.allowed_profiles = frozenset(allowed_profiles)
        self.runbooks, self.runner = tuple(runbooks), runner
        self.runbook_corpus = runbook_corpus
        self._lock = threading.RLock()
        self._events, self._pending = {}, set()
        self._queue = queue.Queue(maxsize=2)
        self._closed = threading.Event()
        self.maintenance_error = None
        # Exactly one owning manager per DB on this host. A second web process
        # cannot mark the first manager's live requests as interrupted.
        self._owner_fd = os.open(
            store.directory / "worker.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        info = os.fstat(self._owner_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            os.close(self._owner_fd)
            raise InvestigationError("WORKSPACE_OWNER_LOCK_UNSAFE")
        try:
            fcntl.flock(self._owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._owner_fd)
            raise InvestigationError("WORKSPACE_ALREADY_RUNNING") from None
        self.recovered_jobs = self.store.recover_interrupted()
        self._thread = threading.Thread(
            target=self._work, name="rca-investigation-worker", daemon=True
        )
        self._thread.start()

    @property
    def llm_configured(self):
        return bool(self.python_executable and self.state_dir and self.model)

    def health(self):
        with self._lock:
            return {
                "worker_alive": self._thread.is_alive(),
                "pending": len(self._pending),
                "capacity": 2,
                "retention_maintenance_error": self.maintenance_error,
            }

    def _request(self, snapshot, mode, question):
        if mode not in {
            "B",
            "C",
            "D",
        }:  # E is evaluator-only, not a blind-user UI claim.
            raise InvestigationError("INVESTIGATION_MODE_INVALID")
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 2000
        ):
            raise InvestigationError("INVESTIGATION_QUESTION_INVALID")
        if snapshot is None:
            raise InvestigationError("INVESTIGATION_ANALYSIS_NOT_FOUND")
        if mode != "B" and (
            not self.llm_configured or snapshot["project"] not in self.allowed_profiles
        ):
            raise InvestigationError("ASSISTANT_PROFILE_NOT_APPROVED")
        return {
            "mode": mode,
            "question": question,
            "model": self.model if mode != "B" else None,
            "snapshot_sha256": snapshot["snapshot_sha256"],
        }

    def submit(
        self, analysis_id, *, mode="B", question=DEFAULT_QUESTION, idempotency_key
    ):
        snapshot = self.store.get_snapshot(analysis_id)
        request = self._request(snapshot, mode, question)
        with self._lock:
            if self._closed.is_set():
                raise InvestigationError("WORKSPACE_STOPPING")
            old = self.store.find_idempotent(
                analysis_id, request, idempotency_key=idempotency_key
            )
            if old:
                return self.store.get_investigation(old), False
            # One running and at most one waiting. No unbounded ThreadPool jobs.
            if len(self._pending) >= 2:
                raise InvestigationError("WORKSPACE_BUSY")
            identifier, fresh = self.store.create_investigation(
                analysis_id, request, idempotency_key=idempotency_key
            )
            if fresh:
                self._pending.add(identifier)
                self._events[identifier] = threading.Event()
                self._queue.put_nowait(identifier)
            return self.store.get_investigation(identifier), fresh

    def follow_up(self, identifier, *, mode="D", question, idempotency_key):
        current = self.store.get_investigation(identifier)
        if current is None:
            raise InvestigationError("INVESTIGATION_NOT_FOUND")
        snapshot = self.store.get_snapshot(current["analysis_id"])
        request = self._request(snapshot, mode, question)
        with self._lock:
            if self._closed.is_set():
                raise InvestigationError("WORKSPACE_STOPPING")
            old = self.store.find_turn_idempotent(
                identifier, request, idempotency_key=idempotency_key
            )
            if old:
                return self.store.get_investigation(identifier), False
            if identifier in self._pending or len(self._pending) >= 2:
                raise InvestigationError("WORKSPACE_BUSY")
            _, fresh = self.store.add_turn(
                identifier, request, idempotency_key=idempotency_key
            )
            if fresh:
                self._pending.add(identifier)
                self._events[identifier] = threading.Event()
                self._queue.put_nowait(identifier)
            return self.store.get_investigation(identifier), fresh

    def cancel(self, identifier):
        with self._lock:
            current = self.store.get_investigation(identifier)
            if current is None:
                raise InvestigationError("INVESTIGATION_NOT_FOUND")
            event = self._events.get(identifier)
            if event:
                event.set()
                self.store.transition(
                    identifier, expected=["queued", "running"], state="cancelling"
                )
            return self.store.get_investigation(identifier)

    def delete_snapshot(self, analysis_id):
        with self._lock:
            for identifier in self._pending:
                current = self.store.get_investigation(identifier)
                if current and current["analysis_id"] == analysis_id:
                    self._events[identifier].set()
            return self.store.delete_snapshot(analysis_id)

    def _work(self):
        last_purge = time.monotonic()
        while not self._closed.is_set() or not self._queue.empty():
            try:
                identifier = self._queue.get(timeout=0.1)
            except queue.Empty:
                if time.monotonic() - last_purge >= 60:
                    try:
                        self.store.purge_expired()
                        self.maintenance_error = None
                    except Exception:
                        self.maintenance_error = (
                            "WORKSPACE_RETENTION_MAINTENANCE_FAILED"
                        )
                    last_purge = time.monotonic()
                continue
            try:
                with self._lock:
                    current = self.store.get_investigation(identifier)
                    event = self._events[identifier]
                    if current is None:
                        continue
                    self.store.transition(
                        identifier, expected=["queued"], state="running"
                    )
                snapshot = self.store.get_snapshot(current["analysis_id"])
                if snapshot is None:
                    continue
                mode, question = (
                    current["request"]["mode"],
                    current["request"]["question"],
                )
                if event.is_set():
                    outcome = {
                        "status": "cancelled",
                        "stop_reason": "ASSISTANT_CANCELLED",
                        "report": None,
                        "usage": {
                            "model_calls": 0,
                            "tool_calls": 0,
                            "accounting_complete": True,
                        },
                        "local_process_stopped": True,
                        "remote_generation_stopped": "NOT_STARTED",
                    }
                elif mode == "B":
                    outcome = {
                        "schema_version": "assistant-run-v1",
                        "status": "completed",
                        "stop_reason": "DETERMINISTIC_CHECKS",
                        "mode": "B",
                        "report": None,
                        "checks": snapshot["catalog"].get("checks", []),
                        "usage": {
                            "model_calls": 0,
                            "tool_calls": 0,
                            "accounting_complete": True,
                        },
                    }
                else:
                    hint = snapshot["analysis"]["candidates"]
                    clean, hint, mapping = prepare_outbound_aggregates(
                        snapshot["catalog"], ranking=hint, include_details=mode == "D"
                    )
                    discussion = previous_discussion(
                        current.get("turns", [])[:-1], mapping, clean
                    )
                    outcome = self.runner(
                        python_executable=self.python_executable,
                        state_dir=self.state_dir,
                        model=self.model,
                        catalog=clean,
                        ranking=hint,
                        question=outbound_question(question, mapping),
                        cancel=event,
                        allow_external=True,
                        workflow="tools" if mode == "D" else "snapshot",
                        runbooks=(
                            self.runbook_corpus.for_project(snapshot["project"])
                            if self.runbook_corpus
                            else self.runbooks
                        )
                        if mode == "D"
                        else (),
                        conversation=discussion,
                    )
                    outcome = restore_report_identity(outcome, mapping)
                    if self.runbook_corpus and mode == "D":
                        outcome["runbook_corpus"] = {
                            "version": self.runbook_corpus.version,
                            "sha256": self.runbook_corpus.sha256,
                        }
                if event.is_set():
                    outcome = {
                        "status": "cancelled",
                        "stop_reason": "ASSISTANT_CANCELLED",
                        "report": None,
                        "usage": outcome.get("usage", {}),
                        "local_process_stopped": True,
                        "remote_generation_stopped": outcome.get(
                            "remote_generation_stopped", "UNKNOWN"
                        ),
                    }
                state = outcome.get("status")
                if state not in {"completed", "partial", "failed", "cancelled"}:
                    state = "failed"
                self.store.transition(
                    identifier,
                    expected=["running", "cancelling"],
                    state=state,
                    outcome=outcome,
                )
            except Exception:
                # No tracebacks/prompts/source URLs in public state. The
                # original ranking remains available even on storage failure.
                try:
                    self.store.transition(
                        identifier,
                        expected=["queued", "running", "cancelling"],
                        state="failed",
                        outcome={
                            "status": "failed",
                            "stop_reason": "INVESTIGATION_WORKER_FAILURE",
                            "report": None,
                            "usage": {"accounting_complete": False},
                        },
                    )
                except Exception:
                    pass
            finally:
                with self._lock:
                    self._pending.discard(identifier)
                    self._events.pop(identifier, None)
                self._queue.task_done()

    def close(self):
        self._closed.set()
        with self._lock:
            for event in self._events.values():
                event.set()
        self._thread.join(timeout=3)
        if not self._thread.is_alive():
            os.close(self._owner_fd)
