"""Matched development-only family ablation; no product model imports."""
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path
import signal
import time

import numpy as np
import pyarrow.parquet as pq
import xgboost as xgb
from rca_ml.m10c_schema import METRIC_FAMILIES, METRIC_COLUMNS, METRIC_PERCENTILE_COLUMNS, METRIC_GLOBAL_COLUMNS
from rca_ml.m13_protocol import ranking_metrics, rank_scores

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/product-research/r3-family-ablation-v1'
COLS = METRIC_COLUMNS + METRIC_PERCENTILE_COLUMNS + METRIC_GLOBAL_COLUMNS
KEEP = frozenset(('cpu', 'memory', 'network', 'traffic_rate'))
SYSTEMS = ('RE1-OB', 'RE1-SS', 'RE1-TT')
SEEDS = (20261021, 20261022)
PARAMS = {'objective':'rank:ndcg', 'max_depth':3, 'eta':.08, 'nthread':1, 'tree_method':'hist'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def project(vector, restricted):
    result = {k:float(vector[k]) for k in COLS}
    if restricted:
        for family in set(METRIC_FAMILIES) - KEEP:
            for suffix in ('has', 'max_shift', 'persistence', 'max_shift_percentile'):
                result[f'metric_{family}_{suffix}'] = 0.0
    available = [f for f in METRIC_FAMILIES if result[f'metric_{f}_has'] > 0]
    shifts = sorted((result[f'metric_{f}_max_shift'] for f in available), reverse=True)
    result['metric_available_family_count'] = float(len(available))
    result['metric_available_family_ratio'] = len(available)/len(METRIC_FAMILIES)
    result['metric_max_shift_score'] = shifts[0] if shifts else 0.0
    result['metric_top2_score'] = float(np.mean(shifts[:2])) if shifts else 0.0
    if not all(np.isfinite(v) for v in result.values()):
        raise ValueError('nonfinite metric feature')
    return result


def matrix(rows, ids, restricted, train=False):
    selected = [r for name in ids for r in rows[name]]
    vectors = [project(r['vector'],restricted) for r in selected]
    array = np.asarray([[v[k] for k in COLS] for v in vectors],dtype=np.float32)
    result = xgb.DMatrix(array, feature_names=list(COLS))
    if train:
        result.set_label([r['label'] for r in selected])
        result.set_group([len(rows[name]) for name in ids])
    return result, selected


def metrics_by(rankings, truth, field):
    result = {}
    for key in sorted({v[field] for v in truth.values()}):
        reduced = {i:v for i,v in truth.items() if v[field]==key}
        result[key] = ranking_metrics({i:rankings[i] for i in reduced}, reduced)
    return result


def main():
    OUT.mkdir(exist_ok=False)
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('registered 5 minute budget')))
    signal.alarm(300)
    started=time.monotonic()
    source=ROOT/'artifacts/m10c/m10c-v2/truth-free.jsonl'
    index=ROOT/'external-data/rcaeval/cases.parquet'
    assert sha(source)=='f6bdb4e27f6901b1a9c5f3d655d792b9effd071b2fa84911d1b50bf6da560b8a'
    assert sha(index)=='c49a288920dbba2e8e724679a14636d5c7eb2b45426bba14007ef79a6c0ab1bb'
    metadata={r['case']:r for r in pq.read_table(index).to_pylist() if r['dataset'] in SYSTEMS}
    assert len(metadata)==375 and len(COLS)==56
    rows, truth={}, {}
    families=Counter()
    for line in source.open():
        # External telemetry is not parsed into experiment rows.
        if '"dataset":"RE1-' not in line and '"dataset": "RE1-' not in line:
            continue
        record=json.loads(line)
        if record['dataset'] not in SYSTEMS:
            continue
        name=record['external_case_id']; label=metadata[name]
        root=label['root_cause_service'].strip().lower().replace('_','-')
        if label['dataset'].endswith('-OB') and root=='frontend': root='frontendservice'
        truth[name]={'incident_id':name,'system':label['dataset'],'root_service':root,'fault_family':label['fault']}
        rows[name]=[{'service':r['service'],'vector':r['vector'],'label':int(r['service']==root)}
                    for r in record['features']['services']]
        assert rows[name]
        for family in METRIC_FAMILIES:
            families[family]+=sum(r['vector'][f'metric_{family}_has']>0 for r in rows[name])
    assert set(rows)==set(metadata)
    registration={'protocol_sha256':sha(ROOT/'docs/R3_FAMILY_ABLATION_PROTOCOL.md'),
        'script_sha256':sha(Path(__file__)), 'source_sha256':sha(source),'index_sha256':sha(index),
        'role':'USED_DEVELOPMENT_ONLY','incidents':len(rows),'seeds':SEEDS,'parameters':PARAMS,'rounds':24,
        'family_observed_candidate_rows':dict(families),'columns':COLS,'max_fits':12,
        'folds':{s:sorted(i for i in rows if truth[i]['system']==s) for s in SYSTEMS}}
    dump(OUT/'registration.json',registration)
    all_predictions={}; summaries={}; fits=0
    for seed in SEEDS:
        paired={}; seed_summary={}
        for variant, restricted in (('restricted_four',True),('expanded_observed',False)):
            predictions={}; heuristic={}
            for target in SYSTEMS:
                train_ids=sorted(i for i in rows if truth[i]['system']!=target)
                test_ids=sorted(i for i in rows if truth[i]['system']==target)
                train,_=matrix(rows,train_ids,restricted,True)
                test,selected=matrix(rows,test_ids,restricted)
                model=xgb.train(dict(PARAMS,seed=seed),train,num_boost_round=24,verbose_eval=False)
                fits+=1
                scores=model.predict(test)
                offset=0
                for name in test_ids:
                    n=len(rows[name]); chunk=selected[offset:offset+n]
                    predictions[name]=rank_scores({r['service']:float(v) for r,v in zip(chunk,scores[offset:offset+n],strict=True)})
                    heuristic[name]=rank_scores({r['service']:project(r['vector'],restricted)['metric_max_shift_score'] for r in chunk})
                    offset+=n
                print(seed,variant,target,flush=True)
            paired[variant]=predictions
            seed_summary[variant]={'overall':ranking_metrics(predictions,truth),
                'by_system':metrics_by(predictions,truth,'system'),'by_fault':metrics_by(predictions,truth,'fault_family'),
                'heuristic':ranking_metrics(heuristic,truth)}
        delta=seed_summary['expanded_observed']['overall']['mrr']-seed_summary['restricted_four']['overall']['mrr']
        seed_summary['delta_mrr']=delta
        all_predictions[str(seed)]=paired; summaries[str(seed)]=seed_summary
    # Seeds are paired repeats, never additional independent incidents.
    groups=defaultdict(list)
    for name,t in truth.items(): groups[(t['system'],t['root_service'],t['fault_family'])].append(name)
    group_deltas=[]
    for names in groups.values():
        differences=[]
        for name in names:
            for seed in SEEDS:
                values=[]
                for variant in ('restricted_four','expanded_observed'):
                    rank=next((r['rank'] for r in all_predictions[str(seed)][variant][name] if r['service']==truth[name]['root_service']),None)
                    values.append(1/rank if rank else 0)
                differences.append(values[1]-values[0])
        group_deltas.append((sum(differences),len(differences)))
    rng=np.random.default_rng(20261021); draws=[]
    for _ in range(2000):
        sample=[group_deltas[i] for i in rng.integers(0,len(group_deltas),len(group_deltas))]
        draws.append(sum(x[0] for x in sample)/sum(x[1] for x in sample))
    delta=float(np.mean([s['delta_mrr'] for s in summaries.values()]))
    ci=np.quantile(draws,[.025,.975]).tolist()
    guard=all(s['expanded_observed']['by_system'][system]['ac_at_5']-s['restricted_four']['by_system'][system]['ac_at_5']>=-.02
              for s in summaries.values() for system in SYSTEMS)
    verdict='SIGNAL_FOR_FRESH_PILOT' if delta>=.03 and ci[0]>0 and guard and all(s['delta_mrr']>0 for s in summaries.values()) else 'NO_CLEAR_SIGNAL'
    dump(OUT/'predictions.json',{'role':'USED_DEVELOPMENT_ONLY','truth_evaluation_only':truth,'predictions':all_predictions})
    result={'verdict':verdict,'role':'USED_DEVELOPMENT_ONLY','fits':fits,'incidents':len(rows),
        'delta_mrr_mean':delta,'cluster_ci95':ci,'clusters':len(groups),'ac5_system_guard':guard,
        'seeds':summaries,'runtime_seconds':time.monotonic()-started,'product_model_promoted':False}
    dump(OUT/'results.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='seeds'}))


if __name__=='__main__': main()
