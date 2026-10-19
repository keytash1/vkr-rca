"""Reuse never crosses scope or resurrects a deleted snapshot."""

import threading
import time
import unittest
from unittest.mock import patch

from analysis_requests import AnalysisRequests
from api_errors import ApiError


def result(identifier="one"):
    return {
        "result_id": identifier,
        "candidates": [{"service": "a"}],
        "source_status": {
            "metrics": "available",
            "traces": "available",
            "span_count": 1,
            "annotations": [],
            "collected_at_unix": time.time(),
            "metric_families_by_service": {
                "a": ["cpu", "memory", "network", "traffic_rate"]
            },
            "metric_point_coverage": {
                "a": {"cpu": 1, "memory": 1, "network": 1, "traffic_rate": 1}
            },
        },
    }


class RequestTests(unittest.TestCase):
    def test_http_partial_is_not_cached_but_observed_idle_is(self):
        for status, state, expected in [('partial', 'PARTIAL', False),
                                        ('unavailable', 'UNAVAILABLE', False),
                                        ('complete', 'NO_ACTIVITY', True),
                                        ('complete', 'OBSERVED', True)]:
            with self.subTest(status=status, state=state):
                requests = AnalysisRequests()
                def compute():
                    value = result()
                    value['source_status']['http_observations'] = {'status':status, 'services':{'a':state}}
                    return value
                requests.run('scope', compute)
                self.assertEqual(requests.run('scope', compute)['delivery']['cache_hit'], expected)

    def test_degraded_optional_context_is_not_reused_as_fresh(self):
        requests = AnalysisRequests(); calls=[]
        def compute():
            calls.append(1); value=result(str(len(calls)))
            value['source_status']['incident_context']={'services':{'a':'unavailable'}}
            return value
        self.assertEqual(requests.run('scope',compute)['result_id'],'1')
        self.assertEqual(requests.run('scope',compute)['result_id'],'2')

    def test_cache_refresh_ttl_delete_and_copy_isolation(self):
        requests = AnalysisRequests(ttl=10)
        calls = []

        def compute():
            calls.append(1)
            return result(str(len(calls)))

        one = requests.run("scope", compute)
        self.assertFalse(one["delivery"]["cache_hit"])
        one["candidates"].clear()
        two = requests.run("scope", compute)
        self.assertTrue(two["delivery"]["cache_hit"])
        self.assertEqual(len(two["candidates"]), 1)
        self.assertEqual(requests.run("scope", compute, refresh=True)["result_id"], "2")
        requests.delete("2")
        self.assertEqual(requests.run("scope", compute)["result_id"], "3")
        with patch("analysis_requests.time.monotonic", return_value=time.monotonic()+11):
            self.assertEqual(requests.run("scope", compute)["result_id"], "4")
        self.assertEqual(requests.run("other-project", compute)["result_id"], "5")

    def test_identical_join_bounded_other_job_rejected(self):
        requests, entered, release = (
            AnalysisRequests(),
            threading.Event(),
            threading.Event(),
        )
        outputs = []

        def compute():
            entered.set()
            self.assertTrue(release.wait(2))
            return result()

        first = threading.Thread(
            target=lambda: outputs.append(requests.run("key", compute))
        )
        second = threading.Thread(
            target=lambda: outputs.append(requests.run("key", compute))
        )
        first.start()
        self.assertTrue(entered.wait(2))
        second.start()
        deadline = time.monotonic() + 2
        while not requests._pending["joined"] and time.monotonic() < deadline:
            time.sleep(0.001)
        with self.assertRaises(ApiError):
            requests.run("key", compute)
        with self.assertRaises(ApiError):
            requests.run("other", compute)
        release.set()
        first.join(2)
        second.join(2)
        self.assertEqual(len(outputs), 2)
        self.assertEqual(sum(o["delivery"]["joined_inflight"] for o in outputs), 1)
        self.assertEqual({o["result_id"] for o in outputs}, {"one"})

    def test_error_degraded_and_refresh_no_stale_fallback(self):
        requests = AnalysisRequests()
        requests.run("key", result)

        def broken():
            raise OSError("source failed")

        with self.assertRaises(OSError):
            requests.run("key", broken, refresh=True)
        with self.assertRaises(OSError):
            requests.run("key", broken)
        for kind in ("trace", "metrics", "warning", "sparse"):
            value = result()
            status = value["source_status"]
            if kind == "trace":
                status["traces"] = "unavailable"
            if kind == "metrics":
                status["metric_families_by_service"]["a"] = ["cpu"]
            if kind == "warning":
                status["annotations"] = ["partial"]
            if kind == "sparse":
                status["metric_point_coverage"]["a"]["cpu"] = 0.1
            count = []

            def compute():
                count.append(1)
                return value

            requests.run(kind, compute)
            requests.run(kind, compute)
            self.assertEqual(len(count), 2)

    def test_byte_quota_does_not_reject_valid_response(self):
        requests = AnalysisRequests(byte_limit=1)
        requests.run("key", result)
        self.assertFalse(requests.run("key", result)["delivery"]["cache_hit"])


if __name__ == "__main__":
    unittest.main()
