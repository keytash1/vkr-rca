"""Self-contained source HTTP -> frozen inference -> result contract.

Synthetic telemetry and a newly fitted healthy context, no incident truth or
research baseline. This does not replace the separately recorded real-source
connection checks or the research ranking regression.
"""

import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from profile_setup import prepare
from profile_test_fixtures import profile_document
from rca_ml.m12_adapter import CANONICAL_UNITS
from runtime_assets import EXPECTED_SHA256
from server import DiagnosticApplication, make_handler
from telemetry_test_fixtures import FakeTelemetry

ROOT = Path(__file__).resolve().parents[2]


class ProductHTTPTests(unittest.TestCase):
    def test_complete_path_missing_candidate_and_source_failure(self):
        source = ThreadingHTTPServer(("127.0.0.1",0),FakeTelemetry)
        source_thread = threading.Thread(target=source.serve_forever,daemon=True)
        source_thread.start()
        self.addCleanup(source_thread.join,2)
        self.addCleanup(source.server_close)
        self.addCleanup(source.shutdown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in EXPECTED_SHA256:
                target = root/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/name).read_bytes())
            raw = profile_document()
            raw["candidate_services"] = ["frontend","worker"]
            raw["metrics"]["url"] = f"http://127.0.0.1:{source.server_port}"
            raw["traces"] = {"url":raw["metrics"]["url"],"query_services":["frontend"]}
            raw["workload"] = {"fixed_requests_per_second":4}
            path = root/"profiles/synthetic.json"
            path.parent.mkdir()
            path.write_text(json.dumps(raw))
            left,right = 1700000000,1700000100
            healthy = {"requests_per_second":4,"metrics":[
                {"timestamp":t,"service":service,"family":family,"value":1.0,"unit":unit}
                for service in raw["candidate_services"] for family,unit in CANONICAL_UNITS.items()
                for t in range(left,right+1)],"traces":[
                {"service":service,"trace_id":"healthy","span_id":service,"parent_span_id":None,
                 "peer_service":None,"span_kind":"SERVER","start_time_us":(left+10)*1000000,
                 "duration_us":10000,"error":False,"status_code":"OK"}
                for service in raw["candidate_services"]]}
            healthy_status = {"traces":"available","metric_families_by_service":{
                service:list(CANONICAL_UNITS) for service in raw["candidate_services"]}}
            with patch("profile_setup.collect",return_value=(healthy,healthy_status)):
                prepare(root,path,left,right)
            app = DiagnosticApplication(root,path.parent)
            http = ThreadingHTTPServer(("127.0.0.1",0),make_handler(app))
            thread = threading.Thread(target=http.serve_forever,daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{http.server_port}"
                payload = {"profile_id":"synthetic","start_unix":left,"end_unix":left+30,"force_refresh":True}
                def post():
                    return urlopen(Request(base+"/api/analyze",data=json.dumps(payload).encode(),
                        headers={"Content-Type":"application/json"}),timeout=20)
                with post() as response:
                    result = json.load(response)
                    self.assertEqual(response.status,200)
                self.assertEqual({c["service"] for c in result["candidates"]},{"frontend","worker"})
                self.assertEqual(result["candidate_count"],2)
                self.assertIn("worker",result["source_status"]["services_without_spans"])
                self.assertEqual(result["source_status"]["metric_families_by_service"]["worker"],[])
                self.assertEqual(result["source_status"]["baseline_binding"]["state"],"active")
                with urlopen(base+f"/api/v2/analyses/{result['result_id']}/evidence") as response:
                    catalog = json.load(response)
                self.assertEqual(catalog["input_sha256"],result["input_sha256"])
                with patch.object(FakeTelemetry,"fail_metrics",True):
                    with self.assertRaises(HTTPError) as failure:
                        post()
                    self.assertEqual(failure.exception.code,502)
                    failure.exception.close()
            finally:
                http.shutdown()
                http.server_close()
                thread.join(2)


if __name__ == "__main__":
    unittest.main()
