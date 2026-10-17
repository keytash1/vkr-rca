"""Mode-masked engineering review packets; never a semantic auto-judge.

Read only the registered local receipts and evaluator-side gold after all
answers of this case exist. No provider calls, recollection, tuning or writes
to input/oracle/answer. Masking is not an independent blinded human panel.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"cmd/thesis_demo")]
from assistant_privacy import prepare_outbound_aggregates
from assistant_tools import SnapshotTools,TOPICS,FAMILIES
from assistant_runner import fingerprint
from evaluate_assistant_cases import save,sha
from evaluation_ledger import validate_ledger
from runbook_corpus import RunbookCorpus


def replay_reads(catalog,runbooks,events):
    gateway=SnapshotTools(catalog,runbooks=runbooks)
    options=[]
    for service in catalog["services"]:
        for name in ("get_candidate_evidence","get_trace_examples","get_observed_dependencies"):
            options.append((name,{"service":service}))
        for family in FAMILIES:
            options.append(("compare_metric_to_baseline",{"service":service,"family":family}))
    options += [("search_runbooks",{"topic":topic}) for topic in TOPICS]
    by_hash={fingerprint({"namespace":"rca","name":name,"arguments":args}):(name,args)
             for name,args in options}
    result=[]
    for event in events:
        if event.get("kind")!="tool_completed":continue
        selected=by_hash.get(event["arguments_sha256"])
        if selected is None:
            result.append({"tool":event["tool"],"replayed":False,
                "reason":"ARGUMENTS_NOT_IN_FINITE_COMMON_READ_SET_NOT_A_PASS"})
            continue
        name,args=selected
        output=gateway.execute({"namespace":"rca","name":name,"arguments":json.dumps(args),"call_id":"offline-review"})
        if fingerprint(output)!=event["output_sha256"]:
            raise ValueError("tool replay differs from original receipt")
        result.append({"tool":name,"arguments":args,"replayed":True,
            "output_sha256":event["output_sha256"]})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",required=True,type=Path)
    parser.add_argument("--comparison",required=True,type=Path)
    parser.add_argument("--case",required=True)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    allowed=(ROOT/"docs/product-acceptance/intelligent-r2").resolve()
    dataset,comparison=args.dataset.resolve(),args.comparison.resolve()
    if not dataset.is_relative_to(allowed) or not comparison.is_relative_to(allowed) or args.output.exists():
        parser.error("registered inputs and new output only")
    ledger_path=dataset/"ledger.json"
    if not ledger_path.exists():
        checkpoints=sorted((dataset/"ledger").glob("[0-9][0-9][0-9].json"))
        if not checkpoints:parser.error("no completed input")
        ledger_path=checkpoints[-1]
    ledger=json.loads(ledger_path.read_text());validate_ledger(ledger)
    entry=next((x for x in ledger if x["case_id"]==args.case),None)
    if entry is None:parser.error("case absent from registered ledger")
    raw=(dataset/"input"/(args.case+".json")).read_bytes()
    gold_bytes=(dataset/"oracle"/(args.case+"-gold.json")).read_bytes()
    if sha(raw)!=entry["input_sha256"] or sha(gold_bytes)!=entry["gold_sha256"]:
        raise ValueError("input/gold differs from ledger")
    source,gold=json.loads(raw),json.loads(gold_bytes)
    if source["collection_status"]!="completed":
        parser.error("collection failure is scored as failure; no invented facts")
    clean,_,mapping=prepare_outbound_aggregates(source["catalog"],include_details=True)
    corpus=RunbookCorpus(ROOT/"deploy/runbooks/basic-investigation.json")
    config_bytes=(comparison/"configuration.json").read_bytes();config=json.loads(config_bytes)
    if corpus.sha256!=config["runbook_corpus_sha256"]:raise ValueError("runbook changed")
    plan=json.loads((comparison/"assigned-attempts.json").read_text())
    assigned=[x for x in plan if x[0]==args.case]
    if len(assigned)!=9:parser.error("requires all 3 modes × 3 repetitions")
    answers,key=[],{}
    for identifier,repeat,mode in assigned:
        attempt=f"{identifier}-{mode}-r{repeat}"
        path=comparison/(attempt+".json")
        if not path.is_file():parser.error("do not open this case before all assigned outcomes exist")
        data=path.read_bytes();receipt=json.loads(data)
        if receipt["configuration_sha256"]!=sha(config_bytes) or receipt["input_file_sha256"]!=sha(raw):
            raise ValueError("answer provenance differs")
        blind=hashlib.sha256((sha(config_bytes)+attempt).encode()).hexdigest()[:12]
        outcome=receipt["outcome"]
        answers.append({"review_id":blind,"status":outcome["status"],"stop_reason":outcome.get("stop_reason"),
            "report":outcome.get("report"),
            "verified_read_operations":replay_reads(clean,corpus.for_project(entry["system_id"]),outcome.get("events",[]))})
        key[blind]={"attempt_id":attempt,"mode":mode,"repeat":repeat,"receipt_sha256":sha(data)}
    packet={"purpose":"ENGINEERING_REVIEW_NOT_AUTOMATIC_QUALITY_SCORE","case_id":args.case,
        "role":entry["role"],"input_sha256":sha(raw),"gold_sha256":sha(gold_bytes),
        "source_facts":clean,"question":source["question"],
        "evaluator_only_control":{"target_alias":mapping["services"][gold["controlled_service"]],
            "intervention":gold["intervention"],"apply":gold["state_after_apply"],"reset":gold["state_after_reset"],
            "rubric":gold["rubric"]},"answers":sorted(answers,key=lambda x:x["review_id"]),
        "masking_limit":"Mode labels hidden here; reviewer is implementer, not an independent blinded panel."}
    args.output.mkdir(parents=True)
    save(args.output/"packet.json",packet);save(args.output/"mode-key.json",key)
    print(json.dumps({"packet":str(args.output/"packet.json"),"sha256":sha((args.output/"packet.json").read_bytes()),
        "answers":len(answers),"provider_calls":0,"original_receipts_changed":False}))


if __name__=="__main__":main()
