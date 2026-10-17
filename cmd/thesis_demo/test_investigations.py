import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from investigations import InvestigationService, InvestigationError, restore_report_identity, previous_discussion
from workspace_store import WorkspaceStore
from test_workspace_store import snapshot


class InvestigationTests(unittest.TestCase):
    def test_action_proposal_identity_round_trip_without_rewriting_prose(self):
        from assistant_contract import validate_report
        mapping={"services":{"alpha":"svc-001"},"observations":{"real-fact":"obs-001"}}
        report={"summary":"svc-001 remains a hypothesis", "hypotheses":[],"data_gaps":[],"limitations":[],
            "action_proposals":[{"service":"svc-001","purpose":"preventive","title":"Check before changing svc-001",
                "rationale":"Conditional","verification_plan":"Compare before and after","evidence_ids":["obs-001"]}]}
        outcome=restore_report_identity({"report":report},mapping)
        self.assertEqual(outcome['report']['action_proposals'][0]['service'],'alpha')
        self.assertEqual(outcome['report']['action_proposals'][0]['evidence_ids'],['real-fact'])
        self.assertEqual(outcome['report']['summary'],report['summary'])
        clean={"services":["svc-001"],"observations":[{"id":"obs-001"}]}
        discussion=previous_discussion([{"state":"completed","outcome":outcome,"request":{"mode":"D","question":"Check alpha"}}],mapping,clean)
        self.assertEqual(discussion[0]['report'],report)
        validate_report(discussion[0]['report'],clean)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.temp.name) / "workspace")
        self.store.put_snapshot(*snapshot(), project="project-unit")
        self.service = None

    def tearDown(self):
        if self.service:
            self.service.close()
        self.temp.cleanup()

    def start(self, **kwargs):
        self.service = InvestigationService(self.store, **kwargs)
        return self.service

    def finished(self, identifier):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = self.store.get_investigation(identifier)
            if job["state"] not in {"queued", "running", "cancelling"}:
                return job
            time.sleep(0.005)
        self.fail("job did not finish")

    def test_without_llm_records_and_deterministic_checks_still_work(self):
        service = self.start()
        job, fresh = service.submit("analysis-unit", idempotency_key="unit")
        self.assertTrue(fresh)
        done = self.finished(job["id"])
        self.assertEqual(done["state"], "completed")
        self.assertEqual(done["outcome"]["usage"]["model_calls"], 0)
        with self.assertRaisesRegex(
            InvestigationError, "ASSISTANT_PROFILE_NOT_APPROVED"
        ):
            service.submit("analysis-unit", mode="D", idempotency_key="external")
        with self.assertRaisesRegex(InvestigationError, "INVESTIGATION_MODE_INVALID"):
            service.submit("analysis-unit", mode="E", idempotency_key="blind")

    def test_double_manager_cannot_interrupt_owning_process(self):
        self.start()
        with self.assertRaisesRegex(InvestigationError, "WORKSPACE_ALREADY_RUNNING"):
            InvestigationService(self.store)

    def test_queue_bounded_idempotency_and_cancel_before_start_never_calls_model(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def runner(**kwargs):
            calls.append(kwargs)
            entered.set()
            while not release.is_set() and not kwargs["cancel"].is_set():
                time.sleep(0.005)
            return {
                "status": "completed",
                "report": {
                    "summary": "No cause established.",
                    "hypotheses": [],
                    "data_gaps": [],
                    "limitations": [],
                },
                "usage": {"model_calls": 1, "accounting_complete": True},
            }

        service = self.start(
            python_executable="unused",
            state_dir="unused",
            model="unit",
            allowed_profiles=["project-unit"],
            runner=runner,
        )
        first, _ = service.submit("analysis-unit", mode="D", idempotency_key="first")
        self.assertTrue(entered.wait(1))
        second, _ = service.submit("analysis-unit", mode="D", idempotency_key="second")
        repeated, fresh = service.submit(
            "analysis-unit", mode="D", idempotency_key="first"
        )
        self.assertFalse(fresh)
        self.assertEqual(repeated["id"], first["id"])
        with self.assertRaisesRegex(InvestigationError, "WORKSPACE_BUSY"):
            service.submit("analysis-unit", mode="D", idempotency_key="third")
        service.cancel(second["id"])
        service.cancel(first["id"])
        self.assertEqual(self.finished(first["id"])["state"], "cancelled")
        cancelled = self.finished(second["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(
            cancelled["outcome"]["remote_generation_stopped"], "NOT_STARTED"
        )
        self.assertEqual(len(calls), 1)

    def test_only_approved_pseudonymous_aggregate_scope_reaches_worker(self):
        calls = []

        def runner(**kwargs):
            calls.append(kwargs)
            c = kwargs["catalog"]
            h = {
                "service": c["services"][0],
                "statement": "CPU needs a check.",
                "supporting_evidence_ids": [c["observations"][0]["id"]],
                "contradicting_evidence_ids": [],
                "unknowns": ["No symptom."],
                "next_checks": [],
            }
            return {
                "status": "completed",
                "report": {
                    "summary": "Check svc-001.",
                    "hypotheses": [h],
                    "data_gaps": [],
                    "limitations": [],
                },
            }

        service = self.start(
            python_executable="unused",
            state_dir="unused",
            model="unit",
            allowed_profiles=["project-unit"],
            runner=runner,
        )
        job, _ = service.submit("analysis-unit", mode="D", idempotency_key="first")
        done = self.finished(job["id"])
        self.assertNotIn("SECRET", json.dumps(calls[0]["catalog"]))
        self.assertNotIn("alpha", json.dumps(calls[0]["catalog"]))
        h = done["outcome"]["report"]["hypotheses"][0]
        self.assertEqual(h["service"], "alpha")
        self.assertEqual(h["supporting_evidence_ids"], ["obs-a"])
        self.assertEqual(
            done["outcome"]["local_identity_legend"]["services"]["svc-001"], "alpha"
        )
        record = done["record"] | {"title": "Human conclusion stays"}
        self.store.save_record(done["id"], record, expected_revision=0)
        again, fresh = service.follow_up(
            done["id"],
            mode="D",
            question="What contradicts the first hypothesis about alpha?",
            idempotency_key="follow",
        )
        self.assertTrue(fresh)
        final = self.finished(again["id"])
        self.assertEqual(final["record"]["title"], "Human conclusion stays")
        self.assertEqual(len(final["turns"]), 2)
        self.assertEqual(len(calls[1]["conversation"]), 1)
        self.assertEqual(
            calls[1]["conversation"][0]["report"]["hypotheses"][0]["service"], "svc-001"
        )
        self.assertNotIn("alpha", calls[1]["question"])


if __name__ == "__main__":
    unittest.main()
