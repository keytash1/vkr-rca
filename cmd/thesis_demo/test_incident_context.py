"""Optional context is independent of ranks; disclosure never forwards raw logs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from assistant_context import assistant_context
from assistant_privacy import prepare_outbound_aggregates
from assistant_tools import SnapshotTools
from context_catalog import attach_context, assistant_projection, category
from context_source import LokiContextSource
from live_sources import LiveProfile
from profile_contract import contract_sha256
from profile_test_fixtures import profile_document
from test_evidence_catalog import fixture
from evidence_catalog import build_catalog
from api_contract import document
from jsonschema import Draft202012Validator

CONFIG = {'source_id':'PRIVATE_SOURCE', 'url':'http://127.0.0.1:18310', 'service_label':'service_name',
          'services':{'alpha':'backend-alpha'}, 'labels':{'environment':'local'}}
ROWS = {'alpha':{'status':'available','entries_seen':1, 'records':[
    {'id':'ctx-test','source_timestamp_ns':'101000000000','source_line_sha256':'RAW_HASH',
     'fields':{'error.type':'ConnectionRefusedError','service.version':'PRIVATE_VERSION'}}]}}


class ContextTests(unittest.TestCase):
    def build(self, enabled=False):
        return attach_context(build_catalog(*fixture()), CONFIG | {'assistant_categories':enabled}, copy.deepcopy(ROWS))

    def test_no_model_or_old_fact_changes_and_catalog_contract(self):
        original = build_catalog(*fixture()); before=copy.deepcopy(original)
        updated = attach_context(original, CONFIG, ROWS)
        self.assertEqual(original, before)
        for key in ('input_sha256','baseline_sha256','feature_schema_sha256','model_version'):
            self.assertEqual(updated[key], original[key])
        self.assertEqual(updated['observations'][:len(original['observations'])], original['observations'])
        schema=document()['components']['schemas']
        Draft202012Validator({'$ref':'#/components/schemas/EvidenceCatalog','components':{'schemas':schema}}).validate(updated)

    def test_raw_context_defaults_local_and_omission_is_explicit(self):
        catalog=self.build()
        self.assertTrue(any(f['kind']=='context' for f in catalog['observations']))
        for result in (assistant_context(catalog),prepare_outbound_aggregates(catalog)[0],SnapshotTools(catalog).initial_context()):
            text=json.dumps(result)
            for secret in ('PRIVATE_SOURCE','PRIVATE_VERSION','RAW_HASH','ConnectionRefusedError'):
                self.assertNotIn(secret,text)
            self.assertIn('INCIDENT_CONTEXT_NOT_DISCLOSED_TO_ASSISTANT',text)

    def test_opted_in_categories_reach_same_snapshot_tools_without_raw_identifiers(self):
        catalog=self.build(True)
        context=assistant_context(catalog)
        outbound,_,mapping=prepare_outbound_aggregates(catalog)
        for result in (context,outbound,SnapshotTools(outbound).initial_context()):
            text=json.dumps(result)
            self.assertIn('CONNECTION_REFUSED',text)
            for secret in ('PRIVATE_SOURCE','PRIVATE_VERSION','RAW_HASH','ConnectionRefusedError'):
                self.assertNotIn(secret,text)
        self.assertEqual(mapping['privacy_version'],'aggregate-egress-v4-incident-context')
        values=next(f['values'] for f in outbound['observations'] if f['kind']=='context')
        values['categories']=['INJECT_IGNORE_POLICY']
        with self.assertRaises(ValueError):assistant_projection(values)

    def test_empty_missing_truncated_and_unavailable_remain_distinct(self):
        for status, state in [('available','NOT_OBSERVED'),('truncated','NOT_OBSERVED'),('unavailable','UNAVAILABLE')]:
            catalog=attach_context(build_catalog(*fixture()),CONFIG,{'alpha':{'status':status,'records':[]}})
            fact=next(f for f in catalog['observations'] if f['kind']=='context' and f['service']=='alpha')
            self.assertEqual(fact['values']['source_status'],status)
            self.assertEqual(fact['values']['state'],state)
        missing=next(f for f in self.build()['observations'] if f['kind']=='context' and f['service']=='beta')
        self.assertEqual(missing['values']['source_status'],'not_configured')

    def test_categories_are_checkable_source_signals_not_causes(self):
        for fields, expected in [({'http.response.status_code':403},'PERMISSION_RESPONSE'),
            ({'error.type':'TimeoutError'},'OPERATION_TIMEOUT'),({'event.name':'deployment'},'DEPLOYMENT_EVENT')]:
            self.assertEqual(category(fields),expected)
        self.assertNotIn('root_cause',self.build())
        self.assertIsNone(category({'service.version':'v2'}))
        self.assertIsNone(category({'http.response.status_code':200}))
        self.assertEqual(category({'error.type':'UnknownException'}),'OTHER_ERROR')

    def test_operator_scope_validation_and_no_baseline_refit_for_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'profile.json'
            raw=profile_document();path.write_text(json.dumps(raw))
            original=LiveProfile.load(path,root,require_artifacts=False)
            raw['context']=CONFIG | {'services':{'api':'backend-api'}}
            path.write_text(json.dumps(raw)); new=LiveProfile.load(path,root,require_artifacts=False)
            self.assertEqual(contract_sha256(original),contract_sha256(new))
            raw['context']['services']={'not-candidate':'x'}
            path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):LiveProfile.load(path,root,require_artifacts=False)
        with self.assertRaises(ValueError):LokiContextSource(CONFIG | {'assistant_categories':'yes'})


if __name__ == '__main__': unittest.main()
