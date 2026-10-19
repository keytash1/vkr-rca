"""Independent accounting of family-ablation predictions and publication scope."""
from pathlib import Path
import hashlib
import json
import math

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'docs/product-research'


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    folder=BASE/'r3-family-ablation-v1'
    registration=read(folder/'registration.json')
    result=read(folder/'results.json')
    predictions=read(folder/'predictions.json')
    assert sha(ROOT/'docs/R3_FAMILY_ABLATION_PROTOCOL.md')==registration['protocol_sha256']
    assert sha(ROOT/'scripts/r3_family_ablation.py')==registration['script_sha256']
    assert result['fits']==12 and result['incidents']==375 and not result['product_model_promoted']
    assert result['role']=='USED_DEVELOPMENT_ONLY'
    truth=predictions['truth_evaluation_only']; deltas=[]
    assert len(truth)==375
    for seed,variants in predictions['predictions'].items():
        mrr={}
        for variant,cases in variants.items():
            assert set(cases)==set(truth)
            rr=[]
            for name,ranking in cases.items():
                assert sorted(r['rank'] for r in ranking)==list(range(1,len(ranking)+1))
                assert len({r['service'] for r in ranking})==len(ranking)
                rank=next((r['rank'] for r in ranking if r['service']==truth[name]['root_service']),None)
                rr.append(1/rank if rank else 0)
            mrr[variant]=sum(rr)/len(rr)
            assert math.isclose(mrr[variant],result['seeds'][seed][variant]['overall']['mrr'],abs_tol=1e-12)
        deltas.append(mrr['expanded_observed']-mrr['restricted_four'])
    assert math.isclose(sum(deltas)/len(deltas),result['delta_mrr_mean'],abs_tol=1e-12)
    for path,expected in read(BASE/'r3-new-corpus-v1/overlap-and-protected.json')['protected_assets_sha256'].items():
        assert sha(ROOT/path)==expected,path
    paths=[
        'README.md','docs/PLAN_PRODUCT_ITERATION_2.md','docs/PROGRESS_PRODUCT_R3.md',
        'docs/HANDOFF_PRODUCT_NEXT_ITERATION.md','docs/R3_RAW_SOURCE_PROTOCOL.md',
        'docs/R3_FAMILY_ABLATION_PROTOCOL.md','docs/product-research/CORE_INPUT_REDUCTION_AUDIT.md',
        'docs/product-research/R3_FAMILY_ABLATION_RESULTS.md','scripts/r3_raw_source_probe.py',
        'scripts/r3_family_ablation.py','scripts/test_r3_raw_source_probe.py',
        'scripts/test_r3_family_ablation.py','scripts/finalize_r3_signal_audit.py',
        *[f'docs/product-research/r3-family-ablation-v1/{n}.json' for n in ('registration','results','predictions')],
        *[f'docs/product-research/r3-raw-source-v1/{n}.json' for n in ('acquisition','schema')],
    ]
    assert not any(p.startswith(('external-data/','reports/','.rca-private/')) for p in paths)
    manifest={'scope':'Research-only; no source telemetry, models or DOCX; plans are commit snapshots',
        'verdict':result['verdict'],'ranking_fits':12,'llm_calls':0,
        'protected_assets_unchanged':True,'sha256':{p:sha(ROOT/p) for p in paths}}
    (BASE/'R3_SIGNAL_AUDIT_MANIFEST.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'verified_files':len(paths),'bytes':sum((ROOT/p).stat().st_size for p in paths),
        'independent_mrr_recomputed':True,'protected_assets_unchanged':True}))


if __name__=='__main__': main()
