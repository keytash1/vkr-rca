"""Product HTTP + real Loki; metrics/traces are explicitly synthetic fixtures."""
import argparse
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.request import Request, urlopen

PRODUCT=Path(os.environ.get('RCA_PRODUCT_ROOT', Path(__file__).resolve().parents[2]/'rca-workbench'))
sys.path[:0]=[str(PRODUCT/'ml'),str(PRODUCT/'cmd/thesis_demo')]
from profile_setup import prepare
from profile_test_fixtures import profile_document
from rca_ml.m12_adapter import CANONICAL_UNITS
from runtime_assets import EXPECTED_SHA256
from server import DiagnosticApplication, make_handler
from telemetry_test_fixtures import FakeTelemetry
from workspace_store import WorkspaceStore
from assistant_privacy import prepare_outbound_aggregates
from assistant_tools import SnapshotTools
from api_contract import document
from jsonschema import Draft202012Validator


def run(receipt, output, serve):
    if output.exists():raise ValueError('new receipt directory required')
    output.mkdir(parents=True)
    cases=json.loads(receipt.read_text())['cases']
    left=math.floor(cases[0]['with_context']['start_unix'])
    right=math.ceil(cases[5]['with_context']['end_unix'])
    source=ThreadingHTTPServer(('127.0.0.1',0),FakeTelemetry)
    source_thread=threading.Thread(target=source.serve_forever,daemon=True);source_thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='rca-loki-product-') as tmp:
            root=Path(tmp)
            for name in EXPECTED_SHA256:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((PRODUCT/name).read_bytes())
            raw=profile_document();raw['candidate_services']=['frontend','worker']
            raw['title']='Учебный сервис · настоящий Loki'
            raw['metrics']['url']=f'http://127.0.0.1:{source.server_port}'
            raw['traces']={'url':raw['metrics']['url'],'query_services':['frontend']}
            raw['workload']={'fixed_requests_per_second':4}
            path=root/'profiles/synthetic.json';path.parent.mkdir();path.write_text(json.dumps(raw))
            healthy_left,healthy_right=left-200,left-100
            healthy={'requests_per_second':4,'metrics':[
                {'timestamp':t,'service':s,'family':f,'value':1.,'unit':u}
                for s in raw['candidate_services'] for f,u in CANONICAL_UNITS.items()
                for t in range(healthy_left,healthy_right+1)],'traces':[
                {'service':s,'trace_id':'healthy','span_id':s,'parent_span_id':None,'peer_service':None,
                 'span_kind':'SERVER','start_time_us':(healthy_left+10)*1000000,
                 'duration_us':10000,'error':False,'status_code':'OK'} for s in raw['candidate_services']]}
            status={'traces':'available','metric_families_by_service':{s:list(CANONICAL_UNITS) for s in raw['candidate_services']}}
            with patch('profile_setup.collect',return_value=(healthy,status)):
                prepare(root,path,healthy_left,healthy_right)
            without=DiagnosticApplication(root,path.parent).analyze_live('synthetic',left,right)
            raw['context']={'source_id':'loki-local','url':'http://127.0.0.1:18310','service_label':'service_name',
                'services':{'frontend':'checkout'},'labels':{'environment':'rca-loki-pilot'},'assistant_categories':True}
            path.write_text(json.dumps(raw))
            store=WorkspaceStore(root/'workspace')
            app=DiagnosticApplication(root,path.parent,workspace=store)
            http=ThreadingHTTPServer(('127.0.0.1',serve or 0),make_handler(app))
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{http.server_port}'
            payload={'profile_id':'synthetic','start_unix':left,'end_unix':right,'force_refresh':True}
            try:
                with urlopen(Request(base+'/api/analyze',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}),timeout=25) as response:
                    result=json.load(response)
                with urlopen(base+f'/api/v2/analyses/{result["result_id"]}/evidence') as response:
                    catalog=json.load(response)
                assert result['candidates']==without['candidates'] and result['input_sha256']==without['input_sha256']
                facts=[f for f in catalog['observations'] if f['kind']=='context']
                actual=next(f for f in facts if f['service']=='frontend')
                assert actual['values']['record_count']>=18 and actual['values']['source_status']=='available'
                assert store.get_snapshot(result['result_id'])['catalog']==catalog
                outbound,_,_=prepare_outbound_aggregates(catalog)
                overview=SnapshotTools(outbound).initial_context()
                assert 'PERMISSION_RESPONSE' in json.dumps(overview)
                assert 'source_line_sha256' not in json.dumps(outbound)
                assert 'ConnectionRefusedError' not in json.dumps(outbound)
                schemas=document()['components']['schemas']
                for value,name in [(result,'AnalysisResult'),(catalog,'EvidenceCatalog')]:
                    Draft202012Validator({'$ref':f'#/components/schemas/{name}','components':{'schemas':schemas}}).validate(value)
                for name,value in [('analysis.json',result),('catalog.json',catalog),('assistant-category-projection.json',outbound),('request.json',payload)]:
                    (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({'status':'passed','url':base,'start_unix':left,'end_unix':right,
                    'model_unchanged':True,'saved_context':True,'provider_calls':0}),flush=True)
                if serve:
                    threading.Event().wait()  # Explicitly stopped after browser/source-down check.
            finally:
                http.shutdown();http.server_close();thread.join(2)
    finally:
        source.shutdown();source.server_close();source_thread.join(2)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--serve',type=int)
    args=parser.parse_args();run(args.receipt,args.output,args.serve)
