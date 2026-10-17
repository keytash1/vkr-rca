import copy
import json
import unittest

from assistant_context import assistant_context, compact_prompt_context
from assistant_privacy import PrivacyError, prepare_outbound_aggregates

from evidence_catalog import build_catalog
from test_evidence_catalog import fixture


class PrivacyTests(unittest.TestCase):
    def test_descriptive_timings_preserved_and_arbitrary_semantics_rejected(self):
        from trace_evidence import summarize_timings
        source = copy.deepcopy(self.catalog)
        timing = summarize_timings([], source['services'], 0, 1)
        original = next(f for f in source['observations'] if f['kind'] == 'traces')
        original['values']['timing'] = timing[original['service']]
        projected, _, _ = prepare_outbound_aggregates(source)
        actual = next(f for f in projected['observations'] if f['kind'] == 'traces')
        self.assertEqual(actual['values']['timing'], original['values']['timing'])
        original['values']['timing']['meaning'] = 'SECRET_NEW_STRING'
        with self.assertRaises(PrivacyError):
            prepare_outbound_aggregates(source)

    def setUp(self):
        # Self-contained deliberately synthetic values. Fresh product checkouts
        # must not need the private/research acceptance corpus for policy tests.
        self.catalog = build_catalog(*fixture())

    def test_only_approved_aggregate_fields_leave_with_no_original_identity(self):
        self.catalog['token'] = 'SECRET_TOKEN'
        self.catalog['limitations'].append('SECRET_TEXT')
        self.catalog['source_quality']['traces_url'] = 'SECRET_URL'
        for fact in self.catalog['observations']:
            fact['tags'] = {'token': 'SECRET_TOKEN'}
            fact['source_links'] = [{'url': 'SECRET_URL'}]
        clean, hint, mapping = prepare_outbound_aggregates(self.catalog)
        wire = json.dumps(clean)
        self.assertNotIn('SECRET', wire)
        self.assertIsNone(hint)
        for original in self.catalog['services']:
            self.assertNotIn(original, wire)
        for original in mapping['observations']:
            self.assertNotIn(original, wire)
        self.assertEqual(len(clean['observations']), len(self.catalog['observations']))
        self.assertEqual(len(clean['services']), len(self.catalog['services']))
        self.assertEqual(sorted(mapping['services'].values()), clean['services'])
        self.assertNotIn('trace_id', wire)
        self.assertNotIn('span_id', wire)
        self.assertNotIn('http', wire)

    def test_numbers_coverage_and_edges_are_preserved_not_reinvented(self):
        clean, _, mapping = prepare_outbound_aggregates(self.catalog)
        by_id = {fact['id']: fact for fact in clean['observations']}
        for fact in self.catalog['observations']:
            projected = by_id[mapping['observations'][fact['id']]]
            self.assertEqual(projected['service'], mapping['services'][fact['service']])
            if fact['kind'] == 'metric':
                for field in ('min', 'median', 'max', 'samples', 'returned_point_coverage', 'baseline_comparison'):
                    self.assertEqual(projected['values'][field], fact['values'][field])
            if fact['kind'] == 'dependencies':
                for original, renamed in zip(fact['values']['edges'], projected['values']['edges']):
                    self.assertEqual(original['observed_edges'], renamed['observed_edges'])
                    self.assertEqual(mapping['services'][original['source']], renamed['source'])

    def test_rank_hint_is_explicit_and_identity_mapping_is_independent(self):
        services = self.catalog['services']
        hint = [{'service': service, 'rank': i, 'model_score': float(-i)}
                for i, service in enumerate(reversed(services), 1)]
        neutral, _, mapping = prepare_outbound_aggregates(self.catalog)
        with_hint, projected_hint, mapping2 = prepare_outbound_aggregates(self.catalog, ranking=hint)
        self.assertEqual(neutral, with_hint)
        self.assertEqual(mapping, mapping2)
        self.assertEqual(projected_hint[0]['service'], mapping['services'][hint[0]['service']])

    def test_arbitrary_string_in_approved_slot_and_nonfinite_value_are_rejected(self):
        for field, value in (('unit', 'SECRET_UNIT'), ('median', 'SECRET_VALUE'), ('max', float('nan'))):
            source = copy.deepcopy(self.catalog)
            fact = next(f for f in source['observations'] if f['kind'] == 'metric')
            fact['values'][field] = value
            with self.subTest(field=field), self.assertRaises(PrivacyError):
                prepare_outbound_aggregates(source)

    def test_factoring_is_lossless_and_smaller(self):
        clean, _, _ = prepare_outbound_aggregates(self.catalog)
        source = assistant_context(clean, summary_only=True)
        packed = compact_prompt_context(source)
        restored = copy.deepcopy(packed)
        contexts = restored.pop('baseline_contexts')
        restored.pop('transport_encoding')
        baseline_fields = restored.pop('baseline_value_fields', None)
        facts = []
        for table in restored.pop('observation_tables'):
            for row in table['rows']:
                fact = dict(zip(table['fact_fields'], row[:-1]))
                fact.update(kind=table['kind'], values=dict(zip(table['value_fields'], row[-1])))
                if baseline_fields and fact['values'].get('baseline_comparison'):
                    fact['values']['baseline_comparison'] = dict(zip(baseline_fields, fact['values']['baseline_comparison']))
                facts.append(fact)
        restored['observations'] = sorted(facts, key=lambda f:(f['service'], f['kind'], f['id']))
        for fact in restored['observations']:
            fact.setdefault('start_unix', restored['start_unix'])
            fact.setdefault('end_unix', restored['end_unix'])
            baseline = fact['values'].get('baseline_comparison')
            if baseline:
                baseline.update(contexts[baseline.pop('context_ref')])
        self.assertEqual(restored, source)
        self.assertLess(len(json.dumps(packed)), len(json.dumps(source)))


if __name__ == '__main__':
    unittest.main()
