"""Bounded real-Loki engineering pilot; actual HTTP failures, not benchmark truth.

Application logs, public symptom summaries and controller truth have separate
outputs. No model, provider, Docker socket or corporate data are used.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PRODUCT = Path(os.environ.get('RCA_PRODUCT_ROOT', Path(__file__).resolve().parents[2]/'rca-workbench'))
sys.path.insert(0, str(PRODUCT/'tools'))
from loki_context_probe import LokiContextSource


def run(base, output):
    if output.exists():
        raise ValueError('new receipt directory required')
    output.mkdir(parents=True)
    with urlopen(base+'/ready', timeout=3) as response:
        assert response.status == 200
    config = {'source_id': 'local-pilot', 'url': base, 'service_label': 'service_name',
              'services': {'checkout': 'checkout'}, 'labels': {'environment': 'rca-loki-pilot'}}
    source = LokiContextSource(config)
    ledger, cases, truth = [], [], []

    def emit(service, fields):
        stamp = str(time.time_ns())
        line = json.dumps(fields, sort_keys=True)
        body = {'streams': [{'stream': {'service_name': service, 'environment': 'rca-loki-pilot'},
                             'values': [[stamp, line]]}]}
        with urlopen(Request(base+'/loki/api/v1/push', data=json.dumps(body).encode(),
                             headers={'Content-Type': 'application/json'}), timeout=5) as response:
            assert response.status == 204
        ledger.append({'service': service, 'timestamp_ns': stamp, 'line': line,
                       'sha256': hashlib.sha256(line.encode()).hexdigest()})

    class Dependency(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            if self.path == '/denied':
                self.send_response(403); self.end_headers()
            else:
                time.sleep(0.12 if self.path == '/slow-a' else 0.2)
                try:
                    self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
                except (BrokenPipeError, ConnectionResetError): pass

    dependency = ThreadingHTTPServer(('127.0.0.1', 0), Dependency)
    dep_thread = threading.Thread(target=dependency.serve_forever, daemon=True); dep_thread.start()
    target = {'url': '', 'header': ''}

    class Application(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            try:
                with urlopen(Request(target['url'], headers={'Authorization': target['header']}), timeout=0.04):
                    pass
            except (OSError, HTTPError, URLError) as error:
                actual = error.reason if isinstance(error, URLError) and isinstance(error.reason, BaseException) else error
                fields = {'event.name': 'error', 'error.type': type(actual).__name__}
                if isinstance(error, HTTPError):
                    fields['http.response.status_code'] = error.code
                    error.close()
                emit('checkout', fields)
                self.send_response(503); self.end_headers(); return
            self.send_response(200); self.end_headers()

    app = ThreadingHTTPServer(('127.0.0.1', 0), Application)
    app_thread = threading.Thread(target=app.serve_forever, daemon=True); app_thread.start()
    try:
        for index, mechanism in enumerate(['access', 'access', 'connection', 'connection', 'timeout', 'timeout']):
            if mechanism == 'access':
                target.update(url=f'http://127.0.0.1:{dependency.server_port}/denied',
                              header='invalid' if index == 0 else '')
            elif mechanism == 'connection':
                with socket.socket() as unused:
                    unused.bind(('127.0.0.1', 0)); port = unused.getsockname()[1]
                target.update(url=f'http://127.0.0.1:{port}/', header='')
            else:
                target.update(url=f'http://127.0.0.1:{dependency.server_port}/slow-{chr(97+index%2)}', header='')
            start = time.time()
            statuses, durations = [], []
            expected = len(ledger)
            for _ in range(3):
                before = time.monotonic()
                try:
                    with urlopen(f'http://127.0.0.1:{app.server_port}/checkout', timeout=5) as response:
                        statuses.append(response.status)
                except HTTPError as error:
                    statuses.append(error.code);error.close()
                durations.append(time.monotonic()-before)
            end = time.time()
            result = source.collect('checkout', start, end)
            actual_rows = ledger[expected:]
            checks = {'three_real_503': statuses == [503]*3,
                      'actual_log_hashes_match': {r['source_line_sha256'] for r in result['records']} == {r['sha256'] for r in actual_rows},
                      'available': result['status'] == 'available',
                      'no_controller_fields': all(set(r['fields']) <= {'event.name','error.type','http.response.status_code'} for r in result['records'])}
            cases.append({'id': f'p{index+1:02d}', 'without_context': {'http_statuses': statuses,
                'durations_seconds': durations}, 'with_context': result, 'checks': checks})
            truth.append({'case_id': f'p{index+1:02d}', 'controlled_mechanism': mechanism})

        start = time.time()
        emit('unrelated', {'event.name':'deployment', 'service.version':'v2'})
        end = time.time()
        cases.append({'id':'p07','control':'unrelated_change', 'with_context': source.collect('checkout',start,end)})
        start = time.time(); threading.Event().wait(0.01); end = time.time()
        cases.append({'id':'p08','control':'no_record', 'with_context': source.collect('checkout',start,end)})
        original = cases[0]['with_context']
        cases.append({'id':'p09','control':'truncated', 'with_context': source.collect('checkout',original['start_unix'],original['end_unix'],limit=1)})
        offline = config | {'url':'http://127.0.0.1:1'}
        cases.append({'id':'p10','control':'source_down', 'with_context': LokiContextSource(offline).collect('checkout',start,end)})
        for name, value in [('cases-before-validation.json', cases), ('application-ledger.json', ledger),
                            ('controller-truth.json', truth)]:
            (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        assert len(cases) == 10
        for case in cases[:6]:
            assert all(case['checks'].values()), case['id']
        assert cases[6]['with_context']['records'] == []
        assert cases[7]['with_context']['status'] == 'available' and cases[7]['with_context']['records'] == []
        assert cases[8]['with_context']['status'] == 'truncated'
        assert cases[9]['with_context']['status'] == 'unavailable'

        # Explicit end-exclusive comparison against Loki, not an in-memory fake.
        stamp = ledger[0]['timestamp_ns']
        # Raw exact ns request is the authoritative API boundary check.
        from urllib.parse import urlencode
        query = urlencode({'query':'{environment="rca-loki-pilot",service_name="checkout"}',
                           'start':str(int(stamp)-1_000_000),'end':stamp,'limit':100})
        with urlopen(base+'/loki/api/v1/query_range?'+query,timeout=5) as response:
            exact = json.load(response)
        assert exact['data']['result'] == []
        receipt = {'kind':'REAL_LOKI_CONTROLLED_APPLICATION_PILOT', 'cases':cases,
            'case_count':10, 'provider_calls':0, 'true_root_cause_not_sent_to_loki':True,
            'exact_ns_end_exclusive_verified':True, 'local_only':True,
            'limits':'No accuracy, user time saving or production transfer claim'}
        for name, value in [('receipt.json',receipt),('application-ledger.json',ledger),('controller-truth.json',truth)]:
            (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'output':str(output),'cases':10,'status':'contract_checks_passed'}))
    finally:
        for name, value in [('cases-before-validation.json', cases), ('application-ledger.json', ledger),
                            ('controller-truth.json', truth)]:
            (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        app.shutdown(); app.server_close(); app_thread.join(2)
        dependency.shutdown(); dependency.server_close(); dep_thread.join(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:18310')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    run(args.url,args.output)
