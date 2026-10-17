import copy
import unittest

from assistant_contract import AssistantContractError, report_schema, validate_report


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


if __name__ == "__main__":
    unittest.main()
