"""One real Docker/Loki pilot. Controller checks are never sent to Loki or ML."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

PRODUCT = Path(__file__).resolve().parents[2]/'rca-workbench'
sys.path[:0] = [str(PRODUCT/'tools'), str(PRODUCT/'cmd/thesis_demo'), str(PRODUCT/'ml')]
from docker_context_collector import Collector, docker
from context_source import LokiContextSource
from context_catalog import attach_context, assistant_projection
from evidence_catalog import build_catalog
from test_evidence_catalog import fixture


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    host = 'unix:///Users/maxryabets/.colima/default/docker.sock'
    project = 'rcahistory-' + uuid.uuid4().hex[:10]
    context = {'source_id':'runtime-local', 'url':'http://127.0.0.1:18310', 'service_label':'service_name',
               'services':{'alpha':'app'}, 'labels':{'environment':project},
               'lookback_seconds':60, 'assistant_categories':True}
    config = {'docker_host':host, 'project':project, 'context':context}
    collector = Collector(config,output/'outbox.sqlite')
    ids = []
    def collect():
        time.sleep(1.1)
        collector.poll()
        while collector.flush(): pass
    def launch(image, memory, *command):
        result = docker(host,'run','-d','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--pids-limit','16','--cpus','0.25','--memory',memory,'--memory-swap',memory,'--tmpfs','/tmp:rw,size=1m',
            '--label','com.docker.compose.project='+project,'--label','com.docker.compose.service=app',image,*command).strip()
        ids.append(result)
        collect()
        return result
    try:
        left = time.time()
        program = "import os,time; exec(\"while not os.path.exists('/tmp/go'): time.sleep(.05)\"); a=bytearray(128*1024*1024); time.sleep(30)"
        one = launch('python:3.12-slim','48m','python','-c',program)
        docker(host,'exec',one,'touch','/tmp/go')
        docker(host,'wait',one)
        oom_state = json.loads(docker(host,'inspect','--format','{{json .State}}',one))
        collect()
        assert oom_state['OOMKilled'] is True and oom_state['ExitCode'] == 137
        oom_end = time.time()
        docker(host,'start',one); collect()
        kill_start = time.time()
        docker(host,'kill','--signal','KILL',one)
        ordinary_state = json.loads(docker(host,'inspect','--format','{{json .State}}',one))
        collect()
        assert ordinary_state['OOMKilled'] is False and ordinary_state['ExitCode'] == 137
        kill_end = time.time()
        docker(host,'update','--memory','64m','--memory-swap','64m',one)
        docker(host,'start',one); collect()
        docker(host,'stop','--time','1',one); collect()
        two = launch('alpine:3.23','80m','sleep','120')
        incident_start = time.time()
        time.sleep(.1)
        end = time.time()
        # Reopen outbox; history is persisted in Loki and not reconstructed from
        # the now-recovered replacement container's current inspection.
        delivered = collector.db.execute('SELECT count(*) FROM outbox WHERE delivered=1').fetchone()[0]
        collector.db.close(); collector = Collector(config,output/'outbox.sqlite')
        replay_count = collector.poll()
        while collector.flush(): pass
        source = LokiContextSource(context)
        result = source.collect('alpha',incident_start,end)
        assert result['status']=='available',result
        records = result['records']; fields = [r['fields'] for r in records]
        assert all(r['period']=='BEFORE_INCIDENT' for r in records)
        assert any(f['event.name']=='oom' for f in fields)
        assert any(f['event.name']=='configuration_change' for f in fields)
        assert any(f['event.name']=='deployment' and f['container.id']==two for f in fields)
        assert {f['container.id'] for f in fields}==set(ids)
        ordinary = [f for r,f in zip(records,fields) if kill_start*1e9 <= int(r['source_timestamp_ns']) < kill_end*1e9]
        assert any(f.get('container.exit_code')==137 for f in ordinary)
        assert not any(f['event.name']=='oom' for f in ordinary)
        assert not LokiContextSource(context | {'lookback_seconds':0}).collect('alpha',incident_start,end)['records']
        catalog = build_catalog(*fixture()); original = json.dumps(catalog,sort_keys=True)
        updated = attach_context(catalog, context, {'alpha':result})
        assert json.dumps(catalog,sort_keys=True)==original
        assert updated['input_sha256']==catalog['input_sha256']
        fact = next(f for f in updated['observations'] if f['kind']=='context' and f['service']=='alpha')
        projection = assistant_projection(fact['values'])
        assert all(i not in json.dumps(projection) for i in ids)
        assert projection['preceding_record_count']==len(records)
        receipt = {'kind':'REAL_DOCKER_LOKI_HISTORY_PILOT', 'context':result,
            'control_checks':{'oom_state':{'OOMKilled':oom_state['OOMKilled'],'exit':oom_state['ExitCode']},
                'ordinary_kill_state':{'OOMKilled':ordinary_state['OOMKilled'],'exit':ordinary_state['ExitCode']},
                'persisted_delivered_records':delivered,'replay_new_records':replay_count,
                'actual_replacement_image_and_memory_change':True,'history_read_after_recovery':True,
                'source_fields_do_not_include_controller_truth':True,'ml_input_unchanged':True},
            'assistant_projection':projection,'provider_calls':0,
            'limits':'Engineering pilot, not ranking accuracy, user study or universal runtime support'}
        (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'status':'passed','records':len(records),'output':str(output)}))
    finally:
        collector.db.close()
        for instance in ids:
            # Exact IDs created by this script only; no volumes are created.
            subprocess.run(['docker','--host',host,'rm','-f',instance],capture_output=True,timeout=15)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
