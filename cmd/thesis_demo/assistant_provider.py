"""One optional, app-owned ChatGPT plan adapter. No model chosen implicitly.

Only public /v1/models and /v1/responses; no backend-api or Codex token reuse.
The process-isolated orchestration deadline is a separate I07/I08 requirement.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
import fcntl
import os
import stat
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from assistant_auth import (
    AuthorizationError,
    NoRedirect,
    PLAN_SCOPE,
    PrivateStore,
    RESOURCE,
    TOKEN_URL,
    auth_json,
)
from assistant_contract import ProviderReply

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 24000


class ProviderError(RuntimeError):
    """Safe code only. Never attach raw upstream error or input text."""


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def parse_response_stream(lines, *, model, started, cancel=None, deadline=None):
    """SSE completion semantics; a partial output is never a successful reply."""
    text, size, text_size, event_lines, completed = [], 0, 0, [], None
    completed_items = {}
    for raw in lines:
        if cancel is not None and cancel.is_set():
            raise ProviderError("LLM_CANCELLED")
        if deadline is not None and time.monotonic() >= deadline:
            raise ProviderError("LLM_DEADLINE")
        size += len(raw)
        if size > MAX_RESPONSE_BYTES or len(raw) > 128 * 1024:
            raise ProviderError("LLM_RESPONSE_BUDGET")
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
        except UnicodeError:
            raise ProviderError("LLM_INVALID_STREAM") from None
        if line.startswith("data:"):
            event_lines.append(line[5:].lstrip())
            continue
        if line or not event_lines:
            continue
        payload = "\n".join(event_lines)
        event_lines.clear()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except ValueError:
            raise ProviderError("LLM_INVALID_STREAM") from None
        if not isinstance(event, dict):
            raise ProviderError("LLM_INVALID_STREAM")
        kind = event.get("type")
        if kind == "response.output_item.done":
            index, item = event.get("output_index"), event.get("item")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < 16
                or not isinstance(item, dict)
                or index in completed_items
            ):
                raise ProviderError("LLM_OUTPUT_ITEMS_INVALID")
            completed_items[index] = item
        if kind in {"error", "response.failed", "response.incomplete"}:
            raise ProviderError("LLM_UPSTREAM_FAILED")
        if kind == "response.refusal.delta":
            raise ProviderError("LLM_REFUSAL")
        if kind == "response.output_text.delta":
            delta = event.get("delta")
            if not isinstance(delta, str):
                raise ProviderError("LLM_INVALID_STREAM")
            text.append(delta)
            text_size += len(delta)
            if text_size > MAX_TEXT_CHARS:
                raise ProviderError("LLM_OUTPUT_BUDGET")
        if kind == "response.completed":
            completed = event.get("response")
            if (
                not isinstance(completed, dict)
                or completed.get("status") != "completed"
            ):
                raise ProviderError("LLM_INVALID_COMPLETION")
            # Completion is the terminal success signal. Do not wait for an
            # idle keep-alive socket after the response is already complete.
            break
    if completed is None:
        raise ProviderError("LLM_STREAM_INTERRUPTED")
    usage = completed.get("usage", {})
    for field in ("input_tokens", "output_tokens"):
        if (
            isinstance(usage.get(field), bool)
            or not isinstance(usage.get(field), int)
            or usage[field] < 0
        ):
            raise ProviderError("LLM_USAGE_UNKNOWN")
    response_id = completed.get("id")
    if not isinstance(response_id, str) or not response_id:
        raise ProviderError("LLM_RESPONSE_ID_MISSING")
    output_items = completed.get("output")
    if not output_items and completed_items:
        if sorted(completed_items) != list(range(len(completed_items))):
            raise ProviderError("LLM_OUTPUT_ITEMS_INVALID")
        output_items = [completed_items[i] for i in sorted(completed_items)]
    output_items = output_items or []
    if not isinstance(output_items, list) or len(output_items) > 16:
        raise ProviderError("LLM_OUTPUT_ITEMS_INVALID")
    calls, continuation, call_ids = [], [], set()
    for item in output_items:
        if not isinstance(item, dict):
            raise ProviderError("LLM_OUTPUT_ITEMS_INVALID")
        kind = item.get("type")
        if kind == "function_call":
            if (
                item.get("status") not in {None, "completed"}
                or any(
                    not isinstance(item.get(k), str) or not item[k]
                    for k in ("call_id", "name", "arguments")
                )
                or len(item["arguments"].encode()) > 4096
                or item["call_id"] in call_ids
            ):
                raise ProviderError("LLM_TOOL_CALL_INVALID")
            call_ids.add(item["call_id"])
            call = {k: item[k] for k in ("call_id", "name", "arguments")}
            call["namespace"] = item.get("namespace")
            if call["namespace"] is not None and not isinstance(call["namespace"], str):
                raise ProviderError("LLM_TOOL_CALL_INVALID")
            calls.append(call)
            continuation.append(
                {
                    k: item[k]
                    for k in (
                        "type",
                        "id",
                        "call_id",
                        "name",
                        "namespace",
                        "arguments",
                        "status",
                    )
                    if k in item
                }
            )
        elif kind == "reasoning":
            # Opaque continuation only: do not store or expose reasoning text.
            opaque = item.get("encrypted_content")
            if opaque is not None and (
                not isinstance(opaque, str) or len(opaque) > 32768
            ):
                raise ProviderError("LLM_REASONING_BUDGET")
            continuation.append(
                {k: item[k] for k in ("type", "id", "encrypted_content") if k in item}
                | {"summary": []}
            )
        elif kind == "message":
            content = item.get("content", [])
            if not isinstance(content, list) or item.get("role") != "assistant":
                raise ProviderError("LLM_OUTPUT_ITEMS_INVALID")
            safe_content = []
            for part in content:
                if (
                    not isinstance(part, dict)
                    or part.get("type") != "output_text"
                    or not isinstance(part.get("text"), str)
                ):
                    raise ProviderError("LLM_REFUSAL_OR_UNSUPPORTED_OUTPUT")
                safe_content.append(
                    {"type": "output_text", "text": part["text"], "annotations": []}
                )
            continuation.append(
                {
                    k: item[k]
                    for k in ("type", "id", "role", "status", "phase")
                    if k in item
                }
                | {"content": safe_content}
            )
        else:
            raise ProviderError("LLM_UNSUPPORTED_OUTPUT_ITEM")
    if len(_json_bytes(continuation)) > 64 * 1024:
        raise ProviderError("LLM_CONTINUATION_BUDGET")
    if not text and not calls:
        raise ProviderError("LLM_EMPTY_RESPONSE")
    return ProviderReply(
        "".join(text),
        str(completed.get("model", model)),
        response_id,
        usage["input_tokens"],
        usage["output_tokens"],
        time.monotonic() - started,
        tuple(calls),
        tuple(continuation),
    )


class ChatGPTPlanProvider:
    def __init__(self, state_dir):
        self.store = PrivateStore(state_dir)
        self.refresh_lock = threading.Lock()

    @contextmanager
    def _session_lock(self):
        """Serialize token rotation across worker/CLI processes on this host."""
        fd = None
        try:
            fd = os.open(
                self.store.directory / "refresh.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
            )
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise ProviderError("LLM_SESSION_LOCK_INVALID")
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ProviderError("LLM_SESSION_BUSY") from None
                    time.sleep(0.02)
            yield
        except OSError:
            raise ProviderError("LLM_SESSION_LOCK_UNAVAILABLE") from None
        finally:
            if fd is not None:
                os.close(fd)

    def _access_token(self):
        with self.refresh_lock, self._session_lock():
            record = self.store.read("connection.json")
            if not record or not {PLAN_SCOPE, "resource.invoke"} <= set(
                record.get("scopes", [])
            ):
                raise ProviderError("LLM_SIGN_IN_REQUIRED")
            if record.get("expires_at_unix", 0) <= time.time() + 60:
                if not record.get("refresh_token"):
                    raise ProviderError("LLM_REAUTHORIZE_REQUIRED")
                try:
                    tokens = auth_json(
                        TOKEN_URL,
                        form={
                            "grant_type": "refresh_token",
                            "client_id": record["client_id"],
                            "refresh_token": record["refresh_token"],
                            "resource": RESOURCE,
                        },
                    )
                except AuthorizationError:
                    raise ProviderError("LLM_REFRESH_FAILED") from None
                scope = tokens.get("scope")
                scopes = scope.split() if isinstance(scope, str) else record["scopes"]
                expires = tokens.get("expires_in")
                token = tokens.get("access_token")
                if (
                    PLAN_SCOPE not in scopes
                    or "resource.invoke" not in scopes
                    or not isinstance(token, str)
                    or not token
                    or str(tokens.get("token_type", "")).lower() != "bearer"
                    or isinstance(expires, bool)
                    or not isinstance(expires, (float, int))
                    or not 0 < expires <= 86400
                ):
                    raise ProviderError("LLM_REFRESH_INVALID")
                record.update(
                    access_token=token,
                    scopes=scopes,
                    expires_at_unix=time.time() + expires,
                    refresh_token=tokens.get("refresh_token", record["refresh_token"]),
                    saved_at_unix=time.time(),
                )
                # Retain the original verified ID token as an optional login
                # hint; never trust an unverified identity from refresh data.
                self.store.write("connection.json", record)
            token = record.get("access_token")
            if not isinstance(token, str) or not token:
                raise ProviderError("LLM_REAUTHORIZE_REQUIRED")
            return token

    def _open(self, path, *, payload=None, timeout_seconds=20):
        if path not in {"/models", "/responses"}:
            raise ProviderError("LLM_ENDPOINT_NOT_ALLOWED")
        body = _json_bytes(payload) if payload is not None else None
        if body and len(body) > MAX_REQUEST_BYTES:
            raise ProviderError("LLM_INPUT_BUDGET")
        headers = {
            "Authorization": "Bearer " + self._access_token(),
            "Accept": "text/event-stream"
            if payload is not None
            else "application/json",
        }
        if body:
            headers["Content-Type"] = "application/json"
        try:
            return build_opener(NoRedirect()).open(
                Request(RESOURCE + path, data=body, headers=headers),
                timeout=timeout_seconds,
            )
        except HTTPError as error:
            code = error.code
            error.close()
            raise ProviderError(f"LLM_HTTP_{code}") from None
        except (URLError, OSError):
            raise ProviderError("LLM_NETWORK_UNAVAILABLE") from None

    def list_models(self):
        try:
            with self._open("/models") as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except OSError:
            raise ProviderError("LLM_NETWORK_UNAVAILABLE") from None
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ProviderError("LLM_RESPONSE_BUDGET")
        try:
            value = json.loads(payload)
            models = value["models"]
            if not isinstance(models, list):
                raise ValueError()
            return [
                {"slug": m["slug"], "display_name": m["display_name"]}
                for m in models
                if isinstance(m, dict)
                and m.get("visibility") == "list"
                and isinstance(m.get("slug"), str)
                and isinstance(m.get("display_name"), str)
            ]
        except (ValueError, TypeError, KeyError):
            raise ProviderError("LLM_MODEL_CATALOG_INVALID") from None

    def complete(
        self,
        *,
        model,
        instructions,
        input_items,
        timeout_seconds=60,
        cancel=None,
        response_schema=None,
        tools=None,
        tool_choice=None,
    ):
        if (
            not isinstance(model, str)
            or not model
            or len(model) > 200
            or not isinstance(instructions, str)
            or not isinstance(input_items, list)
            or not input_items
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 60
        ):
            raise ProviderError("LLM_REQUEST_INVALID")
        if cancel is not None and cancel.is_set():
            raise ProviderError("LLM_CANCELLED")
        started = time.monotonic()
        payload = {
            "model": model,
            "instructions": instructions,
            "input": input_items,
            "store": False,
            "stream": True,
        }
        if tools is not None:
            # Local orchestration supplies one fixed, narrow namespace, never
            # provider-hosted tools, shell, arbitrary URLs or model parameters.
            if (
                not isinstance(tools, list)
                or len(tools) != 1
                or not isinstance(tools[0], dict)
                or tools[0].get("type") != "namespace"
                or tools[0].get("name") != "rca"
                or not isinstance(tools[0].get("tools"), list)
            ):
                raise ProviderError("LLM_TOOLS_INVALID")
            payload["tools"] = tools
        if tool_choice is not None:
            if tool_choice not in {"auto", "none", "required"} or tools is None:
                raise ProviderError("LLM_TOOL_CHOICE_INVALID")
            payload["tool_choice"] = tool_choice
        if response_schema is not None:
            if not isinstance(response_schema, dict):
                raise ProviderError("LLM_REQUEST_INVALID")
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "rca_report",
                    "strict": True,
                    "schema": response_schema,
                }
            }
        # Only documented plan-sharing fields. No unsupported max_output_tokens,
        # temperature, background or persistent conversation parameters.
        try:
            with self._open(
                "/responses", payload=payload, timeout_seconds=min(timeout_seconds, 10)
            ) as response:
                media_type = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                # The live plan-sharing endpoint has also returned SSE framed
                # as text/plain or without Content-Type. Accept those labels, not arbitrary
                # JSON/HTML: the strict SSE parser still requires a completed
                # response with valid usage, and rejects an unframed body.
                if media_type not in {"text/event-stream", "text/plain", ""}:
                    raise ProviderError("LLM_STREAM_CONTENT_TYPE")
                lines = iter(lambda: response.readline(128 * 1024 + 1), b"")
                return parse_response_stream(
                    lines,
                    model=model,
                    started=started,
                    cancel=cancel,
                    deadline=started + timeout_seconds,
                )
        except (OSError, TimeoutError):
            raise ProviderError("LLM_STREAM_INTERRUPTED") from None
