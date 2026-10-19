"""Verify and seal the small publishable R3 research record, not runtime assets."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'docs/product-research'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    temporal = BASE / 'r3-ml-temporal-v1'
    diagnostics = BASE / 'r3-ml-diagnostics-v1'
    missing = BASE / 'r3-ml-missingness-v2'
    a, b = read(temporal / 'results.json'), read(missing / 'results.json')
    assert a['verdict'] == b['verdict'] == 'REJECTED_FOR_PROMOTION'
    assert a['fits'] == 12 and b['new_fits'] == 6
    assert read(temporal / 'progress.json')['status'] == 'complete'
    audit = read(temporal / 'audit.json')
    for part in ('frozen_seals', 'protected_reports'):
        for path, expected in audit[part].items():
            assert sha(ROOT / path) == expected, path
    truth_path = ROOT / 'external-data/m13/runs/development-v1/truth.jsonl'
    assert sha(truth_path) == audit['truth_sha256']
    fields = ('incident_id', 'root_service', 'fault_family', 'workload_regime', 'intensity', 'repetition')
    cases = [{k: row[k] for k in fields} for line in truth_path.read_text().splitlines() for row in [json.loads(line)]]
    labels = BASE / 'R3_ML_EVALUATION_LABELS.json'
    labels.write_text(json.dumps({'role': 'USED_DEVELOPMENT_EVALUATION_ONLY',
        'system': 'DeathStarBench-SocialNetwork', 'cases': cases}, ensure_ascii=False, indent=2) + '\n')
    files = [ROOT / p for p in (
        'docs/HANDOFF_PRODUCT_NEXT_ITERATION.md', 'docs/PLAN_PRODUCT_ITERATION_2.md',
        'docs/PROGRESS_PRODUCT_R3.md', 'docs/product-architecture/GETTING_STARTED.md',
        'docs/R3_ML_PROTOCOL.md', 'docs/R3_DIAGNOSTIC_PROTOCOL.md',
        'docs/R3_MISSINGNESS_PROTOCOL.md', 'docs/R3_SCHEMA_ERRATUM.md',
        'ml/rca_ml/r3_temporal.py', 'scripts/r3_ml_screen.py', 'scripts/r3_ml_diagnostics.py',
        'scripts/r3_missingness_screen.py', 'scripts/test_r3_temporal.py', 'scripts/finalize_r3_ml.py',
        'docs/product-research/R3_ML_RESULTS.md')]
    files.append(labels)
    for directory, names in (
        (temporal, ('audit.json', 'registration.json', 'results.json', 'predictions.json')),
        (diagnostics, ('registration.json', 'results.json', 'predictions.json', 'healthy_low.json', 'healthy_high.json')),
        (BASE / 'r3-ml-missingness-v1', ('registration.json', 'STOPPED.json')),
        (missing, ('registration.json', 'results.json', 'predictions.json')),
    ):
        files.extend(directory / name for name in names)
    paths = [str(p.relative_to(ROOT)) for p in files]
    assert not any(p.startswith(('reports/', '.rca-private/', 'external-data/')) for p in paths)
    manifest = {'scope': 'Research-only negative results; product runtime and DOCX excluded',
        'verdicts': {'temporal': a['verdict'], 'missingness': b['verdict']},
        'ranking_fits': 18, 'new_llm_calls': 0, 'sha256': {str(p.relative_to(ROOT)): sha(p) for p in files}}
    (BASE / 'R3_ML_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'verified_files': len(files), 'bytes': sum(p.stat().st_size for p in files),
        'historical_assets_and_reports_unchanged': True, 'runtime_changes': 0}, indent=2))


if __name__ == '__main__':
    main()
