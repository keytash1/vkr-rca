import copy
import json
import threading
import unittest
from unittest.mock import patch

from assistant_contract import AssistantLimits, ProviderReply, AssistantContractError
from assistant_workflow import run_with_tools
from test_assistant_runner import catalog, report, FakeProvider
from test_assistant_tools import call


def tool_reply(*calls):
    return ProviderReply(
        "",
        "unit-model",
        "unit-id",
        100,
        30,
        0.01,
        tuple(calls),
        tuple({"type": "function_call", **c} for c in calls),
    )


class WorkflowTests(unittest.TestCase):
    def test_large_followup_reserves_final_before_spending_on_tools(self):
        provider=FakeProvider(report())
        conversation=[{"question":"Previous question","report":report(),"mode":"D"}]
        with patch("assistant_workflow.reserve_input",return_value=(7000,"UNIT")):
            result=run_with_tools(provider,model="unit-model",catalog=catalog(),
                ranking=[{"service":"alpha","rank":1,"model_score":0.1},
                         {"service":"beta","rank":2,"model_score":0.0}],
                conversation=conversation)
        self.assertEqual(result["status"],"completed")
        self.assertEqual(len(provider.calls),1)
        self.assertIsNone(provider.calls[0]["tools"])
        self.assertIsNotNone(provider.calls[0]["response_schema"])
        self.assertIn("prior_discussion",provider.calls[0]["input_items"][0]["content"])
        self.assertEqual(result["usage"]["tool_calls"],0)
        self.assertTrue(any(e["kind"]=="followup_final_reserved" for e in result["events"]))

    def test_small_followup_still_can_read_discriminating_details(self):
        provider=FakeProvider(tool_reply(call("get_candidate_evidence",{"service":"alpha"})),report())
        with patch("assistant_workflow.reserve_input",return_value=(100,"UNIT")):
            result=run_with_tools(provider,model="unit-model",catalog=catalog(),
                ranking=[{"service":"alpha","rank":1,"model_score":0.1},
                         {"service":"beta","rank":2,"model_score":0.0}],
                conversation=[{"question":"Previous","report":report(),"mode":"D"}])
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["usage"]["tool_calls"],1)
        self.assertIsNotNone(provider.calls[0]["tools"])

    def test_runbook_citation_requires_actual_read_and_has_server_provenance(self):
        runbook = {"id": "rb-traces", "version": "1", "section": "sample", "topic": "traces", "text": "Guidance, not incident evidence."}
        answer = report()
        answer["summary"] = "Suggested check from rb-traces, version 1, sample."
        with patch("assistant_workflow.reserve_input", return_value=(100, "UNIT")):
            rejected = run_with_tools(FakeProvider(answer, answer), model="unit-model", catalog=catalog(), runbooks=[runbook])
            self.assertEqual(rejected["status"], "failed")
            self.assertIsNone(rejected["report"])
            self.assertTrue(any(e.get("code") == "REPORT_UNREAD_RUNBOOK_REFERENCE" for e in rejected["events"]))
            accepted = run_with_tools(FakeProvider(tool_reply(call("search_runbooks", {"topic": "traces"})), answer),
                                      model="unit-model", catalog=catalog(), runbooks=[runbook])
        self.assertEqual(accepted["status"], "completed")
        reference = accepted["consulted_runbooks"][0]
        self.assertEqual((reference["id"], reference["version"], reference["section"]), ("rb-traces", "1", "sample"))
        self.assertEqual(len(reference["sha256"]), 64)

    def test_blind_mode_refuses_even_valid_previously_hinted_answer(self):
        conversation = [{"question": "Prior question", "report": report(), "mode": "D"}]
        provider = FakeProvider(report())
        with self.assertRaisesRegex(
            AssistantContractError, "ASSISTANT_BLIND_DISCUSSION_NOT_ALLOWED"
        ):
            run_with_tools(
                provider,
                model="unit-model",
                catalog=catalog(),
                conversation=conversation,
            )
        self.assertEqual(provider.calls, [])

    def test_real_loop_protocol_tool_output_then_final_report_and_unchanged_snapshot(
        self,
    ):
        source = catalog()
        before = copy.deepcopy(source)
        provider = FakeProvider(
            tool_reply(call("get_candidate_evidence", {"service": "alpha"})), report()
        )
        outcome = run_with_tools(provider, model="unit-model", catalog=source)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["mode"], "E")
        self.assertEqual(outcome["usage"]["tool_calls"], 1)
        self.assertEqual(outcome["usage"]["tool_steps"], 1)
        self.assertEqual(
            provider.calls[1]["input_items"][-1]["type"], "function_call_output"
        )
        self.assertEqual(source, before)
        self.assertNotIn("SECRET", json.dumps(outcome))

    def test_d_and_e_share_tools_and_catalog_but_only_d_gets_explicit_hint(self):
        source = catalog()
        hint = [
            {"service": "beta", "rank": 1, "model_score": 0.9},
            {"service": "alpha", "rank": 2, "model_score": -0.4},
        ]
        p1, p2 = FakeProvider(report()), FakeProvider(report())
        d = run_with_tools(p1, model="unit-model", catalog=source, ranking=hint)
        e = run_with_tools(p2, model="unit-model", catalog=source)
        self.assertEqual((d["mode"], e["mode"]), ("D", "E"))
        for field in (
            "tool_data_sha256",
            "tools_sha256",
            "prompt_sha256",
            "report_schema_sha256",
            "limits",
        ):
            self.assertEqual(d[field], e[field])
        dc = json.loads(p1.calls[0]["input_items"][0]["content"])
        ec = json.loads(p2.calls[0]["input_items"][0]["content"])
        self.assertEqual(dc["observations"].pop("ranking_hint"), hint)
        self.assertEqual(dc, ec)

    def test_rejected_or_repeated_call_stops_with_safe_fallback(self):
        for item in (
            call("get_candidate_evidence", {"service": "other-project"}),
            call("shell", {"command": "SECRET"}),
        ):
            outcome = run_with_tools(
                FakeProvider(tool_reply(item)), model="unit-model", catalog=catalog()
            )
            self.assertEqual(outcome["status"], "failed")
            self.assertIsNone(outcome["report"])
            self.assertEqual(outcome["fallback"]["mode"], "B")
            self.assertNotIn("SECRET", json.dumps(outcome))
        same = call("get_candidate_evidence", {"service": "alpha"})
        with patch(
            "assistant_workflow.reserve_input", return_value=(100, "UNIT_ESTIMATE")
        ):
            outcome = run_with_tools(
                FakeProvider(tool_reply(same), tool_reply(same)),
                model="unit-model",
                catalog=catalog(),
            )
        self.assertEqual(outcome["stop_reason"], "ASSISTANT_REPEATED_TOOL_CALL")
        self.assertEqual(outcome["usage"]["tool_calls"], 1)

    def test_batch_budget_and_final_call_do_not_execute_more_tools(self):
        calls = [
            call("get_candidate_evidence", {"service": "alpha"}, str(i))
            for i in range(7)
        ]
        outcome = run_with_tools(
            FakeProvider(tool_reply(*calls)), model="unit-model", catalog=catalog()
        )
        self.assertEqual(outcome["stop_reason"], "ASSISTANT_TOOL_BUDGET")
        self.assertEqual(outcome["usage"]["tool_calls"], 0)
        provider = FakeProvider(
            tool_reply(call("get_candidate_evidence", {"service": "alpha"})), report()
        )
        outcome = run_with_tools(
            provider,
            model="unit-model",
            catalog=catalog(),
            limits=AssistantLimits(tool_steps=1),
        )
        self.assertEqual(outcome["status"], "completed")
        self.assertIsNone(provider.calls[1]["tools"])
        self.assertIsNotNone(provider.calls[1]["response_schema"])

    def test_cancel_unknown_usage_and_budget_have_no_false_success(self):
        event = threading.Event()
        event.set()
        provider = FakeProvider(report())
        outcome = run_with_tools(
            provider, model="unit-model", catalog=catalog(), cancel=event
        )
        self.assertEqual(outcome["status"], "cancelled")
        self.assertEqual(provider.calls, [])
        outcome = run_with_tools(
            FakeProvider(RuntimeError("SECRET upstream")),
            model="unit-model",
            catalog=catalog(),
        )
        self.assertFalse(outcome["usage"]["accounting_complete"])
        self.assertIsNone(outcome["report"])
        outcome = run_with_tools(
            FakeProvider(report()),
            model="unit-model",
            catalog=catalog(),
            limits=AssistantLimits(input_tokens=100),
        )
        self.assertEqual(outcome["usage"]["model_calls"], 0)
        self.assertEqual(outcome["stop_reason"], "ASSISTANT_INPUT_BUDGET")


if __name__ == "__main__":
    unittest.main()
