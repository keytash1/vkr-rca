"""Self-contained source HTTP -> frozen inference -> result contract.

Synthetic telemetry and a newly fitted healthy context, no incident truth or
research baseline. This does not replace the separately recorded real-source
connection checks or the research ranking regression.
"""

import json
import copy
from dataclasses import replace
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
                check = catalog["source_quality"]["baseline_applicability"]
                self.assertEqual(check["temporal_relation"], "OVERLAPS")
                self.assertEqual(check["reference_rps"], 4)
                self.assertIn("CURRENT_LOAD_CONFIGURED_NOT_MEASURED", check["reasons"])
                self.assertEqual(result["source_status"]["workload_source"], "profile_constant")
                # Supplemental HTTP facts cannot alter canonical inputs or ranks.
                from http_observations import CHANNELS, digest, summarize
                from test_http_observations import CONFIG
                from workspace_store import WorkspaceStore
                from profile_contract import contract_sha256
                from api_contract import document
                from jsonschema import Draft202012Validator
                original_profile = app.profiles['synthetic']
                app.profiles['synthetic'] = replace(original_profile, http_observations_config=copy.deepcopy(CONFIG))
                self.assertEqual(contract_sha256(original_profile), contract_sha256(app.profiles['synthetic']))
                app.workspace = WorkspaceStore(root / "workspace")
                def observed(profile, start, end):
                    matrices = {channel: {service: {stamp: value for stamp in range(left, left+31)}
                        for service in original_profile.services}
                        for channel, value in {'request_rate':5., 'error_ratio':.25, 'latency_p95':.1, 'presence':1.}.items()}
                    rows = summarize(matrices, original_profile.services, start, end, 1)
                    rows['config_sha256'] = digest(profile.http_observations_config)
                    return rows
                with patch('server.collect_http', side_effect=observed) as collector:
                    with post() as response:
                        enriched = json.load(response)
                    payload['force_refresh'] = False
                    with post() as response:
                        cached = json.load(response)
                    # Missing worker telemetry intentionally prevents reuse.
                    self.assertFalse(cached['delivery']['cache_hit'])
                    self.assertEqual(collector.call_count, 2)
                    cacheable = copy.deepcopy(enriched)
                    cacheable['source_status'].update(metrics='available', traces='available', annotations=[], span_count=1,
                        metric_families_by_service={s:list(CANONICAL_UNITS) for s in original_profile.services},
                        metric_point_coverage={s:{f:1 for f in CANONICAL_UNITS} for s in original_profile.services})
                    with patch.object(app, '_analyze_live', return_value=cacheable) as compute:
                        app.analyze_live('synthetic', left, left+30)
                        reused = app.analyze_live('synthetic', left, left+30)
                        self.assertTrue(reused['delivery']['cache_hit'])
                        self.assertEqual(compute.call_count, 1)
                        changed = copy.deepcopy(CONFIG)
                        changed['queries']['request_rate']['query'] += ' + 0'
                        app.profiles['synthetic'] = replace(original_profile, http_observations_config=changed)
                        app.analyze_live('synthetic', left, left+30)
                        self.assertEqual(compute.call_count, 2)
                self.assertEqual(enriched['candidates'], result['candidates'])
                self.assertEqual(enriched['input_sha256'], result['input_sha256'])
                self.assertEqual(enriched['feature_schema_sha256'], result['feature_schema_sha256'])
                saved = app.workspace.get_snapshot(enriched['result_id'])
                http_catalog = saved['catalog']
                self.assertEqual(http_catalog['catalog_version'], 'evidence-v4-service-http')
                self.assertEqual(http_catalog['observations'][:len(catalog['observations'])], catalog['observations'])
                http_facts = [f for f in http_catalog['observations'] if f['values'].get('family', '').startswith('http_')]
                self.assertEqual(len(http_facts), 2 * len(CHANNELS))
                self.assertEqual(http_facts[1]['values']['median'], .25)
                schema = document()
                for name, value in [('AnalysisResult', enriched), ('EvidenceCatalog', http_catalog)]:
                    Draft202012Validator({'$ref':'#/components/schemas/'+name, 'components':schema['components']}).validate(value)
                payload['force_refresh'] = True
                with patch('server.collect_http', side_effect=TimeoutError):
                    failed = app.analyze_live('synthetic', left, left+30, force_refresh=True)
                self.assertEqual(failed['candidates'], result['candidates'])
                self.assertEqual(failed['source_status']['http_observations']['status'], 'unavailable')
                failed_catalog = app.workspace.get_snapshot(failed['result_id'])['catalog']
                self.assertTrue(all(f['values']['median'] is None for f in failed_catalog['observations']
                                    if f['values'].get('family', '').startswith('http_')))
                app.profiles['synthetic'] = original_profile
                app.profiles['synthetic'] = replace(app.profiles['synthetic'], context_config={
                    'source_id':'unit','url':'http://127.0.0.1:1','service_label':'service_name',
                    'services':{'frontend':'frontend'},'labels':{}})
                with patch('server.collect_context', side_effect=TimeoutError):
                    degraded = app.analyze_live('synthetic',left,left+30,force_refresh=True)
                self.assertEqual(degraded['candidates'],result['candidates'])
                self.assertEqual(degraded['input_sha256'],result['input_sha256'])
                self.assertEqual(degraded['source_status']['incident_context']['services']['frontend'],'unavailable')
                with patch('server.collect_context', return_value={}), patch('server.attach_context', side_effect=ValueError):
                    projection_failure = app.analyze_live('synthetic',left,left+30,force_refresh=True)
                self.assertEqual(projection_failure['candidates'],result['candidates'])
                self.assertEqual(projection_failure['source_status']['incident_context']['status'],'projection_unavailable')
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
