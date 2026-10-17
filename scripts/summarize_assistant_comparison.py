"""Objective controlled-target accounting, not an LLM semantic-quality judge.

Reads gold only in the evaluator, after responses. No provider/tool calls.
All assigned attempts form the denominator, including missing/failed answers.
Candidate inclusion is not causal proof, general accuracy, or the rubric's
usefulness/grounding score. Those require a separate content review.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"cmd/thesis_demo"))
from assistant_privacy import prepare_outbound_aggregates
from evaluation_ledger import validate_ledger


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as output:
        json.dump(value,output,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
        output.write("\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    index = (len(values)-1)*p
    lo,hi = int(index),min(int(index)+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(index-lo)


def paired_target_accounting(grouped, modes, *, all_assignments_attempted):
    # An administrative stop can leave entire groups/modes unexposed. Treating
    # those assignments as observed negative outcomes creates spurious cluster
    # precision. Preserve them in the accounting denominator, not an effect CI.
    if not all_assignments_attempted:
        return {"status":"NOT_ESTIMATED_INCOMPLETE_ASSIGNMENT","estimates":None}
    if len(grouped) < 2:
        return {"status":"NOT_ESTIMATED_INSUFFICIENT_CLUSTERS","estimates":None}
    estimates = {}
    rng = random.Random(20261017)
    groups = sorted(grouped)
    for left,right in (("D","C"),("D","E")):
        if left not in modes or right not in modes:
            continue
        values = [grouped[g][left]-grouped[g][right] for g in groups]
        samples = [statistics.mean(rng.choice(values) for _ in groups) for _ in range(2000)]
        estimates[left+"-"+right] = {"mean_difference":statistics.mean(values),
            "cluster_bootstrap_95_low":percentile(samples,.025),"cluster_bootstrap_95_high":percentile(samples,.975),
            "clusters":len(groups),"seed":20261017,"resamples":2000}
    return {"status":"OBJECTIVE_TARGET_ACCOUNTING_ONLY_NOT_USEFULNESS","estimates":estimates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",required=True,type=Path)
    parser.add_argument("--comparison",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a new output directory")
    dataset,comparison = args.dataset.resolve(),args.comparison.resolve()
    approved = (ROOT/"docs/product-acceptance/intelligent-r2").resolve()
    if not dataset.is_relative_to(approved) or not comparison.is_relative_to(approved):
        parser.error("only the registered local teaching receipts")
    ledger = json.loads((dataset/"ledger.json").read_text())
    validate_ledger(ledger)
    entries = {item["case_id"]:item for item in ledger}
    assigned = json.loads((comparison/"assigned-attempts.json").read_text())
    config_bytes = (comparison/"configuration.json").read_bytes()
    config_sha = digest(config_bytes)
    records,cases = [],{}
    for identifier,repeat,mode in assigned:
        if identifier not in cases:
            entry = entries[identifier]
            input_bytes = (dataset/"input"/(identifier+".json")).read_bytes()
            gold_bytes = (dataset/"oracle"/(identifier+"-gold.json")).read_bytes()
            if digest(input_bytes)!=entry["input_sha256"] or digest(gold_bytes)!=entry["gold_sha256"]:
                raise ValueError("input/gold changed")
            case,gold = json.loads(input_bytes),json.loads(gold_bytes)
            if case["collection_status"]=="completed":
                clean,_,mapping = prepare_outbound_aggregates(case["catalog"],include_details=True)
                target = mapping["services"][gold["controlled_service"]]
            else:
                clean,mapping,target = None,None,None
            cases[identifier] = (entry,case,gold,clean,mapping,target)
        entry,case,gold,clean,mapping,target = cases[identifier]
        attempt = f"{identifier}-{mode}-r{repeat}"
        path = comparison/(attempt+".json")
        result = json.loads(path.read_text()) if path.is_file() else None
        if result and (result["input_file_sha256"]!=entry["input_sha256"] or result["configuration_sha256"]!=config_sha):
            raise ValueError("attempt provenance differs")
        outcome = result["outcome"] if result else {}
        report = outcome.get("report")
        completed = outcome.get("status")=="completed" and report is not None
        selected = [h["service"] for h in report["hypotheses"]] if report else []
        row = {"attempt_id":attempt,"case_id":identifier,"group_id":entry["group_id"],
            "system_id":entry["system_id"],"mode":mode,"repeat":repeat,"assigned":True,
            "attempted":result is not None,"status":outcome.get("status","not_attempted"),
            "stop_reason":outcome.get("stop_reason"),"structured_completed":completed,
            "controlled_target_in_hypotheses":completed and target in selected,
            "abstained":completed and not selected,"hypothesis_services":selected,
            "controlled_service":gold["controlled_service"],"controlled_pseudonym":target,
            "elapsed_seconds":outcome.get("elapsed_seconds"),"usage":outcome.get("usage",{}),
            "semantic_usefulness":None,"claim_grounding":None,"critical_falsehood":None}
        records.append(row)
        if result:
            # Labels hidden, not a claim of perfect blinding: report wording can
            # itself mention ML. Gold remains local to the evaluator packet.
            code = digest(attempt.encode())[:16]
            save(args.output/"review"/(code+".json"),{"review_code":code,"report":report,
                "observations":clean,"controlled_target":target,"gold_rubric":gold["rubric"],
                "status":outcome.get("status"),"note":"Mode label hidden; text may reveal mode. Content review is not automatically scored."})
    modes = {}
    for mode in sorted({r["mode"] for r in records}):
        rows = [r for r in records if r["mode"]==mode]
        modes[mode] = {"assigned":len(rows),"attempted":sum(r["attempted"] for r in rows),
            "structured_completed":sum(r["structured_completed"] for r in rows),
            "controlled_target_in_hypotheses":sum(r["controlled_target_in_hypotheses"] for r in rows),
            "abstained":sum(r["abstained"] for r in rows),"statuses":dict(Counter(r["status"] for r in rows)),
            "seconds_p50":percentile([r["elapsed_seconds"] for r in rows if r["elapsed_seconds"] is not None],.5),
            "seconds_p95":percentile([r["elapsed_seconds"] for r in rows if r["elapsed_seconds"] is not None],.95),
            "known_input_tokens":sum(r["usage"].get("known_input_tokens",0) for r in rows),
            "known_output_tokens":sum(r["usage"].get("known_output_tokens",0) for r in rows),
            "unaccounted_attempts":sum(r["usage"].get("unaccounted_attempts",0) for r in rows),
            "model_calls":sum(r["usage"].get("model_calls",0) for r in rows),
            "tool_calls":sum(r["usage"].get("tool_calls",0) for r in rows)}
    grouped = defaultdict(dict)
    for group in sorted({r["group_id"] for r in records}):
        for mode in modes:
            rows = [r for r in records if r["group_id"]==group and r["mode"]==mode]
            grouped[group][mode] = statistics.mean(float(r["controlled_target_in_hypotheses"]) for r in rows)
    all_attempted = bool(records) and all(r["attempted"] for r in records)
    paired = paired_target_accounting(grouped,modes,all_assignments_attempted=all_attempted)
    summary = {"purpose":"CONTROLLED_TARGET_ACCOUNTING_NOT_SEMANTIC_ACCEPTANCE",
        "batch_execution_finished":(comparison/"execution-summary.json").is_file(),
        "all_assignments_attempted":all_attempted,"assigned":len(records),
        "attempted":sum(r["attempted"] for r in records),"modes":modes,
        "group_target_inclusion_over_all_assigned":dict(grouped),"paired_target_inclusion":paired,
        "semantic_rubric_scored":False,"default_mode_promotion_decided":False,
        "warning":"Repeated episodes cluster by intervention. A target mention alone does not establish usefulness, factual entailment, causal proof, new ranker accuracy or MTTR improvement."}
    save(args.output/"records.json",records)
    save(args.output/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
