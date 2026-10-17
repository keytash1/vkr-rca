"""Transport failures and usage semantics, no real model or credentials."""
import json
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from assistant_auth import PLAN_SCOPE, PrivateStore
from assistant_provider import ChatGPTPlanProvider, ProviderError, parse_response_stream


def events(*items):
    return b"".join(b"data: " + json.dumps(item).encode() + b"\n\n" for item in items).splitlines(keepends=True)


def completed(**updates):
    return {"type": "response.completed", "response": {"status": "completed", "id": "resp-unit",
        "model": "unit-model", "usage": {"input_tokens": 15, "output_tokens": 3}} | updates}


class StreamTests(unittest.TestCase):
    def parse(self, lines, **kwargs):
        return parse_response_stream(lines, model="unit-model", started=time.monotonic(), **kwargs)

    def test_requires_real_terminal_completion_and_usage(self):
        reply = self.parse(events({"type": "response.output_text.delta", "delta": "RCA_"},
            {"type": "response.output_text.delta", "delta": "OK"}, completed()))
        self.assertEqual(reply.text, "RCA_OK")
        self.assertEqual((reply.input_tokens, reply.output_tokens), (15, 3))
        self.assertGreaterEqual(reply.elapsed_seconds, 0)
        with self.assertRaisesRegex(ProviderError, "LLM_STREAM_INTERRUPTED"):
            self.parse(events({"type": "response.output_text.delta", "delta": "partial"}))
        with self.assertRaisesRegex(ProviderError, "LLM_USAGE_UNKNOWN"):
            self.parse(events({"type": "response.output_text.delta", "delta": "text"}, completed(usage={})))

    def test_failure_after_text_is_not_a_successful_partial_answer(self):
        for kind in ("response.failed", "response.incomplete", "error", "response.refusal.delta"):
            with self.subTest(kind=kind), self.assertRaises(ProviderError):
                self.parse(events({"type": "response.output_text.delta", "delta": "partial"},
                    {"type": kind, "error": {"message": "SECRET_UPSTREAM_BODY"}}))

    def test_only_completed_function_call_is_replayable_not_partial_arguments(self):
        item = {"type": "function_call", "id": "fc-unit", "call_id": "call-unit", "namespace": "rca",
                "name": "get_candidate_evidence", "arguments": '{"service":"alpha"}', "status": "completed"}
        reply = self.parse(events(completed(output=[{"type": "reasoning", "id": "rs-unit", "summary": [],
            "encrypted_content": "OPAQUE_UNIT"}, item])))
        self.assertEqual(reply.tool_calls[0]["namespace"], "rca")
        self.assertEqual(reply.output_items[0]["encrypted_content"], "OPAQUE_UNIT")
        # Plan-sharing SSE may put items only in item.done, with a compact
        # terminal response. They are still unusable until terminal completion.
        compact = self.parse(events({"type": "response.output_item.done", "output_index": 0, "item": item}, completed()))
        self.assertEqual(compact.tool_calls[0]["name"], "get_candidate_evidence")
        with self.assertRaisesRegex(ProviderError, "LLM_STREAM_INTERRUPTED"):
            self.parse(events({"type": "response.function_call_arguments.done", "arguments": item["arguments"]}))
        with self.assertRaisesRegex(ProviderError, "LLM_TOOL_CALL_INVALID"):
            self.parse(events(completed(output=[item, item])))
        with self.assertRaisesRegex(ProviderError, "LLM_UNSUPPORTED_OUTPUT_ITEM"):
            self.parse(events(completed(output=[{"type": "web_search_call"}])))

    def test_cancel_deadline_malformed_and_output_limits(self):
        cancel = threading.Event(); cancel.set()
        good = events({"type": "response.output_text.delta", "delta": "ok"}, completed())
        with self.assertRaisesRegex(ProviderError, "LLM_CANCELLED"):
            self.parse(good, cancel=cancel)
        with self.assertRaisesRegex(ProviderError, "LLM_DEADLINE"):
            self.parse(good, deadline=time.monotonic() - 1)
        with self.assertRaisesRegex(ProviderError, "LLM_INVALID_STREAM"):
            self.parse([b"data: not-json\n", b"\n"])
        with self.assertRaisesRegex(ProviderError, "LLM_OUTPUT_BUDGET"):
            self.parse(events({"type": "response.output_text.delta", "delta": "x" * 24001}, completed()))
        with self.assertRaisesRegex(ProviderError, "LLM_USAGE_UNKNOWN"):
            self.parse(events({"type": "response.output_text.delta", "delta": "ok"},
                completed(usage={"input_tokens": True, "output_tokens": 0})))


class ProviderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.store = PrivateStore(self.directory)
        self.provider = ChatGPTPlanProvider(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, **overrides):
        record = {"client_id": "oaiapp_unit", "subject": "unit-subject", "id_token": "unit-original-id",
            "scopes": [PLAN_SCOPE, "resource.invoke"], "expires_at_unix": time.time() + 300,
            "access_token": "UNIT_TEST_ACCESS_TOKEN", "refresh_token": "UNIT_TEST_REFRESH_TOKEN"} | overrides
        self.store.write("connection.json", record)
        return record

    def test_missing_permission_never_calls_network(self):
        with patch("assistant_provider.build_opener") as opener:
            with self.assertRaisesRegex(ProviderError, "LLM_SIGN_IN_REQUIRED"):
                self.provider.list_models()
            opener.assert_not_called()
        self.record(scopes=["openid"])
        with self.assertRaisesRegex(ProviderError, "LLM_SIGN_IN_REQUIRED"):
            self.provider._access_token()

    def test_only_documented_fixed_endpoints_and_bounded_input(self):
        self.record()
        with self.assertRaisesRegex(ProviderError, "LLM_ENDPOINT_NOT_ALLOWED"):
            self.provider._open("https://evil.invalid/collect")
        with self.assertRaisesRegex(ProviderError, "LLM_INPUT_BUDGET"):
            self.provider._open("/responses", payload={"text": "x" * 65537})
        with patch.object(self.provider, "_open") as opened:
            with self.assertRaisesRegex(ProviderError, "LLM_REQUEST_INVALID"):
                self.provider.complete(model="", instructions="unit", input_items=[])
            opened.assert_not_called()

    def test_refresh_rotates_atomically_and_does_not_replace_verified_identity(self):
        self.record(expires_at_unix=0)
        tokens = {"access_token": "NEW_UNIT_ACCESS", "refresh_token": "NEW_UNIT_REFRESH",
            "token_type": "Bearer", "expires_in": 3600, "id_token": "UNVERIFIED_DO_NOT_USE"}
        with patch("assistant_provider.auth_json", return_value=tokens) as request:
            self.assertEqual(self.provider._access_token(), "NEW_UNIT_ACCESS")
        self.assertEqual(request.call_args.kwargs["form"]["client_id"], "oaiapp_unit")
        saved = self.store.read("connection.json")
        self.assertEqual(saved["refresh_token"], "NEW_UNIT_REFRESH")
        self.assertEqual(saved["id_token"], "unit-original-id")
        self.assertEqual(saved["subject"], "unit-subject")

    def test_separate_instances_serialize_refresh_and_reuse_rotated_token(self):
        self.record(expires_at_unix=0)
        other = ChatGPTPlanProvider(self.directory)
        tokens = {"access_token": "NEW_UNIT_ACCESS", "refresh_token": "NEW_UNIT_REFRESH",
            "token_type": "Bearer", "expires_in": 3600}
        def refresh(*args, **kwargs):
            time.sleep(.04)
            return tokens
        results = []
        def use(provider):
            results.append(provider._access_token())
        with patch("assistant_provider.auth_json", side_effect=refresh) as request:
            workers = [threading.Thread(target=use, args=(provider,)) for provider in (self.provider, other)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(2)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(request.call_count, 1)
        self.assertEqual(results, ["NEW_UNIT_ACCESS", "NEW_UNIT_ACCESS"])

    def test_session_lock_rejects_symlink(self):
        self.record()
        target = self.directory / "other-file"
        target.touch(mode=0o600)
        (self.directory / "refresh.lock").symlink_to(target)
        with self.assertRaisesRegex(ProviderError, "LLM_SESSION_LOCK_UNAVAILABLE"):
            self.provider._access_token()

    def test_live_plain_text_sse_requires_full_completion(self):
        def response(body, media_type):
            stream = io.BytesIO(body)
            stream.headers = {"Content-Type": media_type}
            return stream
        body = b"".join(events({"type": "response.output_text.delta", "delta": "RCA_OK"}, completed()))
        for media_type in ("text/event-stream", "text/plain; charset=utf-8", ""):
            with self.subTest(media_type=media_type), patch.object(self.provider, "_open",
                    return_value=response(body, media_type)):
                result = self.provider.complete(model="unit-model", instructions="unit",
                    input_items=[{"role": "user", "content": "unit"}])
                self.assertEqual(result.text, "RCA_OK")
        with patch.object(self.provider, "_open", return_value=response(b"plain unframed text", "text/plain")):
            with self.assertRaisesRegex(ProviderError, "LLM_STREAM_INTERRUPTED"):
                self.provider.complete(model="unit-model", instructions="unit", input_items=[{}])
        with patch.object(self.provider, "_open", return_value=response(body, "text/html")):
            with self.assertRaisesRegex(ProviderError, "LLM_STREAM_CONTENT_TYPE"):
                self.provider.complete(model="unit-model", instructions="unit", input_items=[{}])


if __name__ == "__main__":
    unittest.main()
