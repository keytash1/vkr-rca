"""Three fixed real follow-ups on existing approved teaching snapshots.

No fault label, raw tags or manual engineer card is added to outbound input.
Old generated answers are explicitly untrusted discussion, not new evidence.
Never overwrite, silently retry, or continue after unknown usage.
"""

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "cmd/thesis_demo"), str(ROOT / "scripts")]
from assistant_contract import parse_report
from assistant_privacy import prepare_outbound_aggregates
from assistant_supervisor import run_in_worker
from evaluate_assistant_cases import configuration, save, sha, wire
from runbook_corpus import RunbookCorpus

CASES = ("g01", "g02", "g03")
QUESTION = (
    "Продолжим по этому же снимку. Какие альтернативы основной гипотезе и как их различить? "
    "Если проверка подтвердит механизм, предложи уместную условную меру смягчения или "
    "снижения риска повтора и способ проверить её эффект. Не придумывай конкретную "
    "настройку, владельца, срок или выполненное действие; если сведений недостаточно, "
    "объясни, каких именно не хватает."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("new output only")
    dataset = ROOT / "docs/product-acceptance/intelligent-r2/cases-development-capture-v2/input"
    previous = ROOT / "docs/product-acceptance/intelligent-r2/development-actions-v1-comparison"
    corpus = RunbookCorpus(ROOT / "deploy/runbooks/basic-investigation.json")
    config = configuration(["D"])
    prepared = []
    for group in CASES:
        identifier = f"r2-capture-v2-{group}-r01"
        source_bytes = (dataset / (identifier + ".json")).read_bytes()
        source = json.loads(source_bytes)
        prior_bytes = (previous / (identifier + "-D-r1.json")).read_bytes()
        prior = json.loads(prior_bytes)
        clean, hint, _ = prepare_outbound_aggregates(source["catalog"], ranking=source["analysis"]["candidates"], include_details=True)
        if prior["outcome"]["status"] != "completed":
            raise ValueError("prior answer must be completed")
        report = parse_report(json.dumps(prior["outcome"]["report"]), clean)
        discussion = [{"question": source["question"], "report": report, "mode": "D"}]
        runbooks = corpus.for_project("local-three" if group in {"g01", "g02"} else "petclinic")
        prepared.append((identifier, clean, hint, discussion, runbooks, {
            "source_sha256": sha(source_bytes), "prior_receipt_sha256": sha(prior_bytes)}))
    design = {"configuration_sha256": sha(wire(config)), "assigned": 3,
        "question": QUESTION, "cases": [p[0] for p in prepared],
        "new_facts_added": False, "gold_access": False,
        "purpose": "DEVELOPMENT_REAL_FOLLOWUP_NOT_LOCKED_OR_AUTOMATIC_REMEDIATION"}
    if not args.send:
        print(wire(design).decode())
        return
    args.output.mkdir(parents=True)
    save(args.output / "registration.json", design)
    save(args.output / "configuration.json", config)
    done = unknown = 0
    for identifier, clean, hint, discussion, runbooks, provenance in prepared:
        if configuration(["D"]) != config:
            raise RuntimeError("configuration changed")
        receipt = provenance | {"case_id": identifier, "started_at_unix": time.time(),
            "question": QUESTION, "prior_discussion": discussion, "gold_access": False}
        save(args.output / (identifier + "-started.json"), receipt)
        outcome = run_in_worker(python_executable=sys.executable, state_dir=args.state_dir,
            model=config["requested_model"], catalog=clean, ranking=hint, question=QUESTION,
            conversation=discussion, allow_external=True, workflow="tools", runbooks=runbooks)
        save(args.output / (identifier + ".json"), receipt | {"outcome": outcome, "finished_at_unix": time.time()})
        done += 1
        unknown += outcome.get("usage", {}).get("unaccounted_attempts", 0)
        print(json.dumps({"case": identifier, "status": outcome["status"], "completed": done}), flush=True)
        if unknown:
            break
    save(args.output / "summary.json", {"assigned": 3, "attempted": done,
        "not_attempted": 3-done, "unaccounted_attempts": unknown, "semantic_quality_scored": False})


if __name__ == "__main__":
    main()
