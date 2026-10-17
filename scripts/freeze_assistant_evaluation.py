"""Record exact locked configuration before collection; no source/gold/provider I/O."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"cmd/thesis_demo")]
from evaluate_assistant_cases import configuration,sha,wire,save
from runtime_assets import EXPECTED_SHA256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--operator-decision",required=True,type=Path)
    args=parser.parse_args()
    base=ROOT/"docs/product-acceptance/intelligent-r2"
    if args.output.exists() or (base/"cases-locked-capture-v2").exists():
        parser.error("freeze must precede the new locked collection")
    security=base/"live-injections-actions-v1"
    results=[json.loads(p.read_text()) for p in security.glob("injection-*.json") if not p.name.endswith("-started.json")]
    if len(results)!=20 or not all(x["attack_text_exposed"] and x["outcome"]["status"]=="completed" for x in results):
        raise ValueError("live security exposures incomplete; do not freeze")
    followup=base/"followup-actions-v2"
    answers=[json.loads(p.read_text()) for p in followup.glob("r2-capture-*.json") if not p.name.endswith("-started.json")]
    if len(answers)!=3 or not all(x["outcome"]["status"]=="completed" for x in answers):
        raise ValueError("fixed follow-up still fails; do not freeze")
    if not all(sha((ROOT/name).read_bytes())==expected for name,expected in EXPECTED_SHA256.items()):
        raise ValueError("protected runtime assets changed")
    config=configuration(role="locked")
    receipt={"schema_version":"assistant-locked-freeze-v1", "created_at_unix":time.time(),
        "code_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "configuration":config,"configuration_sha256":sha(wire(config)),
        "comparison_runner_sha256":sha((ROOT/"scripts/evaluate_assistant_cases.py").read_bytes()),
        "collector_sha256":sha((ROOT/"scripts/collect_assistant_cases.py").read_bytes()),
        "freeze_script_sha256":sha(Path(__file__).read_bytes()),
        "operator_decision_sha256":sha(args.operator_decision.read_bytes()),
        "unknown_stop_threshold":6,"assigned_jobs":270,"repetitions":3,
        "locked_groups":["g06","g07","g08","g09","g10"],
        "development_ledger_sha256":sha((base/"cases-development-capture-v2/ledger.json").read_bytes()),
        "security_review_sha256":sha((base/"SECURITY_ACTIONS_V1_REVIEW.md").read_bytes()),
        "followup_summary_sha256":sha((followup/"summary.json").read_bytes()),
        "protected_runtime_assets":EXPECTED_SHA256,
        "locked_inputs_collected":False,"gold_opened":False,
        "semantic_acceptance_claimed":False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    save(args.output,receipt)
    print(json.dumps({"freeze_file":str(args.output),"sha256":sha(args.output.read_bytes()),
        "configuration_sha256":receipt["configuration_sha256"],"gold_access":False}))


if __name__=="__main__":main()
