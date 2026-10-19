"""Registered R3-J wiring checks; no model fit, LLM call or accuracy estimate."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT.parent / 'rca-workbench'
sys.path[:0] = [str(PRODUCT / 'ml'), str(PRODUCT / 'cmd/thesis_demo')]
from http_observations import CHANNELS, VERSION, collect_http, decode_matrix, summarize
from live_sources import LiveProfile
from server import DiagnosticApplication
from workspace_store import WorkspaceStore

PRIVATE = ROOT / 'artifacts/r3-http-observations-v2'
OUT = ROOT / 'docs/product-research/r3-http-observations-summary.json'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def compose(*args):
    subprocess.run(['docker', '--host', 'unix:///Users/maxryabets/.colima/default/docker.sock',
        'compose', '-f', str(ROOT / 'deploy/acceptance/compose.yml'), *args], check=True)


def wait_until(deadline):
    while time.time() < deadline:
        time.sleep(min(1, deadline-time.time()))


def recorded():
    checks = []
    for name, services in [('r3-live-red-v1', ('gateway', 'orders', 'payment')),
                           ('r3-metric-reserve-v1', ('api-gateway', 'customers-service', 'vets-service', 'visits-service'))]:
        base = ROOT / 'artifacts' / name
        window = json.loads((base / 'healthy-window.json').read_text())
        raw = json.loads((base / 'healthy-red.json').read_text())
        scope = {'services':services, 'aliases':{}, 'ignored':(), 'label':'service'}
        matrices = {c: decode_matrix({'status':'success', 'data':{'resultType':'matrix', 'result':raw['up' if c == 'presence' else c]}},
            scope, c, window['start_unix'], window['end_unix']) for c in (*CHANNELS, 'presence')}
        result = summarize(matrices, services, window['start_unix'], window['end_unix'], 2)
        assert all(row['state'] == 'OBSERVED' for row in result['services'].values()), result
        checks.append({'source':name, 'services':list(services), 'status':result['status'],
                       'raw_sha256':hashlib.sha256((base / 'healthy-red.json').read_bytes()).hexdigest()})
    return checks


def capture(profile, name, *, clean_lookback):
    start = int(time.time()) + (35 if clean_lookback else 1)
    end = start+10
    print('capture', name, start, end, flush=True)
    wait_until(end+3)
    result = collect_http(profile, start, end)
    save(PRIVATE / (name+'.json'), result)
    return result


def run():
    PRIVATE.mkdir(exist_ok=False)
    # A product installation must not accidentally load research replay files.
    sys.path.insert(0, str(PRODUCT / 'deploy/product'))
    from export_source import export
    runtime_root = PRIVATE / 'source'
    export_receipt = export(PRODUCT, runtime_root)
    config_raw = json.loads((ROOT / 'deploy/acceptance/red-queries.json').read_text())
    config = {'version':VERSION, 'lookback_seconds':30,
        'source_presence_query':'min by(service) (up{job="business-http-red"})', 'queries':config_raw['channels']}
    raw = json.loads((ROOT / 'artifacts/r3-live-red-v1/profile.json').read_text())
    raw['http_observations'] = config
    baseline_relative = 'deploy/profiles/artifacts/http-observations-go'
    baseline_dir = runtime_root / baseline_relative
    baseline_dir.mkdir(parents=True)
    for name in ('healthy-baseline.json', 'legacy-metric-baseline.json', 'provenance.json'):
        original = ROOT / raw['artifact_dir'] / name
        if original.is_file():
            shutil.copy2(original, baseline_dir / name)
    raw['artifact_dir'] = baseline_relative
    profile_path = runtime_root / 'deploy/profiles' / 'system.json'
    save(profile_path, raw)
    profile = LiveProfile.load(profile_path, runtime_root)
    receipt = {'role':'PRODUCT_WIRING_NOT_ACCURACY_EVALUATION', 'model_fits':0, 'provider_calls':0,
        'source':'real Prometheus / Go HTTP instrumentation', 'recorded_sources':recorded(),
        'source_export':{key:value for key,value in export_receipt.items() if key != 'output'},
        'protocol_sha256':hashlib.sha256((ROOT / 'docs/R3_HTTP_OBSERVATIONS_PROTOCOL.md').read_bytes()).hexdigest()}
    try:
        # Preserve and reuse the already captured active interval from v1.
        active = json.loads((ROOT / 'artifacts/r3-http-observations-v1/active.json').read_text())
        assert all(row['state'] == 'OBSERVED' for row in active['services'].values()), active
        app = DiagnosticApplication(runtime_root, profile_path.parent, workspace=WorkspaceStore(PRIVATE / 'workspace'))
        start, end = active['start_unix'], active['end_unix']
        enriched = app.analyze_live(profile.id, start, end, force_refresh=True)
        save(PRIVATE / 'api-analysis.json', enriched)
        snapshot = app.workspace.get_snapshot(enriched['result_id'])
        save(PRIVATE / 'api-snapshot.json', snapshot)
        app.profiles[profile.id] = replace(profile, http_observations_config=None)
        original = app.analyze_live(profile.id, start, end, force_refresh=True)
        for key in ('input_sha256', 'feature_schema_sha256', 'candidates'):
            assert enriched[key] == original[key], key
        assert len([f for f in snapshot['catalog']['observations'] if f['values'].get('family', '').startswith('http_')]) == 9
        receipt['api'] = {'identical_core_input_and_ranking':True, 'snapshot_saved':True,
            'analysis_id':enriched['result_id'], 'start_unix':start, 'end_unix':end,
            'source_status':enriched['source_status']['http_observations'],
            'baseline_warning':enriched['source_status'].get('baseline_binding')}
        compose('stop', 'workload')
        idle = capture(profile, 'idle', clean_lookback=True)
        assert all(row['state'] == 'NO_ACTIVITY' for row in idle['services'].values()), idle
        assert all(row['metrics']['latency_p95']['median'] is None for row in idle['services'].values())
        compose('start', 'workload')
        compose('stop', 'payment')
        outage = capture(profile, 'outage', clean_lookback=True)
        assert outage['services']['payment']['state'] == 'UNAVAILABLE', outage
        assert outage['services']['payment']['metrics']['request_rate']['median'] is None
        receipt['phases'] = {name:{'status':result['status'], 'start_unix':result['start_unix'], 'end_unix':result['end_unix'],
            'services':{s:r['state'] for s,r in result['services'].items()}} for name,result in [('active',active),('idle',idle),('outage',outage)]}
        receipt['accepted'] = True
        save(OUT, receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
    finally:
        compose('start', 'payment', 'workload')


if __name__ == '__main__':
    run()
