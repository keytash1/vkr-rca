"""Second bounded experiment: train-only missing-trace augmentation."""
from pathlib import Path
from collections import defaultdict
import json
import signal
import time

import numpy as np
import xgboost as xgb
from rca_ml.m13_experiment import _fit, _predict
from rca_ml.m13_features import FEATURES, RANKING_FEATURES, build_candidate_rows
from rca_ml.m13_protocol import cluster_key, ranking_metrics, rank_scores
from r3_ml_screen import ROOT, audit, read, dump, sha, intervals, CONFIG, SEEDS


def combine(values, ids):
    result = {}
    for name in ids:
        by_service = defaultdict(list)
        for ranking in values:
            for row in ranking[name]:
                by_service[row['service']].append(row['score'])
        result[name] = rank_scores({s: float(np.mean(v)) for s, v in by_service.items()})
    return result


def main():
    out = ROOT / 'docs/product-research/r3-ml-missingness-v2'
    out.mkdir(exist_ok=False)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('5 minute experiment limit')))
    signal.alarm(300)
    started = time.monotonic()
    prior = ROOT / 'docs/product-research/r3-ml-temporal-v1'
    inventory, index, truth, services = audit()
    previous = read(prior / 'registration.json')
    assert previous['seeds'] == list(SEEDS) and previous['config'] == CONFIG
    dump(out / 'registration.json', {'protocol_sha256': sha(ROOT / 'docs/R3_MISSINGNESS_PROTOCOL.md'),
         'runner_sha256': sha(Path(__file__)), 'previous_registration_sha256': sha(prior / 'registration.json'),
         'splits': previous['splits'], 'seeds': SEEDS, 'config': CONFIG, 'audit': inventory,
         'control_models': {str(p.relative_to(ROOT)): sha(p) for p in sorted(prior.glob('refit_control-*-fold*.json'))},
         'max_new_ranking_fits': 6, 'scope': 'USED_DEVELOPMENT_ONLY',
         'schema_erratum_sha256': sha(ROOT / 'docs/R3_SCHEMA_ERRATUM.md')})
    baseline = read(ROOT / 'ml/models/m13/healthy-baseline.json')
    original = read(prior / 'truth-free-features.json')
    masked = {}
    allowed = {'start_unix', 'end_unix', 'requests_per_second', 'metrics', 'traces', 'traces_collected'}
    columns = FEATURES + RANKING_FEATURES
    assert list(columns) == read(ROOT / 'ml/models/m13/freeze-manifest.json')['feature_schema']
    assert len(columns) == 62
    for item in index:
        name = item['incident_id']
        raw = read(ROOT / 'external-data/m13/runs/development-v1' / item['telemetry_path'])
        clean = {k: v for k, v in raw.items() if k in allowed}
        current = build_candidate_rows(dict(clean, traces=[], traces_collected=False), baseline, services)
        old = {r['service']: r['features'] for r in original[name]}
        for row in current:
            row['features'].update({k: old[row['service']][k] for k in RANKING_FEATURES})
            row['incident_id'] = name
        masked[name] = current
    for source in (original, masked):
        for name, rows in source.items():
            for row in rows:
                row['target'] = int(row['service'] == truth[name]['root_service'])
    train_views = dict(original)
    for name, rows in masked.items():
        # The suffix is a group/lookup key only; it never becomes a numeric feature.
        train_views[name + '-missing'] = [dict(row, incident_id=name + '-missing') for row in rows]
    per_seed = {}
    all_predictions = defaultdict(list)
    fits = 0
    for seed in SEEDS:
        predictions = {k: {} for k in ('control_original', 'control_missing', 'augmented_original', 'augmented_missing')}
        for split in previous['splits']:
            train, test = split['train'], split['test']
            assert not set(train) & set(test)
            assert not {cluster_key(truth[i]) for i in train} & {cluster_key(truth[i]) for i in test}
            augmented_ids = train + [name + '-missing' for name in train]
            assert not set(augmented_ids) & (set(test) | {name + '-missing' for name in test})
            control = xgb.Booster()
            control.load_model(prior / f"refit_control-{seed}-fold{split['fold']}.json")
            model = _fit(train_views, augmented_ids, columns, CONFIG, seed + split['fold'])
            fits += 1
            model.save_model(out / f"augmented-{seed}-fold{split['fold']}.json")
            predictions['control_original'].update(_predict(control, original, test, columns))
            predictions['control_missing'].update(_predict(control, masked, test, columns))
            predictions['augmented_original'].update(_predict(model, original, test, columns))
            predictions['augmented_missing'].update(_predict(model, masked, test, columns))
            print(f'Augmentation fit {fits}/6', flush=True)
        for variant, pred in predictions.items():
            assert set(pred) == set(truth)
            per_seed[f'{variant}-{seed}'] = ranking_metrics(pred, truth)
            all_predictions[variant].append(pred)
        dump(out / f'predictions-{seed}.json', predictions)
    predictions = {k: combine(v, truth) for k, v in all_predictions.items()}
    # Same controls, with a separate assertion that inference/code did not drift.
    previous_control = read(prior / 'predictions.json')['refit_control']
    assert predictions['control_original'] == previous_control
    metrics = {k: ranking_metrics(v, truth) for k, v in predictions.items()}
    comparisons = {suffix: intervals(predictions[f'augmented_{suffix}'], predictions[f'control_{suffix}'], truth) for suffix in ('original', 'missing')}
    slices = {}
    for fault in sorted({c['fault_family'] for c in truth.values()}):
        cases = {i: c for i, c in truth.items() if c['fault_family'] == fault}
        slices[fault] = {k: ranking_metrics(v, cases) for k, v in predictions.items()}
    a, b = metrics['augmented_original'], metrics['control_original']
    gates = {'missing_mrr_delta_05': comparisons['missing']['mrr']['delta'] >= .05,
             'missing_mrr_positive_ci': comparisons['missing']['mrr']['ci95'][0] > 0,
             'original_mrr_noninferior': comparisons['original']['mrr']['delta'] >= -.01,
             'original_ac_noninferior': all(a[k] >= b[k] - .02 for k in ('ac_at_1', 'ac_at_3', 'ac_at_5')),
             'missing_fault_ac1_noninferior': all(v['augmented_missing']['ac_at_1'] >= v['control_missing']['ac_at_1'] - .10 - 1e-12 for v in slices.values()),
             'coverage_preserved': all(v['candidate_universe_coverage'] == 1 for v in metrics.values())}
    for path, expected in inventory['frozen_seals'].items():
        assert sha(ROOT / path) == expected
    for path, expected in inventory['protected_reports'].items():
        assert sha(ROOT / path) == expected
    result = {'verdict': 'NEEDS_FRESH_TEST' if all(gates.values()) else 'REJECTED_FOR_PROMOTION',
              'scope': 'Known development OOF; artificial missing traces; not independent transfer',
              'metrics': metrics, 'per_seed': per_seed, 'comparisons': comparisons, 'fault_slices': slices,
              'gates': gates, 'new_fits': fits, 'seconds': time.monotonic() - started, 'product_modified': False}
    dump(out / 'predictions.json', predictions)
    dump(out / 'results.json', result)
    assert sum(p.stat().st_size for p in out.iterdir() if p.is_file()) <= 20 * 1024 * 1024
    signal.alarm(0)
    print(json.dumps({'verdict': result['verdict'], 'metrics': {k: {m: v[m] for m in ('ac_at_1', 'mrr')} for k, v in metrics.items()},
                      'comparisons': comparisons, 'gates': gates, 'fits': fits}, indent=2))


if __name__ == '__main__':
    main()
