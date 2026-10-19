"""Small, pre-registered sensitivity study; no ranking-model training."""
from pathlib import Path
from collections import defaultdict
import copy
import hashlib
import json
import time
import signal

from rca_ml.m13_features import fit_healthy_baseline, build_candidate_rows
from rca_ml.m12_adapter import robust_baseline
from rca_ml.m13_runtime import M13Runtime
from rca_ml.m13_protocol import cluster_key, ranking_metrics
from r3_ml_screen import ROOT, audit, read, dump, sha


def main():
    out = ROOT / 'docs/product-research/r3-ml-diagnostics-v1'
    out.mkdir(exist_ok=False)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('5 minute diagnostic limit')))
    signal.alarm(300)
    started = time.monotonic()
    inventory, index, truth, services = audit()
    groups = defaultdict(list)
    for case in truth.values():
        groups[cluster_key(case)].append(case['incident_id'])
    selected = []
    for fault in sorted({c['fault_family'] for c in truth.values()}):
        for workload in sorted({c['workload_regime'] for c in truth.values()}):
            keys = [k for k in groups if k[2] == fault and k[3] == workload]
            key = min(keys, key=lambda k: hashlib.sha256(f'20261019:{k}'.encode()).hexdigest())
            selected.extend(groups[key])
    assert len(selected) == 20
    dump(out / 'registration.json', {'protocol_sha256': sha(ROOT / 'docs/R3_DIAGNOSTIC_PROTOCOL.md'),
         'code_sha256': sha(Path(__file__)), 'selected_ids': sorted(selected), 'ranking_fits': 0,
         'max_inference': 100, 'healthy_preprocessing_builds': 2, 'audit': inventory})
    run = ROOT / 'external-data/m13/runs/development-v1'
    healthy = read(run / 'healthy/baseline.json')
    baselines = {}
    baseline_details = {}
    for name, segment in zip(('healthy_low', 'healthy_high'), healthy['segments'], strict=True):
        lo, hi = segment['start_unix'], segment['end_unix']
        reduced = {'segments': [segment],
                   'metrics': [p for p in healthy['metrics'] if lo <= p['timestamp'] <= hi],
                   'traces': [p for p in healthy['traces'] if lo <= p['start_time_us'] / 1e6 <= hi]}
        baselines[name] = (fit_healthy_baseline(reduced, services), robust_baseline(reduced['metrics']))
        baseline_details[name] = {'segment': segment, 'metric_samples': len(reduced['metrics']),
                                 'span_samples': len(reduced['traces']),
                                 'channel_estimators': sum(len(x) for mod in baselines[name][0].values() if isinstance(mod, dict) for x in mod.values() if isinstance(x, dict)),
                                 'distinct_rps_values': 1, 'Huber_regressions': 0}
        dump(out / f'{name}.json', {'baseline': baselines[name][0], 'legacy': baselines[name][1]})
    runtime = M13Runtime(ROOT)
    original = (runtime.baseline, runtime.legacy_baseline)
    conditions = ('original', 'healthy_low', 'healthy_high', 'traces_empty', 'traces_unavailable')
    predictions = {name: {} for name in conditions}
    mask_pairs = []
    residual_boundary = {'metric_before_start_seconds': [], 'metric_after_end_seconds': [], 'trace_before_start_seconds': [], 'trace_after_end_seconds': []}
    allowed = {'start_unix', 'end_unix', 'requests_per_second', 'metrics', 'traces', 'traces_collected'}
    for item in index:
        name = item['incident_id']
        if name not in selected:
            continue
        raw = read(run / item['telemetry_path'])
        clean = {k: v for k, v in raw.items() if k in allowed}
        for p in raw['metrics']:
            if p['timestamp'] < raw['start_unix']:
                residual_boundary['metric_before_start_seconds'].append(raw['start_unix'] - p['timestamp'])
            if p['timestamp'] > raw['end_unix']:
                residual_boundary['metric_after_end_seconds'].append(p['timestamp'] - raw['end_unix'])
        for p in raw['traces']:
            t = p['start_time_us'] / 1e6
            if t < raw['start_unix']:
                residual_boundary['trace_before_start_seconds'].append(raw['start_unix'] - t)
            if t > raw['end_unix']:
                residual_boundary['trace_after_end_seconds'].append(t - raw['end_unix'])
        for condition in conditions:
            window = copy.deepcopy(clean)
            runtime.baseline, runtime.legacy_baseline = baselines.get(condition, original)
            if condition.startswith('traces_'):
                window['traces'] = []
                window['traces_collected'] = condition == 'traces_empty'
            result = runtime.analyze(dict(window, incident_id=name))
            predictions[condition][name] = [dict(service=x['service'], rank=x['rank'], score=x['model_score']) for x in result['candidates']]
        values = []
        for collected in (True, False):
            feature_rows = build_candidate_rows(dict(clean, traces=[], traces_collected=collected), original[0], services)
            values.append({r['service']: r['features'] for r in feature_rows})
        changed = sorted({k for s in services for k in values[0][s] if values[0][s][k] != values[1][s][k]})
        mask_pairs.append({'incident_id': name, 'changed_features': changed,
                           'ranking_identical': predictions['traces_empty'][name] == predictions['traces_unavailable'][name]})
    subset = {i: truth[i] for i in selected}
    metrics = {c: ranking_metrics(p, subset) for c, p in predictions.items()}
    sensitivity = {c: {'top1_changed': sum(predictions[c][i][0]['service'] != predictions['original'][i][0]['service'] for i in selected),
                       'total': len(selected)} for c in conditions}
    by_workload = {}
    for workload in ('mixed_low', 'mixed_high'):
        cases = {i: c for i, c in subset.items() if c['workload_regime'] == workload}
        by_workload[workload] = {c: ranking_metrics(p, cases) for c, p in predictions.items()}
    for path, expected in inventory['frozen_seals'].items():
        assert sha(ROOT / path) == expected
    for path, expected in inventory['protected_reports'].items():
        assert sha(ROOT / path) == expected
    boundaries = {k: {'count': len(v), 'max_seconds': max(v, default=0)} for k, v in residual_boundary.items()}
    result = {'scope': 'Known development sensitivity, not new accuracy or transfer estimate',
              'conditions': metrics, 'top1_sensitivity': sensitivity, 'by_workload': by_workload,
              'empty_vs_unavailable': mask_pairs, 'boundary_observations': boundaries,
              'baseline_builds': baseline_details, 'ranking_fits': 0, 'inference_calls': 100,
              'total_seconds': time.monotonic() - started, 'product_modified': False,
              'protected_assets_and_reports_unchanged': True}
    dump(out / 'predictions.json', predictions)
    dump(out / 'results.json', result)
    signal.alarm(0)
    print(json.dumps({'metrics': {c: {k: m[k] for k in ('mrr', 'ac_at_1')} for c, m in metrics.items()},
                      'sensitivity': sensitivity, 'mask_rankings_identical': sum(p['ranking_identical'] for p in mask_pairs),
                      'boundaries': boundaries, 'seconds': result['total_seconds']}, indent=2))


if __name__ == '__main__':
    main()
