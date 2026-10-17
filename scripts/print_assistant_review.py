"""Compact lossless report text plus selected source scalars for manual reading.

Only metric time bins are omitted by default and explicitly counted. Use
--series ID when a response makes a trend/bin claim. No scoring or model I/O.
"""
import argparse
import json
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("packet",type=Path)
parser.add_argument("--series")
parser.add_argument("--answer", action="append", help="Print only selected review IDs; no scoring")
parser.add_argument("--no-source", action="store_true", help="Source facts were read in an earlier page")
parser.add_argument("--offset", type=int, default=0)
parser.add_argument("--count", type=int, default=9)
args=parser.parse_args()
p=json.loads(args.packet.read_text())
print("CASE",p["case_id"],"CONTROL",json.dumps(p["evaluator_only_control"],ensure_ascii=False))
c=p["source_facts"]
print("QUALITY",json.dumps(c["source_quality"],ensure_ascii=False),"LIMITATIONS",c["limitations"])
for f in c["observations"]:
    if args.no_source and args.series != f["id"]:
        continue
    v=f["values"]
    if f["kind"]=="metric":
        b=v.get("baseline_comparison") or {}
        print("METRIC",f["id"],f["service"],v["family"],v["unit"],
            "min/median/max",v.get("min"),v.get("median"),v.get("max"),
            "state",v["state"],"samples",v.get("samples"),"coverage",v.get("returned_point_coverage"),
            "baseline_expected/iqr/residual_p90",b.get("expected_at_observed_load"),b.get("residual_iqr"),b.get("absolute_residual_p90"),
            "load_comparability",b.get("load_comparability"),"bins_NOT_PRINTED",len(v.get("series",[])))
        if args.series==f["id"]:print("SERIES",json.dumps(v.get("series",[]),ensure_ascii=False))
    else:
        print("SOURCE",f["id"],f["service"],f["kind"],json.dumps(v,ensure_ascii=False,separators=(",",":")))
for a in p["answers"][args.offset:args.offset + args.count]:
    if args.answer and a["review_id"] not in args.answer:
        continue
    print("\nANSWER",a["review_id"],a["status"],a["stop_reason"])
    print("READS",json.dumps(a["verified_read_operations"],ensure_ascii=False,separators=(",",":")))
    r=a["report"]
    if r is None:continue
    print("summary:",r["summary"])
    for i,h in enumerate(r["hypotheses"]):
        prefix=f"hypotheses.{i}"
        print(prefix+".service:",h["service"])
        print(prefix+".statement:",h["statement"])
        print(prefix+".refs:",h["supporting_evidence_ids"],"CONTRADICT",h["contradicting_evidence_ids"])
        for j,t in enumerate(h["unknowns"]):print(prefix+f".unknowns.{j}:",t)
        for j,check in enumerate(h["next_checks"]):
            for key,value in check.items():print(prefix+f".next_checks.{j}."+key+":",value)
    for key in ("data_gaps","limitations"):
        for i,value in enumerate(r[key]):print(f"{key}.{i}:",value)
    print("action_proposals:",json.dumps(r.get("action_proposals",[]),ensure_ascii=False))
