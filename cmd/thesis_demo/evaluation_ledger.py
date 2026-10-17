"""Evaluator-side dataset gate. Never import this module into an assistant worker."""
from collections import Counter, defaultdict
import re

ROLES = {"development", "locked", "attack", "regression", "transport"}
HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
FIELDS = {"case_id", "group_id", "system_id", "role", "input_sha256", "gold_sha256",
          "origin", "transmission"}


class LedgerError(ValueError):
    pass


def validate_ledger(cases, *, require_acceptance_ready=False, regression_hashes=()):
    if not isinstance(cases, list):
        raise LedgerError("LEDGER_NOT_A_LIST")
    seen, groups, inputs, systems = set(), defaultdict(set), defaultdict(set), defaultdict(set)
    counts = Counter()
    protected = set(regression_hashes)
    for case in cases:
        if not isinstance(case, dict) or set(case) != FIELDS:
            raise LedgerError("LEDGER_FIELDS_INVALID")
        for key in ("case_id", "group_id", "system_id"):
            if not isinstance(case[key], str) or not ID.fullmatch(case[key]):
                raise LedgerError("LEDGER_ID_INVALID")
        if case["case_id"] in seen:
            raise LedgerError("LEDGER_DUPLICATE_CASE")
        seen.add(case["case_id"])
        role = case["role"]
        if not isinstance(role, str) or role not in ROLES:
            raise LedgerError("LEDGER_ROLE_INVALID")
        if any(not isinstance(case[key], str) or not HASH.fullmatch(case[key])
               for key in ("input_sha256", "gold_sha256")):
            raise LedgerError("LEDGER_HASH_INVALID")
        if not isinstance(case["origin"], str) or not case["origin"].strip() or len(case["origin"]) > 500:
            raise LedgerError("LEDGER_PROVENANCE_REQUIRED")
        if case["transmission"] not in {"local_only", "approved_synthetic_to_openai"}:
            raise LedgerError("LEDGER_TRANSMISSION_INVALID")
        if role in {"development", "locked"} and case["input_sha256"] in protected:
            raise LedgerError("LEDGER_REGRESSION_RELABELED")
        groups[(case["system_id"], case["group_id"])].add(role)
        inputs[case["input_sha256"]].add(role)
        systems[role].add(case["system_id"])
        counts[role] += 1
    for roles in (*groups.values(), *inputs.values()):
        if "locked" in roles and len(roles) != 1:
            raise LedgerError("LEDGER_LOCKED_CONTAMINATION")
        if "regression" in roles and roles & {"development", "locked"}:
            raise LedgerError("LEDGER_REGRESSION_RELABELED")
    ready = counts["development"] >= 30 and counts["locked"] >= 30 and counts["attack"] >= 20
    ready = ready and len(systems["development"]) >= 2 and len(systems["locked"]) >= 2
    if require_acceptance_ready and not ready:
        raise LedgerError("LEDGER_NOT_ACCEPTANCE_READY")
    return {"counts": dict(sorted(counts.items())), "acceptance_ready": ready,
            "note": "Structural gate only; source/gold independence still requires engineering review."}
