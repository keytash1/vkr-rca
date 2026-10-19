"""R3-A controlled development pilot. No report edits, training or truth upload.

prepare: fresh real HTTP failures + synthetic resource series + frozen ranking.
run: at most one provider attempt per registered task; never retry started work.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = Path(os.environ.get('RCA_PRODUCT_ROOT', ROOT.parent / 'rca-workbench')).resolve()
sys.path[:0] = [str(PRODUCT / 'ml'), str(PRODUCT / 'cmd/thesis_demo')]
from assistant_context import assistant_context, compact_prompt_context
from assistant_contract import AssistantLimits, report_schema
from assistant_budget import reserve_input
from assistant_privacy import prepare_outbound_aggregates
from assistant_runner import DEFAULT_QUESTION, PROMPT_VERSION, INSTRUCTIONS
from assistant_supervisor import run_in_worker
from context_catalog import attach_context
from evidence_catalog import build_catalog
from profile_runtime import ProfileTransferRuntime
from rca_ml.m12_adapter import CANONICAL_UNITS, robust_baseline
from rca_ml.m13_features import fit_healthy_baseline
from runtime_assets import EXPECTED_SHA256
from trace_adapters import validate_canonical_spans

PINS = ('f81e6f2', 'aea24f5')  # Tested cache fix and its main merge, same source.
SERVICES = ('api', 'worker')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def product_head():
    return subprocess.check_output(['git', '-C', str(PRODUCT), 'rev-parse', 'HEAD'], text=True).strip()


def validate_capture(mechanism, requests, records):
    """An intended injection is not truth: check actual outcomes before inference."""
    if len(requests) != 3 or any(r['status'] != (200 if mechanism == 'healthy_unrelated_change' else 503)
                                 for r in requests):
        raise ValueError('CAPTURE_HTTP_OUTCOME_MISMATCH')
    fields = [r['fields'] for r in records]
    if mechanism == 'healthy_unrelated_change':
        valid = not fields
    elif mechanism in ('permission', 'unavailable_context'):
        valid = len(fields) == 3 and all(f.get('http.response.status_code') in (401, 403) for f in fields)
    elif mechanism == 'connection':
        valid = len(fields) == 3 and all(f.get('error.type') == 'ConnectionRefusedError' for f in fields)
    elif mechanism == 'timeout':
        valid = len(fields) == 3 and all(f.get('error.type') == 'TimeoutError' for f in fields)
    else:
        valid = False
    if not valid:
        raise ValueError('CAPTURE_MECHANISM_MISMATCH_NOT_VALID_FOR_COMPARISON')


def metrics(start, end):
    values = {'cpu': .25, 'memory': 67108864., 'network': 1024., 'traffic_rate': 1024.}
    return [{'timestamp': t, 'service': service, 'family': family,
             'value': values[family], 'unit': unit}
            for service in SERVICES for family, unit in CANONICAL_UNITS.items()
            for t in (start, (start + end) / 2, end)]


def span(service, trace, identifier, parent, start, duration, error, kind='SERVER'):
    return {'service': service, 'trace_id': trace, 'span_id': identifier,
            'parent_span_id': parent or '', 'peer_service': 'worker' if kind == 'CLIENT' else None,
            'span_kind': kind, 'start_time_us': int(start * 1e6),
            'duration_us': max(1, int(duration * 1e6)), 'error': error,
            'status_code': 'ERROR' if error else 'OK',
            **({'observed_edge': {'source': 'api', 'target': 'worker'}} if parent else {})}


def prepare(output, followup=False):
    assert product_head().startswith(PINS), 'product changed before registration'
    output.mkdir(parents=True, exist_ok=False)
    records, spans, statuses = [], [], []
    target = {'url': ''}

    class Dependency(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            if self.path.startswith('/status/'):
                self.send_response(int(self.path.rsplit('/', 1)[1])); self.end_headers()
                return
            if self.path.startswith('/delay/'):
                time.sleep(float(self.path.rsplit('/', 1)[1]))
            try:
                self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
            except (BrokenPipeError, ConnectionResetError): pass

    dependency = ThreadingHTTPServer(('127.0.0.1', 0), Dependency)
    thread_dep = threading.Thread(target=dependency.serve_forever, daemon=True)
    thread_dep.start()

    class Application(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            start, tick = time.time(), time.monotonic()
            error, fields, status = False, None, 200
            try:
                with urlopen(target['url'], timeout=.04) as response:
                    response.read(32)
            except (HTTPError, URLError, OSError) as exc:
                error, status = True, 503
                actual = exc.reason if isinstance(exc, URLError) and isinstance(exc.reason, BaseException) else exc
                fields = {'event.name': 'error', 'error.type': type(actual).__name__}
                if isinstance(exc, HTTPError):
                    fields['http.response.status_code'] = exc.code
                    exc.close()
            duration = time.monotonic() - tick
            trace = f'{len(statuses)+1:032x}'
            spans.extend([span('api', trace, '0000000000000001', None, start, duration, error),
                          span('api', trace, '0000000000000002', '0000000000000001', start, duration, error, kind='CLIENT')])
            if fields:
                line = json.dumps(fields, sort_keys=True)
                records.append({'source_timestamp_ns': str(time.time_ns()), 'fields': fields,
                                'source_line_sha256': hashlib.sha256(line.encode()).hexdigest()})
            statuses.append({'status': status, 'start_unix': start, 'duration_seconds': duration})
            self.send_response(status); self.end_headers()

    app = ThreadingHTTPServer(('127.0.0.1', 0), Application)
    thread_app = threading.Thread(target=app.serve_forever, daemon=True); thread_app.start()
    truth, cases, jobs = [], [], []
    try:
        # macOS may time out on a bound/non-listening socket. Close it before
        # use; validate_capture rejects port reuse or any unexpected outcome.
        with socket.socket() as refused, tempfile.TemporaryDirectory(prefix='rca-r3-baseline-') as tmp:
            refused.bind(('127.0.0.1', 0))
            refused_port = refused.getsockname()[1]
            refused.close()
            healthy_start, healthy_end = time.time() - 180, time.time() - 90
            healthy = {'segments': [{'start_unix': healthy_start, 'end_unix': healthy_end, 'requests_per_second': 1.}],
                       'metrics': metrics(healthy_start, healthy_end),
                       'traces': [span(s, f'{i+100:032x}', f'{i+1:016x}', None, healthy_start + 10, .002, False)
                                  for i, s in enumerate(SERVICES)]}
            baseline = fit_healthy_baseline(healthy, SERVICES)
            legacy = robust_baseline(healthy['metrics'])
            artifact = Path(tmp)
            save(artifact / 'healthy-baseline.json', baseline)
            save(artifact / 'legacy-metric-baseline.json', legacy)
            runtime = ProfileTransferRuntime(PRODUCT, artifact, SERVICES)
            save(output / 'healthy-fixture.json', healthy)
            base_url = f'http://127.0.0.1:{dependency.server_port}'
            targets = [base_url + '/status/401', base_url + '/status/403',
                       f'http://127.0.0.1:{refused_port}/a',
                       f'http://127.0.0.1:{refused_port}/b',
                       base_url + '/delay/.12', base_url + '/delay/.20',
                       base_url + '/healthy', base_url + '/status/403']
            mechanisms = ['permission', 'permission', 'connection', 'connection', 'timeout', 'timeout',
                          'healthy_unrelated_change', 'unavailable_context']
            selected = [(i, url, mechanism) for i, (url, mechanism) in enumerate(zip(targets, mechanisms, strict=True), 1)
                        if not followup or i in (2, 4, 6, 8)]
            for case_number, (index, url, mechanism) in enumerate(selected, 1):
                target['url'] = url
                before_records, before_spans, before_statuses = len(records), len(spans), len(statuses)
                start = time.time()
                for _ in range(3):
                    try:
                        with urlopen(f'http://127.0.0.1:{app.server_port}/', timeout=3) as response: response.read(32)
                    except HTTPError as exc: exc.close()
                end = time.time()
                identifier = f'r3f-{case_number:02d}' if followup else f'r3-{index:02d}'
                local = records[before_records:]
                save(output / 'local' / f'{identifier}-capture.json', {
                    'requests': statuses[before_statuses:], 'records': local,
                    'intended_mechanism': mechanism})
                validate_capture(mechanism, statuses[before_statuses:], local)
                window = {'candidate_services': list(SERVICES), 'start_unix': start, 'end_unix': end,
                          'requests_per_second': 1., 'metrics': metrics(start, end),
                          'traces': spans[before_spans:], 'traces_collected': True}
                validate_canonical_spans(window['traces'])
                ranked = runtime.rank_all(window)['frozen_m13']
                hint = [{'service': r['service'], 'rank': r['rank'], 'model_score': r['score']} for r in ranked]
                result = {'result_id': identifier, 'start_unix': start, 'end_unix': end,
                          'input_sha256': digest(window), 'baseline_sha256': digest(baseline),
                          'model_version': runtime.freeze['version'], 'feature_schema_sha256': digest(runtime.columns)}
                catalog = build_catalog(window, result, baseline, source_status={'traces': 'available'})
                rows = {'api': {'status': 'available', 'records': local},
                        'worker': {'status': 'available', 'records': []}}
                if index == 7:
                    rows['worker']['records'] = [{'source_timestamp_ns': str(time.time_ns()),
                        'fields': {'event.name': 'deployment'}, 'source_line_sha256': digest({'event.name': 'deployment'})}]
                if index == 8:
                    rows['api'] = {'status': 'unavailable', 'reason': 'SOURCE_PROBE_FAILED', 'records': []}
                config = {'source_id': 'fresh-application-session', 'services': dict(zip(SERVICES, SERVICES)),
                          'assistant_categories': True}
                with_context = attach_context(catalog, config, rows)
                projected = {}
                for arm, source in [('C0', catalog), ('C1', with_context)]:
                    clean, clean_hint, _ = prepare_outbound_aggregates(source, ranking=hint)
                    packet = {'catalog': clean, 'ranking': clean_hint}
                    path = output / 'inputs' / f'{identifier}-{arm}.json'
                    save(path, packet)
                    jobs.append({'case': identifier, 'arm': arm, 'input': str(path.relative_to(output)), 'sha256': digest(packet)})
                    projected[arm] = clean
                def shared(value):
                    return sorted([{'service': f['service'], 'kind': f['kind'], 'values': f['values']}
                                   for f in value['observations'] if f['kind'] != 'context'], key=digest)
                assert shared(projected['C0']) == shared(projected['C1'])
                body = json.dumps(projected['C1'])
                assert all(forbidden not in body for forbidden in ['ConnectionRefusedError', 'HTTPError', 'TimeoutError',
                            'source_line_sha256', '127.0.0.1', 'controlled_mechanism'])
                assert len(local) == (0 if index == 7 else 3)
                save(output / 'local' / f'{identifier}.json', {'window': window, 'rank': hint,
                     'application_requests': statuses[before_statuses:], 'source_rows': rows, 'catalog': with_context})
                truth.append({'case': identifier, 'mechanism': mechanism,
                              'hidden_controller_target': url, 'actual_error_fields': [r['fields'] for r in local]})
                cases.append({'case': identifier, 'group': 'new-single-session-controlled-development',
                              'role': 'USED_DEVELOPMENT', 'synthetic_resource_metrics': True,
                              'actual_http_requests': 3, 'model': 'frozen_m13', 'canonical_sha256': digest(window)})
            random.Random(20261019).shuffle(jobs)
            save(output / 'controller-truth.json', truth)
            save(output / 'data-ledger.json', {'old_m14': 'USED_TEST_DO_NOT_TRAIN', 'old_loki_pilot': 'USED_ENGINEERING', 'cases': cases})
            protocol = 'docs/R3_FOLLOWUP_PROTOCOL.md' if followup else 'docs/R3_PROTOCOL.md'
            registration = {'protocol_path': protocol, 'protocol_sha256': hashlib.sha256((ROOT / protocol).read_bytes()).hexdigest(),
                'product_commit': product_head(), 'prompt_version': PROMPT_VERSION, 'prompt_sha256': digest(INSTRUCTIONS),
                'model': 'gpt-6.1-sol', 'question': DEFAULT_QUESTION, 'max_generation_attempts': len(jobs),
                'limits': {'model_calls': 1, 'wall_seconds': 60, 'input_tokens': 12000, 'output_tokens': 3000},
                'runtime_asset_sha256': EXPECTED_SHA256, 'jobs': jobs}
            save(output / 'registration.json', registration)
            print(json.dumps({'prepared': len(cases), 'registered_jobs': len(jobs), 'output': str(output)}), flush=True)
    finally:
        app.shutdown(); app.server_close(); thread_app.join(2)
        dependency.shutdown(); dependency.server_close(); thread_dep.join(2)


def run(output, state_dir):
    assert not (output / 'STOPPED.json').exists(), 'stopped experiment must not be resumed'
    registration = json.loads((output / 'registration.json').read_text())
    assert product_head() == registration['product_commit'] and product_head().startswith(PINS)
    assert digest(INSTRUCTIONS) == registration['prompt_sha256']
    assert hashlib.sha256((ROOT / registration['protocol_path']).read_bytes()).hexdigest() == registration['protocol_sha256']
    assert len(registration['jobs']) == registration['max_generation_attempts'] <= 16
    preflight = []
    for job in registration['jobs']:
        packet = json.loads((output / job['input']).read_text())
        assert digest(packet) == job['sha256']
        context = assistant_context(packet['catalog'], ranking=packet['ranking'], summary_only=True)
        content = json.dumps({'question': registration['question'], 'observations': compact_prompt_context(context)},
                             ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        reserve, method = reserve_input({'instructions': INSTRUCTIONS, 'input': content, 'schema': report_schema(context)}, registration['model'])
        assert 'VERIFIED_LOCAL_ESTIMATE' in method and reserve <= registration['limits']['input_tokens'], (job['case'], reserve, method)
        preflight.append({'job': job['case'] + '-' + job['arm'], 'reserved_tokens': reserve, 'method': method})
    if not (output / 'preflight.json').exists(): save(output / 'preflight.json', preflight)
    started = set()
    ledger_path = output / 'attempts.jsonl'
    if ledger_path.exists():
        started = {json.loads(line)['job'] for line in ledger_path.read_text().splitlines()}
    for number, job in enumerate(registration['jobs'], 1):
        key = job['case'] + '-' + job['arm']
        if key in started: continue
        packet = json.loads((output / job['input']).read_text())
        assert digest(packet) == job['sha256']
        # Persist reservation BEFORE any possible transmission; crashes never repeat it.
        with ledger_path.open('a') as stream:
            stream.write(json.dumps({'job': key, 'started_at_unix': time.time(), 'attempt_reserved': 1}) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        outcome = run_in_worker(python_executable=sys.executable, state_dir=state_dir,
            model=registration['model'], question=registration['question'], limits=AssistantLimits(**registration['limits']),
            catalog=packet['catalog'], ranking=packet['ranking'], allow_external=True, workflow='snapshot')
        save(output / 'responses' / (key + '.json'), outcome)
        # Neutral sequence file has no arm/case. Truth deliberately not read by runner.
        save(output / 'review-masked' / f'answer-{number:02d}.json',
             {'answer_id': f'answer-{number:02d}', 'status': outcome['status'], 'report': outcome.get('report')})
        print(json.dumps({'job': key, 'status': outcome['status'], 'reason': outcome.get('stop_reason'),
                          'usage': outcome.get('usage'), 'seconds': outcome.get('elapsed_seconds')}), flush=True)
        if outcome['status'] != 'completed':
            print('STOP: incomplete outcome; no retries or alternate provider', flush=True)
            break


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--followup', action='store_true')
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.output, args.followup)
    else:
        if args.state_dir is None: parser.error('--state-dir required')
        run(args.output, args.state_dir)
