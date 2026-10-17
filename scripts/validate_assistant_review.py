"""Validate manually written case decisions and sum them; does not judge prose."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def field(report,path):
    value=report
    for part in path.split("."):
        value=value[int(part)] if isinstance(value,list) else value[part]
    if not isinstance(value,str) or not value:
        raise ValueError("reviewed factual path is not a nonempty text field")
    return value


def validate(directory, comparison=None):
    data=(directory/"packet.json").read_bytes()
    packet=json.loads(data)
    decisions=json.loads((directory/"decisions.json").read_text())
    key=json.loads((directory/"mode-key.json").read_text())
    if decisions["packet_sha256"]!=hashlib.sha256(data).hexdigest() or not decisions["all_report_fields_read"]:
        raise ValueError("packet/reading attestation differs")
    answers={item["review_id"]:item for item in packet["answers"]}
    rows=decisions["decisions"]
    if len(rows)!=len(answers) or {r["review_id"] for r in rows}!=set(answers) or set(key)!=set(answers):
        raise ValueError("all assigned outcomes require exactly one decision")
    if comparison is not None:
        configuration_sha=hashlib.sha256((comparison/"configuration.json").read_bytes()).hexdigest()
        plan=json.loads((comparison/"assigned-attempts.json").read_text())
        expected={(case,repeat,mode) for case,repeat,mode in plan if case==packet["case_id"]}
        actual=set()
        for identifier,entry in key.items():
            mode,repeat,attempt=entry["mode"],entry["repeat"],entry["attempt_id"]
            if mode not in ("C","D","E") or type(repeat) is not int or repeat not in (1,2,3):
                raise ValueError("invalid mode/repetition key")
            if attempt!=f'{packet["case_id"]}-{mode}-r{repeat}':
                raise ValueError("mode key does not name its assigned attempt")
            receipt_bytes=(comparison/(attempt+".json")).read_bytes()
            if hashlib.sha256(receipt_bytes).hexdigest()!=entry["receipt_sha256"]:
                raise ValueError("original receipt hash differs")
            receipt=json.loads(receipt_bytes)
            if receipt["configuration_sha256"]!=configuration_sha or receipt["input_file_sha256"]!=packet["input_sha256"]:
                raise ValueError("configuration/input provenance differs")
            if hashlib.sha256((configuration_sha+attempt).encode()).hexdigest()[:12]!=identifier:
                raise ValueError("masked ID differs from original assignment")
            outcome=receipt["outcome"];answer=answers[identifier]
            if any(answer.get(k)!=outcome.get(k) for k in ("status","stop_reason","report")):
                raise ValueError("reviewed answer differs from original receipt")
            actual.add((packet["case_id"],repeat,mode))
        if actual!=expected or len(expected)!=9:
            raise ValueError("mode key does not cover all nine original assignments")
    by_mode=defaultdict(lambda:dict(assigned=0,useful=0,next_check=0,factual_bundles=0,supported=0,critical=0))
    for row in rows:
        identifier=row["review_id"];answer=answers[identifier]
        if type(row["useful"]) is not bool or type(row["next_check"]) is not bool:
            raise ValueError("decisions must be explicit boolean")
        paths=row["factual_paths"]
        if len(paths)!=len(set(paths)):
            raise ValueError("duplicate factual path")
        unsupported=row["unsupported"]
        if len({x["path"] for x in unsupported})!=len(unsupported):
            raise ValueError("a failed bundle cannot be counted twice")
        for path in paths:field(answer["report"],path)
        for error in unsupported:
            if error["path"] not in paths or error["quote"] not in field(answer["report"],error["path"]):
                raise ValueError("unsupported quote/path does not match actual report")
            if not error.get("reason") or not error.get("severity"):
                raise ValueError("unexplained defect")
        if answer["status"]!="completed" and (row["useful"] or row["next_check"]):
            raise ValueError("no completed answer cannot pass usefulness")
        summary=by_mode[key[identifier]["mode"]]
        summary["assigned"]+=1;summary["useful"]+=row["useful"];summary["next_check"]+=row["next_check"]
        summary["factual_bundles"]+=len(paths);summary["supported"]+=len(paths)-len(unsupported)
        summary["critical"]+=len(row["critical_defects"])
    return {"case_id":packet["case_id"],"role":packet["role"],"modes":dict(by_mode),
        "script_is_semantic_judge":False,"independent_human_evaluation":False,
        "semantic_decisions":"Codex agent with primary-data and deterministic checks; not an independent human scorer",
        "not_overall_acceptance":True}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    parser.add_argument("--comparison",type=Path,help="Also bind mode labels and reports to original receipts")
    args=parser.parse_args()
    print(json.dumps(validate(args.directory,args.comparison),ensure_ascii=False,sort_keys=True,indent=2))
