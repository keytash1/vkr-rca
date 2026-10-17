"""Registered development comparisons on freshly collected teaching cases.

No arbitrary dataset, question or corpus uploads. Gold/controller files are not
read. Each assigned attempt is written BEFORE transmission; failures/unknown
usage stay in the denominator. This runner does not score its own prose.
"""

import argparse
from dataclasses import asdict
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cmd/thesis_demo"))
from assistant_contract import AssistantLimits
from assistant_privacy import prepare_outbound_aggregates
from assistant_supervisor import run_in_worker
from evaluation_ledger import validate_ledger
from runbook_corpus import RunbookCorpus

DATASETS = {"original-v1": ROOT / "docs/product-acceptance/intelligent-r2/cases-development-v1",
            "source-timings-v2": ROOT / "docs/product-acceptance/intelligent-r2/cases-development-enriched-v2",
            "refreshed-v3": ROOT / "docs/product-acceptance/intelligent-r2/cases-development-refreshed-v3",
            "capture-v2": ROOT / "docs/product-acceptance/intelligent-r2/cases-development-capture-v2",
            "locked-capture-v2": ROOT / "docs/product-acceptance/intelligent-r2/cases-locked-capture-v2"}
CORPUS_SHA256 = "07aea20fcbdd4161a490bb65b0424edef58112a6c465cb913cebca9af3d790b5"
QUESTIONS = {
    "Наблюдается замедление пользовательских запросов. Какие гипотезы и проверки следуют из этого интервала?",
    "Наблюдаются сбои или таймауты пользовательских запросов. Какие гипотезы и проверки следуют из этого интервала?",
}
MODULES = (
    "assistant_budget",
    "assistant_context",
    "assistant_contract",
    "assistant_privacy",
    "assistant_tools",
    "assistant_workflow",
    "assistant_runner",
    "assistant_worker",
    "assistant_provider",
    "assistant_auth",
    "assistant_supervisor",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wire(value):
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        ).encode()
        + b"\n"
    )


def save(path, value):
    with path.open("xb") as output:
        output.write(wire(value))


def configuration(modes=None, role="development"):
    return {
        "schema_version": "assistant-comparison-config-v1",
        "requested_model": "gpt-6.1-sol",
        "limits": asdict(AssistantLimits()),
        "repetitions": 3,
        "module_sha256": {
            name: sha((ROOT / "cmd/thesis_demo" / (name + ".py")).read_bytes())
            for name in MODULES
        },
        "runbook_corpus_sha256": CORPUS_SHA256,
        "provider": "official app-owned OpenAI Responses connection; store=false; no paid fallback",
        "modes": modes or ["C", "D", "E"],
        "gold_access": False,
        "purpose": ("LOCKED_ACCEPTANCE_NO_TUNING" if role == "locked" else "DEVELOPMENT_COMPARISON_NOT_LOCKED_ACCEPTANCE"),
    }


def load_completed_assignments(directory, config, plan):
    """Append-only resume: no rerun of success, failure, or a lost worker receipt."""
    if json.loads((directory / "configuration.json").read_text()) != config:
        raise ValueError("resume configuration differs")
    if json.loads((directory / "assigned-attempts.json").read_text()) != [list(p) for p in plan]:
        raise ValueError("resume assignments differ")
    completed, totals = set(), dict(count=0, failures=0, input=0, output=0, unknown=0)
    gap = False
    for identifier, repeat, mode in plan:
        attempt = f"{identifier}-{mode}-r{repeat}"
        started, result = directory / (attempt + "-started.json"), directory / (attempt + ".json")
        if started.is_symlink() or result.is_symlink():
            raise ValueError("symlinked receipt")
        if started.exists() != result.exists():
            # Never silently retry an interrupted process that may have sent I/O.
            raise ValueError("unresolved started-only/result-only assignment: " + attempt)
        if not result.exists():
            gap = True
            continue
        if gap:
            raise ValueError("completed assignments must form a prefix")
        receipt = json.loads(result.read_text())
        if receipt["attempt_id"] != attempt or receipt["configuration_sha256"] != sha(wire(config)):
            raise ValueError("receipt identity/configuration mismatch")
        initial = json.loads(started.read_text())
        for key in ("attempt_id", "configuration_sha256", "input_file_sha256", "started_at_unix"):
            if initial[key] != receipt[key]:
                raise ValueError("started/result receipt mismatch")
        outcome, usage = receipt["outcome"], receipt["outcome"].get("usage", {})
        completed.add(attempt)
        totals["count"] += 1
        totals["failures"] += outcome["status"] != "completed"
        totals["input"] += usage.get("known_input_tokens", 0)
        totals["output"] += usage.get("known_output_tokens", 0)
        totals["unknown"] += usage.get("unaccounted_attempts", 0)
    return completed, totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", action="append")
    selection.add_argument("--all-registered", action="store_true", help="Fixed 30 capture-v2 development assignments; wait for collector checkpoints")
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="original-v1")
    parser.add_argument("--role", choices=["development", "locked"], default="development")
    parser.add_argument("--freeze-manifest", type=Path)
    parser.add_argument("--mode", action="append", choices=["C","D","E"],help="Explicit diagnostic subset; default all three")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Append only unattempted fixed assignments, never retry failed ones")
    parser.add_argument("--unknown-limit", type=int, default=1, help="Finite cumulative stop threshold, including retained unknown attempts")
    parser.add_argument("--operator-decision", type=Path, help="Required recorded scope/budget decision for a raised unknown threshold")
    args = parser.parse_args()
    if args.resume and not args.output.is_dir():
        parser.error("resume requires an existing series")
    if args.output.exists() and not args.resume:
        parser.error("output must be new; never overwrite an attempt")
    if not 1 <= args.unknown_limit <= (6 if args.role == "locked" else 3):
        parser.error("unknown threshold outside this role's finite boundary")
    if args.unknown_limit != 1 and ((not args.resume and args.role != "locked") or not args.operator_decision or not args.operator_decision.is_file()):
        parser.error("raised unknown threshold requires resume and a recorded operator decision")
    if (args.role == "locked") != (args.dataset == "locked-capture-v2"):
        parser.error("locked role and locked dataset must be selected together")
    if args.role == "locked" and (not args.operator_decision or not args.operator_decision.is_file()):
        parser.error("locked stage requires its prior bounded operator/budget decision")
    dataset = DATASETS[args.dataset]
    if args.all_registered and args.dataset not in {"capture-v2", "locked-capture-v2"}:
        parser.error("all-registered is restricted to the fixed capture-v2 development series")
    identifiers = args.case or [
        f"r2-capture-v2-g{group:02d}-r{repeat:02d}"
        for group in (range(6, 11) if args.role == "locked" else range(1, 6)) for repeat in range(1, 7)
    ]
    if len(set(identifiers)) != len(identifiers):
        parser.error("duplicate selected case")

    def load_case(identifier):
        deadline = time.monotonic() + (3600 if args.all_registered else 0)
        waiting_announced = False
        while True:
            ledger_path = dataset / "ledger.json"
            if not ledger_path.is_file():
                checkpoints = sorted((dataset / "ledger").glob("[0-9][0-9][0-9].json"))
                ledger_path = checkpoints[-1] if checkpoints else None
            ledger = json.loads(ledger_path.read_text()) if ledger_path else []
            if ledger:
                validate_ledger(ledger)
            by_id = {entry["case_id"]: entry for entry in ledger}
            if identifier in by_id:
                break
            if time.monotonic() >= deadline or (dataset / "ledger.json").is_file():
                raise ValueError("assigned input has no completed collector checkpoint: " + identifier)
            if not waiting_announced:
                print(json.dumps({"waiting_for_collector": identifier}), flush=True)
                waiting_announced = True
            time.sleep(5)
        if identifier not in by_id or by_id[identifier]["role"] != args.role:
            raise ValueError("case is not a collected input for the selected role")
        path = dataset / "input" / (identifier + ".json")
        data = path.read_bytes()
        if path.is_symlink() or sha(data) != by_id[identifier]["input_sha256"]:
            raise ValueError("input integrity mismatch")
        case = json.loads(data)
        if case["question"] not in QUESTIONS:
            raise ValueError(
                "question differs from reviewed teaching symptom templates"
            )
        if by_id[identifier]["transmission"] != "approved_synthetic_to_openai":
            raise ValueError("input transmission not approved")
        return case, by_id[identifier]

    # Explicit selections must already exist. The fixed streaming series is
    # registered before answers; its inputs are checked only after collection.
    if not args.all_registered:
        for identifier in identifiers:
            load_case(identifier)
    corpus = RunbookCorpus(ROOT / "deploy/runbooks/basic-investigation.json")
    if corpus.sha256 != CORPUS_SHA256:
        raise ValueError("corpus differs from our reviewed public generic guidance")
    modes = args.mode or ["C","D","E"]
    if len(set(modes)) != len(modes):
        parser.error("duplicate selected mode")
    config = configuration(modes, args.role)
    freeze_sha = None
    if args.role == "locked":
        if not args.freeze_manifest or not args.freeze_manifest.is_file():
            parser.error("locked inference requires the prior freeze manifest")
        freeze_bytes = args.freeze_manifest.read_bytes()
        freeze = json.loads(freeze_bytes)
        if (freeze["configuration"] != config or
            freeze["comparison_runner_sha256"] != sha(Path(__file__).read_bytes()) or
            freeze["collector_sha256"] != sha((ROOT / "scripts/collect_assistant_cases.py").read_bytes()) or
            freeze["unknown_stop_threshold"] != args.unknown_limit or
            freeze["operator_decision_sha256"] != sha(args.operator_decision.read_bytes())):
            raise ValueError("locked frozen configuration/runner/budget differs")
        freeze_sha = sha(freeze_bytes)
    plan = [
        (identifier, repeat, mode)
        for case_index, identifier in enumerate(identifiers)
        for repeat in (1, 2, 3)
        for offset in [(case_index + repeat - 1) % len(modes)]
        for mode in (modes[offset:] + modes[:offset])
    ]
    if not args.send:
        print(
            json.dumps(
                {
                    "configuration_sha256": sha(wire(config)),
                    "assigned_attempts": len(plan),
                    "cases": identifiers,
                    "gold_access": False,
                    "dry_run": True,
                }
            )
        )
        return
    completed = set()
    summary_name = "execution-summary.json"
    if not args.resume:
        args.output.mkdir(parents=True)
    # A second CLI must not reserve the same previously unattempted assignment.
    series_lock = (args.output / ".runner.lock").open("a")
    try:
        fcntl.flock(series_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("another runner owns this series")
    if args.resume:
        completed, totals = load_completed_assignments(args.output, config, plan)
        count, failures, usage_input, usage_output, unknown = (totals[k] for k in ("count", "failures", "input", "output", "unknown"))
        if unknown >= args.unknown_limit:
            parser.error("retained unknown count already reached the cumulative stop threshold")
        segment = 1
        while (args.output / f"resume-{segment:03d}-registration.json").exists():
            segment += 1
        summary_name = f"resume-{segment:03d}-summary.json"
        save(args.output / f"resume-{segment:03d}-registration.json", {
            "configuration_sha256": sha(wire(config)), "retained_attempts": count,
            "retained_unknown_attempts": unknown, "assigned_total": len(plan),
            "unattempted_assignments_only": True, "unknown_stop_threshold": args.unknown_limit,
            "operator_decision_sha256": sha(args.operator_decision.read_bytes()) if args.operator_decision else None,
            "retained_receipts_sha256": {p.name: sha(p.read_bytes()) for p in sorted(args.output.glob("*.json"))},
            "registered_at_unix": time.time(),
        })
    else:
        save(args.output / "configuration.json", config)
        save(args.output / "assigned-attempts.json", plan)
        count, failures, usage_input, usage_output, unknown = 0, 0, 0, 0, 0
    cached_cases = {}
    for identifier, repeat, mode in plan:
        if configuration(modes, args.role) != config:
            raise RuntimeError(
                "assistant configuration changed; remaining assignments not sent"
            )
        if identifier not in cached_cases:
            cached_cases[identifier] = load_case(identifier)
        case, entry = cached_cases[identifier]
        attempt = f"{identifier}-{mode}-r{repeat}"
        if attempt in completed:
            # Recheck input provenance even for skipped immutable receipts.
            prior = json.loads((args.output / (attempt + ".json")).read_text())
            if prior["input_file_sha256"] != entry["input_sha256"]:
                raise ValueError("retained input provenance mismatch")
            continue
        receipt = {
            "attempt_id": attempt,
            "case_id": identifier,
            "repeat": repeat,
            "mode": mode,
            "input_file_sha256": entry["input_sha256"],
            "configuration_sha256": sha(wire(config)),
            "started_at_unix": time.time(),
            "role": args.role,
            "freeze_manifest_sha256": freeze_sha,
            "destination": "https://api.openai.com/v1/responses",
            "gold_access": False,
            "transmission": "approved local teaching aggregate telemetry and our fixed public generic guidance",
            "excludes": [
                "original names",
                "source URLs",
                "raw tags",
                "raw trace/span IDs",
                "gold",
                "corporate documents",
                "secrets",
            ],
        }
        save(args.output / (attempt + "-started.json"), receipt)
        if case["collection_status"] != "completed":
            outcome = {
                "status": "failed",
                "stop_reason": "COLLECTION_FAILED_NO_PROVIDER_CALL",
                "report": None,
                "usage": {
                    "known_input_tokens": 0,
                    "known_output_tokens": 0,
                    "unaccounted_attempts": 0,
                    "accounting_complete": True,
                },
            }
        else:
            tool_mode = mode in {"D", "E"}
            hint = case["analysis"]["candidates"] if mode in {"C", "D"} else None
            clean, hint, mapping = prepare_outbound_aggregates(
                case["catalog"], ranking=hint, include_details=tool_mode
            )
            receipt["privacy_version"] = mapping["privacy_version"]
            receipt["outbound_catalog_sha256"] = sha(wire(clean))
            receipt["ranking_hint_present"] = hint is not None
            outcome = run_in_worker(
                python_executable=sys.executable,
                state_dir=args.state_dir,
                model=config["requested_model"],
                catalog=clean,
                ranking=hint,
                question=case["question"],
                allow_external=True,
                workflow="tools" if tool_mode else "snapshot",
                runbooks=corpus.for_project(entry["system_id"]) if tool_mode else (),
            )
        receipt["outcome"] = outcome
        receipt["finished_at_unix"] = time.time()
        save(args.output / (attempt + ".json"), receipt)
        count += 1
        failures += outcome["status"] != "completed"
        usage = outcome.get("usage", {})
        usage_input += usage.get("known_input_tokens", 0)
        usage_output += usage.get("known_output_tokens", 0)
        unknown += usage.get("unaccounted_attempts", 0)
        print(
            json.dumps(
                {
                    "attempt": attempt,
                    "status": outcome["status"],
                    "stop_reason": outcome.get("stop_reason"),
                    "completed_assignments": count,
                    "assigned": len(plan),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        stop_code = outcome.get("stop_reason", "")
        if (unknown >= args.unknown_limit or stop_code in {
            "LLM_SIGN_IN_REQUIRED", "LLM_REAUTHORIZE_REQUIRED", "LLM_REFRESH_FAILED",
            "LLM_HTTP_401", "LLM_HTTP_403", "LLM_HTTP_402", "LLM_HTTP_429"}):
            # We cannot certify a global allowance after unknown accounting.
            # Preserve this failure, do not automatically spend more.
            break
    save(
        args.output / summary_name,
        {
            "assigned": len(plan),
            "attempted": count,
            "not_attempted": len(plan) - count,
            "failed_or_partial": failures,
            "known_input_tokens": usage_input,
            "known_output_tokens": usage_output,
            "unaccounted_attempts": unknown,
            "semantic_quality_scored": False,
        },
    )


if __name__ == "__main__":
    main()
