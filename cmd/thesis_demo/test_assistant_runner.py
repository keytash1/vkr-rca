"""Semantic boundary properties using a controllable provider, never real usage."""
import copy
import json
import threading
import unittest
from unittest.mock import patch

from assistant_context import assistant_context
from assistant_contract import AssistantContractError, AssistantLimits, ProviderReply, parse_report
from assistant_runner import run_snapshot


def catalog():
    return {"services": ["beta", "alpha"], "start_unix": 100, "end_unix": 110,
        "requests_per_second": 5, "source_quality": {"traces": "unavailable", "sampling": "UNKNOWN"},
        "limitations": ["SAMPLING_UNKNOWN"], "root_service": "SECRET_GOLD",
        "observations": [{"id": "obs-a", "service": "alpha", "kind": "metric",
            "start_unix": 100, "end_unix": 110, "model_score": "SECRET_RANK",
            "values": {"family": "cpu", "unit": "cores", "samples": 2,
                "min": 2, "median": 3, "max": 4, "state": "OBSERVED", "returned_point_coverage": .8,
                "baseline_comparison": None, "series": [{"start_unix": 100, "end_unix": 110,
                    "min": 2, "max": 4, "mean": 3, "samples": 2, "rank": "SECRET_RANK"}]},
            "source_links": [{"url": "https://invalid.example/SECRET_URL"}]}]}


def report():
    return {"summary": "Требуется проверка нагрузки.", "hypotheses": [{"service": "alpha",
        "statement": "Наблюдается изменение CPU; причина не подтверждена.",
        "supporting_evidence_ids": ["obs-a"], "contradicting_evidence_ids": [],
        "unknowns": ["Нет сопоставимого здорового периода."], "next_checks": [{
            "action": "Сопоставить нагрузку со здоровым периодом.",
            "expected_observation": "Проверить наличие сходной нагрузки.", "evidence_ids": ["obs-a"]}]}],
        "data_gaps": ["Трассировки недоступны."], "limitations": ["Причина не доказана."], "action_proposals": []}


class FakeProvider:
    def __init__(self, *replies, callback=None):
        self.replies, self.calls, self.callback = list(replies), [], callback

    def complete(self, **kwargs):
        self.calls.append(copy.deepcopy({k: v for k, v in kwargs.items() if k != "cancel"}))
        if self.callback:
            self.callback()
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, ProviderReply) else ProviderReply(
            json.dumps(value, ensure_ascii=False), "unit-model", "unit-id", 500, 100, .01)


class RunnerTests(unittest.TestCase):
    def test_c_uses_same_budget_estimator_policy_as_tools(self):
        with patch('assistant_runner.reserve_input',return_value=(100,'UNIT_ESTIMATE')):
            outcome=run_snapshot(FakeProvider(report()),model='unit-model',catalog=catalog(),limits=AssistantLimits(input_tokens=2000))
        self.assertEqual(outcome['status'],'completed')
        self.assertEqual(outcome['events'][0]['reservation_method'],'UNIT_ESTIMATE')

    def test_complete_report_preserves_all_candidates_and_omission_notice(self):
        source = catalog(); before = copy.deepcopy(source)
        provider = FakeProvider(report())
        result = run_snapshot(provider, model="unit-model", catalog=source)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(source, before)
        self.assertEqual(result["usage"]["model_calls"], 1)
        self.assertTrue(result["usage"]["accounting_complete"])
        self.assertIsNone(result["fallback"])
        supplied = provider.calls[0]
        self.assertFalse(supplied["response_schema"]["additionalProperties"])
        content = supplied["input_items"][0]["content"]
        self.assertNotIn("SECRET", content)
        context = json.loads(content)["observations"]
        self.assertEqual(context["services"], ["alpha", "beta"])
        self.assertEqual(context["projection"]["candidates_included"], 2)
        self.assertIn("metric.series", context["projection"]["omitted_detail_fields"])
        self.assertEqual(context["source_quality"]["traces"], "unavailable")

    def test_one_repair_then_fallback_never_displays_bad_report(self):
        invalid = report(); invalid["hypotheses"][0]["service"] = "other-project"
        provider = FakeProvider(invalid, report())
        result = run_snapshot(provider, model="unit-model", catalog=catalog())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage"]["model_calls"], 2)
        provider = FakeProvider(invalid, invalid)
        result = run_snapshot(provider, model="unit-model", catalog=catalog())
        self.assertEqual(result["stop_reason"], "ASSISTANT_INVALID_REPORT")
        self.assertIsNone(result["report"])
        self.assertEqual(result["fallback"]["mode"], "B")

    def test_provider_failure_does_not_retry_or_expose_secrets_and_records_unknown_usage(self):
        provider = FakeProvider(RuntimeError("SECRET_TOKEN upstream text"))
        result = run_snapshot(provider, model="unit-model", catalog=catalog())
        self.assertEqual(len(provider.calls), 1)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertFalse(result["usage"]["accounting_complete"])
        self.assertEqual(result["usage"]["unaccounted_attempts"], 1)

    def test_input_usage_limits_and_cancel_never_masquerade_as_completion(self):
        provider = FakeProvider(report())
        result = run_snapshot(provider, model="unit-model", catalog=catalog(), limits=AssistantLimits(input_tokens=100))
        self.assertEqual(result["stop_reason"], "ASSISTANT_INPUT_BUDGET")
        self.assertEqual(provider.calls, [])
        provider = FakeProvider(ProviderReply(json.dumps(report()), "unit-model", "id", 500, 3001, .1))
        result = run_snapshot(provider, model="unit-model", catalog=catalog())
        self.assertEqual(result["stop_reason"], "ASSISTANT_USAGE_BUDGET")
        self.assertIsNone(result["report"])
        event = threading.Event(); event.set()
        provider = FakeProvider(report())
        result = run_snapshot(provider, model="unit-model", catalog=catalog(), cancel=event)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(provider.calls, [])
        event.clear()
        provider = FakeProvider(report(), callback=event.set)
        result = run_snapshot(provider, model="unit-model", catalog=catalog(), cancel=event)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["usage"]["known_output_tokens"], 100)

    def test_blind_context_is_unchanged_when_rank_is_poisoned(self):
        source = catalog(); hint = [{"service": "beta", "rank": 1, "model_score": .9},
                                    {"service": "alpha", "rank": 2, "model_score": -.4}]
        neutral = assistant_context(source, summary_only=True)
        source["ranking"] = hint
        source["services"].reverse(); source["observations"].reverse()
        self.assertEqual(neutral, assistant_context(source, summary_only=True))
        provider = FakeProvider(report())
        result = run_snapshot(provider, model="unit-model", catalog=source, ranking=hint)
        self.assertEqual(result["mode"], "C")
        self.assertIn("ranking_hint", json.loads(provider.calls[0]["input_items"][0]["content"])["observations"])
        with self.assertRaises(ValueError):
            assistant_context(source, ranking=[hint[0], hint[0]])

    def test_invalid_json_duplicate_keys_inconsistent_refs_and_limits(self):
        for value in ('{"summary":"a","summary":"b"}', '{"x":NaN}', '```json\n{}\n```', '[' * 1100):
            with self.subTest(value=value[:20]), self.assertRaises(AssistantContractError):
                parse_report(value, catalog())
        invalid = report(); invalid["hypotheses"][0]["contradicting_evidence_ids"] = ["obs-a"]
        with self.assertRaisesRegex(AssistantContractError, "REPORT_CONFLICTING_REFERENCE"):
            parse_report(json.dumps(invalid), catalog())
        for overrides in ({"wall_seconds": 61}, {"model_calls": True}, {"input_tokens": 0}):
            with self.assertRaises(AssistantContractError):
                AssistantLimits(**overrides)


if __name__ == "__main__":
    unittest.main()
