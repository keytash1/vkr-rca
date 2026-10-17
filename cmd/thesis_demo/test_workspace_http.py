from http.server import ThreadingHTTPServer
from http.cookiejar import CookieJar
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

from server import DiagnosticApplication, make_handler
from investigations import InvestigationService
from workspace_store import WorkspaceStore
from test_workspace_store import snapshot
from jsonschema import Draft202012Validator
from api_contract import document
from workspace_http import validate_local_origin

ROOT = Path(__file__).resolve().parents[2]


class WorkspaceHTTPTests(unittest.TestCase):
    def test_container_origin_is_explicit_and_forwarded_headers_not_trusted(self):
        expected = "http://127.0.0.1:19999"
        self.app.workspace_http.expected_origin = validate_local_origin(expected)
        self.assertEqual(self.request("/api/v2/workspace")[0], 403)
        # Internal container probe remains non-sensitive; the actual APIs keep
        # the exact published Host/Origin guard instead of weakening it.
        status, probe, headers = self.request("/healthz")
        self.assertIn(status, (200, 503))
        self.assertEqual(set(probe), {"status"})
        self.assertIn(probe["status"], ("ready", "not_configured"))
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(self.request("/api/health")[0], 403)
        status, value, _ = self.request("/api/v2/workspace", headers={"Host": "127.0.0.1:19999", "Origin": expected})
        self.assertEqual(status, 200)
        self.csrf = value["csrf_token"]
        for origin in (self.base, "http://localhost:19999", "https://attacker.invalid"):
            self.assertEqual(self.request("/api/v2/investigations", {}, headers={
                "Host": "127.0.0.1:19999", "Origin": origin})[0], 403)
        self.assertEqual(self.request("/api/v2/workspace", headers={"X-Forwarded-Host": "127.0.0.1:19999"})[0], 403)
        for value in ("https://127.0.0.1:19999", "http://0.0.0.0:19999", "http://127.0.0.1:19999/",
                      "http://user@localhost:19999", "http://localhost:0", "http://localhost", "http://localhost:19999?q=x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_local_origin(value)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.temp.name) / "workspace")
        self.store.put_snapshot(*snapshot(), project="project-unit")
        self.service = InvestigationService(self.store)
        self.app = DiagnosticApplication(
            ROOT,
            Path(self.temp.name) / "empty-profiles",
            workspace=self.store,
            investigations=self.service,
        )
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = None

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)
        self.service.close()
        self.temp.cleanup()

    def request(self, path, payload=None, headers=None):
        h = {}
        if payload is not None:
            h = {
                "Content-Type": "application/json",
                "Origin": self.base,
                "X-RCA-CSRF": self.csrf or "",
            }
        h.update(headers or {})
        req = Request(
            self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=h,
        )
        try:
            response = self.client.open(req, timeout=5)
        except HTTPError as e:
            response = e
        with response:
            return response.status, json.load(response), dict(response.headers)

    def login(self):
        status, value, headers = self.request("/api/v2/workspace")
        self.assertEqual(status, 200)
        self.csrf = value["csrf_token"]
        return headers

    def test_host_origin_cookie_and_csrf_before_any_mutation(self):
        status, e, _ = self.request("/api/v2/investigations")
        self.assertEqual((status, e["code"]), (401, "SESSION_REQUIRED"))
        headers = self.login()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        for overrides, code in (
            ({"Host": f"attacker.invalid:{self.http.server_port}"}, "HOST_NOT_ALLOWED"),
            ({"Origin": "https://attacker.invalid"}, "ORIGIN_NOT_ALLOWED"),
            ({"X-RCA-CSRF": "invalid"}, "CSRF_REQUIRED"),
            ({"Sec-Fetch-Site": "cross-site"}, "ORIGIN_NOT_ALLOWED"),
        ):
            status, e, _ = self.request("/api/v2/investigations", {}, headers=overrides)
            self.assertEqual((status, e["code"]), (403, code))
        self.assertEqual(self.store.list_investigations(), [])

    def test_history_query_contract_and_invalid_filters(self):
        self.login()
        status,value,_=self.request('/api/v2/investigations?service=alpha&category=latency&limit=100')
        self.assertEqual(status,200)
        self.assertEqual(value['period_basis'],'INVESTIGATION_CREATED_AT')
        self.assertEqual(value['investigations'],[])
        for query in ('limit=101','after=nan','after=200&before=100','service=a&service=b',
                      'url=http://outside','category=','action_status=execute'):
            with self.subTest(query=query):
                self.assertEqual(self.request('/api/v2/investigations?'+query)[0],400)

    def test_review_requires_saved_owner_conclusion_and_revision(self):
        self.login()
        identifier,_=self.store.create_investigation('analysis-unit',{'mode':'B'},idempotency_key='review')
        route='/api/v2/investigations/'+identifier
        status,error,_=self.request(route+'/review',{'expected_revision':0})
        self.assertEqual((status,error['code']),(400,'RECORD_REVIEW_OWNER_CONCLUSION_REQUIRED'))
        record=self.store.get_investigation(identifier)['record'] | {
            'metadata':{'owner':'Engineer','incident':'','category':''},'conclusion':'Unresolved'}
        self.assertEqual(self.request(route+'/record',{'expected_revision':0,'record':record})[0],200)
        status,reviewed,_=self.request(route+'/review',{'expected_revision':1})
        self.assertEqual(status,200)
        Draft202012Validator({'$ref':'#/components/schemas/Investigation','components':document()['components']}).validate(reviewed)
        self.assertIn('approval',reviewed['record'])
        self.assertEqual(self.request(route+'/review',{'expected_revision':1})[0],409)
        self.assertEqual(self.request(route+'/review',{'expected_revision':2},headers={'X-RCA-CSRF':'wrong'})[0],403)

    def test_snapshot_create_repeat_update_and_export_scope(self):
        self.login()
        payload = {
            "analysis_id": "analysis-unit",
            "mode": "B",
            "question": "Check",
            "idempotency_key": "one",
        }
        status, job, _ = self.request("/api/v2/investigations", payload)
        self.assertEqual(status, 202)
        Draft202012Validator(
            {
                "$ref": "#/components/schemas/Investigation",
                "components": document()["components"],
            }
        ).validate(job)
        status, repeated, _ = self.request("/api/v2/investigations", payload)
        self.assertEqual(status, 200)
        self.assertEqual(job["id"], repeated["id"])
        status, e, _ = self.request(
            "/api/v2/investigations", payload | {"question": "Different"}
        )
        self.assertEqual((status, e["code"]), (409, "STORE_IDEMPOTENCY_CONFLICT"))
        path = "/api/v2/investigations/" + job["id"]
        status, current, _ = self.request(path)
        self.assertEqual(status, 200)
        record = current["record"] | {
            "title": "A real investigation",
            "conclusion": "Not yet confirmed",
        }
        status, saved, _ = self.request(
            path + "/record", {"expected_revision": 0, "record": record}
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(
            self.request(path + "/record", {"expected_revision": 0, "record": record})[
                0
            ],
            409,
        )
        status, snapshot_value, _ = self.request(
            "/api/v2/analyses/analysis-unit/snapshot"
        )
        self.assertEqual(status, 200)
        self.assertEqual(snapshot_value["project"], "project-unit")
        status, e, _ = self.request(
            "/api/v2/investigations",
            payload | {"analysis_id": "other-analysis", "idempotency_key": "other"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            self.request("/api/v2/analyses/analysis-unit/delete", {})[1],
            {"deleted": True},
        )
        self.assertEqual(self.request(path)[0], 404)

    def test_daily_allowance_rejects_before_worker_and_keeps_b_available(self):
        self.login()
        self.store.assistant_daily_jobs=1
        self.store.create_investigation("analysis-unit",{"mode":"D"},idempotency_key="earlier")
        calls=[]
        self.service.python_executable="unused"
        self.service.state_dir="unused"
        self.service.model="unit"
        self.service.allowed_profiles=frozenset(["project-unit"])
        self.service.runner=lambda **kwargs: calls.append(kwargs) or {"status":"failed","report":None}
        payload={"analysis_id":"analysis-unit","mode":"D","question":"Check","idempotency_key":"new"}
        status,value,_=self.request("/api/v2/investigations",payload)
        self.assertEqual((status,value["code"]),(429,"STORE_ASSISTANT_DAILY_LIMIT"))
        self.assertIn("24 часа",value["error"])
        self.assertEqual(calls,[])
        status,capabilities,_=self.request("/api/v2/workspace")
        self.assertEqual(status,200)
        self.assertEqual(capabilities["assistant_budget"]["remaining_jobs"],0)
        self.assertEqual(self.request("/api/v2/investigations",payload|{"mode":"B"})[0],202)


if __name__ == "__main__":
    unittest.main()
