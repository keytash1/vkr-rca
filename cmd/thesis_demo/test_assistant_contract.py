import copy
import unittest

from assistant_contract import AssistantContractError, report_schema, validate_report, parse_report
import json


class AssistantReportTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"services": ["alpha", "beta"], "observations": [{"id": "obs-local"}]}
        self.report = {"summary": "Наблюдается изменение; требуется проверка.", "hypotheses": [{
            "service": "alpha", "statement": "Возможна локальная проблема.",
            "supporting_evidence_ids": ["obs-local"], "contradicting_evidence_ids": [],
            "unknowns": ["Нет данных о развёртывании."], "next_checks": [{
                "action": "Сопоставить интервал с изменением нагрузки.",
                "expected_observation": "Проверить, совпадают ли моменты изменений.",
                "evidence_ids": ["obs-local"]}]}], "data_gaps": [], "limitations": ["Причина не подтверждена."]}

    def test_valid_report_and_honest_abstention(self):
        self.assertEqual(validate_report(self.report, self.catalog), self.report)
        abstention = self.report | {"summary": "Данных недостаточно.", "hypotheses": []}
        self.assertEqual(validate_report(abstention, self.catalog), abstention)

    def test_legacy_storage_is_readable_but_new_provider_must_include_action_field(self):
        self.assertEqual(validate_report(self.report,self.catalog),self.report)
        with self.assertRaisesRegex(AssistantContractError,"REPORT_ACTION_PROPOSALS_REQUIRED"):
            parse_report(json.dumps(self.report),self.catalog)
        current=self.report | {"action_proposals":[]}
        self.assertEqual(parse_report(json.dumps(current),self.catalog),current)

    def test_unknown_fields_arbitrary_links_and_cross_scope_are_rejected(self):
        for field, value in (("confidence", .99), ("url", "https://evil.invalid"), ("executed", True)):
            invalid = copy.deepcopy(self.report); invalid["hypotheses"][0][field] = value
            with self.subTest(field=field), self.assertRaises(AssistantContractError):
                validate_report(invalid, self.catalog)
        for key, value in (("service", "other-project"), ("supporting_evidence_ids", ["obs-another-session"]),
                           ("contradicting_evidence_ids", ["obs-local", "obs-local"])):
            invalid = copy.deepcopy(self.report); invalid["hypotheses"][0][key] = value
            with self.subTest(key=key), self.assertRaises(AssistantContractError):
                validate_report(invalid, self.catalog)

    def test_size_and_type_limits_are_enforced(self):
        for key, value in (("summary", "x" * 1201), ("hypotheses", {}), ("data_gaps", [1])):
            with self.subTest(key=key), self.assertRaises(AssistantContractError):
                validate_report(self.report | {key: value}, self.catalog)

    def test_provider_schema_has_the_same_neutral_scope(self):
        schema = report_schema(self.catalog)
        self.assertEqual(schema['$defs']['service_id']['enum'], ['alpha', 'beta'])
        self.assertEqual(schema['$defs']['observation_id']['enum'], ['obs-local'])
        self.assertEqual(schema, report_schema({'services': ['beta', 'alpha'],
            'observations': [{'id': 'obs-local', 'model_score': 'DO_NOT_SEND'}]}))
        empty = report_schema({'services': [], 'observations': []})
        self.assertEqual(empty['properties']['hypotheses']['maxItems'], 0)

    def test_action_proposals_are_scoped_conditional_and_not_assignments(self):
        proposal = {"service":"alpha", "purpose":"preventive", "title":"После проверки ограничить нагрузку",
            "rationale":"Наблюдается изменение", "verification_plan":"Сравнить ошибки при той же нагрузке",
            "evidence_ids":["obs-local"]}
        report = self.report | {"action_proposals":[proposal]}
        self.assertEqual(validate_report(report,self.catalog),report)
        for extra in ({"owner":"invented"},{"status":"verified"},{"due_unix":123},{"executed":True}):
            with self.subTest(extra=extra), self.assertRaises(AssistantContractError):
                validate_report(report | {"action_proposals":[proposal | extra]},self.catalog)
        for replacement in ({"service":"outside"},{"purpose":"shell"},{"evidence_ids":[]},
                            {"evidence_ids":["outside"]},{"verification_plan":""}):
            with self.subTest(replacement=replacement), self.assertRaises(AssistantContractError):
                validate_report(report | {"action_proposals":[proposal | replacement]},self.catalog)
        self.assertEqual(validate_report(self.report | {"action_proposals":[]},self.catalog)["action_proposals"],[])


if __name__ == "__main__":
    unittest.main()
