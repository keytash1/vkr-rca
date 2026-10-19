import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

from assistant_supervisor import _run_child, run_in_worker
from test_assistant_runner import catalog, report


class ProcessBoundaryTests(unittest.TestCase):
    def test_worker_honours_only_operator_tokenizer_cache(self):
        code = "import os,json; print(json.dumps({'status':'completed','cache':os.environ.get('TIKTOKEN_CACHE_DIR'),'secret_inherited':'SECRET_KEY' in os.environ}))"
        for environment, expected in [
            ({'TIKTOKEN_CACHE_DIR':'/opt/rca/tokenizer-cache', 'DATA_GYM_CACHE_DIR':'/ignored'}, '/opt/rca/tokenizer-cache'),
            ({'DATA_GYM_CACHE_DIR':'/operator/public-cache'}, '/operator/public-cache'),
            ({'TIKTOKEN_CACHE_DIR':''}, ''),
        ]:
            with self.subTest(environment=environment), patch.dict(os.environ, environment | {'SECRET_KEY':'not-forwarded'}, clear=True), patch('assistant_supervisor.tempfile.gettempdir', side_effect=AssertionError('explicit cache must not need tmp')):
                result = self.run_code(code)
            self.assertEqual(result['cache'], expected)
            self.assertFalse(result['secret_inherited'])

    def run_code(self, code, payload=b"{}", **kwargs):
        return _run_child([sys.executable, "-c", code], payload, wall_seconds=kwargs.pop("wall_seconds", 3), **kwargs)

    def test_complete_result_and_unknown_usage_after_bad_protocol(self):
        good = json.dumps({"status": "completed", "report": report()})
        result = self.run_code("import sys; sys.stdin.buffer.read(); print(" + repr(good) + ")")
        self.assertEqual(result["status"], "completed")
        result = self.run_code("print('not json SECRET')")
        self.assertEqual(result["stop_reason"], "ASSISTANT_WORKER_PROTOCOL")
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertFalse(result["usage"]["accounting_complete"])

    def test_hanging_worker_and_pipe_writer_are_stopped_not_just_hidden(self):
        start = time.monotonic()
        result = self.run_code("import time; time.sleep(10)", wall_seconds=.15)
        self.assertEqual(result["stop_reason"], "ASSISTANT_DEADLINE")
        self.assertLess(time.monotonic() - start, 2)
        self.assertTrue(result["local_process_stopped"])
        self.assertEqual(result["remote_generation_stopped"], "UNKNOWN")
        result = self.run_code("import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(10)", wall_seconds=.15)
        self.assertEqual(result["stop_reason"], "ASSISTANT_DEADLINE")
        self.assertTrue(result["local_process_stopped"])
        result = self.run_code("import sys; sys.stdout.write('x'*200000); sys.stdout.flush()")
        self.assertEqual(result["stop_reason"], "ASSISTANT_PIPE_BUDGET")

    def test_cancel_before_spawn_and_during_wait(self):
        event = threading.Event(); event.set()
        with patch("assistant_supervisor.subprocess.Popen") as popen:
            result = self.run_code("pass", cancel=event)
            popen.assert_not_called()
        self.assertEqual(result["status"], "cancelled")
        event.clear()
        timer = threading.Timer(.1, event.set); timer.start()
        try:
            result = self.run_code("import time; time.sleep(10)", cancel=event)
            self.assertEqual(result["status"], "cancelled")
        finally:
            timer.cancel()

    def test_no_transmission_without_policy_and_parent_scope_validation(self):
        args = {"python_executable": sys.executable, "state_dir": "/not-used", "model": "unit",
                "catalog": catalog()}
        with patch("assistant_supervisor._run_child") as child:
            result = run_in_worker(**args)
            child.assert_not_called()
            self.assertEqual(result["stop_reason"], "ASSISTANT_TRANSMISSION_NOT_ALLOWED")
        invalid = report(); invalid["hypotheses"][0]["service"] = "other-project"
        with patch("assistant_supervisor._run_child", return_value={"status": "completed", "report": invalid}):
            result = run_in_worker(**args, allow_external=True)
            self.assertEqual(result["stop_reason"], "ASSISTANT_WORKER_REPORT_INVALID")
        with patch("assistant_supervisor._run_child", return_value={"status": "completed", "report": report()}) as child:
            run_in_worker(**args, allow_external=True)
            transmitted = child.call_args.args[1].decode()
            self.assertNotIn("SECRET", transmitted)
            self.assertNotIn("source_links", transmitted)


if __name__ == "__main__":
    unittest.main()
