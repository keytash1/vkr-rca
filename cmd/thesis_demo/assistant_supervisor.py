"""Bounded local I/O and process lifetime. Not an OS filesystem/egress sandbox.

Only the fixed private worker receives a job. No model-controlled command,
shell, executable path, provider URL, environment or state directory is used.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time

from assistant_context import assistant_context
from assistant_contract import AssistantLimits, validate_report, validate_conversation
from assistant_runner import DEFAULT_QUESTION, encoded

MAX_PIPE_BYTES = 128 * 1024
MAX_JOB_BYTES = 256 * 1024


def _failure(code, *, started=False, cancelled=False):
    return {
        "schema_version": "assistant-run-v1",
        "status": "cancelled" if cancelled else "failed",
        "stop_reason": code,
        "report": None,
        "fallback": {"mode": "B", "available": True, "reason": code},
        "usage": {
            "accounting_complete": not started,
            "unaccounted_attempts": int(started),
        },
        "local_process_stopped": True,
        "remote_generation_stopped": "UNKNOWN" if started else "NOT_STARTED",
    }


def _stop_group(process):
    # start_new_session gives this one job its own process group. Even a child
    # retaining a pipe cannot keep the reader waiting beyond the deadline.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.15)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)


def _run_child(command, payload, *, wall_seconds, cancel=None):
    """Internal fixed-worker transport; injectable command only for local tests."""
    if len(payload) > MAX_JOB_BYTES:
        return _failure("ASSISTANT_JOB_BUDGET")
    if cancel is not None and cancel.is_set():
        return _failure("ASSISTANT_CANCELLED", cancelled=True)
    started = time.monotonic()
    # Honour only the operator's tokenizer-cache override, never the rest of
    # the parent environment. The assistant image prewarms a read-only cache
    # outside /tmp; discarding its path silently forces the byte fallback.
    cache_dir = next((os.environ[name] for name in ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR")
                      if name in os.environ), None)
    if cache_dir is None:
        cache_dir = str(Path(tempfile.gettempdir()) / "data-gym-cache")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            bufsize=0,
            env={
                "PATH": os.defpath,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "TIKTOKEN_CACHE_DIR": cache_dir,
            },
        )
    except OSError:
        return _failure("ASSISTANT_WORKER_UNAVAILABLE")
    output, offset, reason = bytearray(), 0, None
    selector = selectors.DefaultSelector()
    try:
        for pipe in (process.stdin, process.stdout):
            os.set_blocking(pipe.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            if cancel is not None and cancel.is_set():
                reason = "ASSISTANT_CANCELLED"
                break
            remaining = wall_seconds - (time.monotonic() - started)
            if remaining <= 0:
                reason = "ASSISTANT_DEADLINE"
                break
            for key, _ in selector.select(min(0.05, remaining)):
                pipe = key.fileobj
                if pipe is process.stdin:
                    try:
                        written = os.write(
                            pipe.fileno(), payload[offset : offset + 4096]
                        )
                        offset += written
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        offset = len(payload)
                    if offset == len(payload):
                        selector.unregister(pipe)
                        pipe.close()
                else:
                    try:
                        block = os.read(pipe.fileno(), 4096)
                    except BlockingIOError:
                        continue
                    if not block:
                        selector.unregister(pipe)
                        pipe.close()
                    else:
                        output.extend(block)
                        if len(output) > MAX_PIPE_BYTES:
                            reason = "ASSISTANT_PIPE_BUDGET"
                            break
            if reason:
                break
        if not reason:
            try:
                process.wait(
                    timeout=max(0.001, wall_seconds - (time.monotonic() - started))
                )
            except subprocess.TimeoutExpired:
                reason = "ASSISTANT_DEADLINE"
        if reason:
            return _failure(
                reason, started=True, cancelled=reason == "ASSISTANT_CANCELLED"
            )
        try:
            result = json.loads(output)
            if not isinstance(result, dict) or result.get("status") not in {
                "completed",
                "partial",
                "failed",
                "cancelled",
            }:
                raise ValueError()
            if process.returncode != 0:
                return _failure("ASSISTANT_WORKER_FAILURE", started=True)
            return result
        except (ValueError, UnicodeError, RecursionError):
            return _failure("ASSISTANT_WORKER_PROTOCOL", started=True)
    finally:
        selector.close()
        _stop_group(process)
        for pipe in (process.stdin, process.stdout):
            if not pipe.closed:
                pipe.close()


def run_in_worker(
    *,
    python_executable,
    state_dir,
    model,
    catalog,
    ranking=None,
    question=DEFAULT_QUESTION,
    limits=None,
    cancel=None,
    allow_external=False,
    workflow="snapshot",
    runbooks=(),
    conversation=(),
):
    """Trusted local caller only; external data transmission is disabled by default.

    Settings paths and consent are operator policy, never supplied by an LLM.
    Parent revalidates the returned report against the selected original scope.
    """
    if allow_external is not True:
        return _failure("ASSISTANT_TRANSMISSION_NOT_ALLOWED")
    if workflow not in {"snapshot", "tools"}:
        return _failure("ASSISTANT_WORKFLOW_INVALID")
    limits = limits or AssistantLimits()
    # Send only the allowlisted summary to the isolated interpreter, never a
    # research result/label/raw span dictionary or source credential.
    context = assistant_context(catalog, summary_only=workflow != "tools")
    if workflow == "tools" and ranking is None and conversation:
        # E must never receive an earlier ML-hinted answer through discussion.
        return _failure("ASSISTANT_BLIND_DISCUSSION_NOT_ALLOWED")
    conversation = validate_conversation(conversation, context)
    # run_snapshot reprojects; supply declared omitted arrays, never the originals.
    for fact in context["observations"]:
        if fact["kind"] == "metric" and workflow != "tools":
            fact["values"]["series"] = []
        elif fact["kind"] == "traces" and workflow != "tools":
            fact["values"]["examples"] = []
    job = {
        "catalog": context,
        "ranking": assistant_context(catalog, ranking=ranking).get("ranking_hint"),
        "question": question,
        "model": model,
        "limits": asdict(limits),
        "workflow": workflow,
        "runbooks": list(runbooks) if workflow == "tools" else [],
        "conversation": conversation,
    }
    worker = Path(__file__).with_name("assistant_worker.py")
    result = _run_child(
        [
            str(Path(python_executable).absolute()),
            str(worker),
            "--state-dir",
            str(Path(state_dir).absolute()),
        ],
        encoded(job),
        wall_seconds=limits.wall_seconds,
        cancel=cancel,
    )
    if result.get("status") == "completed":
        try:
            validate_report(result["report"], context)
        except (KeyError, ValueError, TypeError):
            return _failure("ASSISTANT_WORKER_REPORT_INVALID", started=True)
    return result
