"""Small provider-neutral report contract. Structural validity is not truth."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol


class AssistantContractError(ValueError):
    pass


@dataclass(frozen=True)
class AssistantLimits:
    model_calls: int = 4
    tool_calls: int = 6
    tool_steps: int = 3
    input_tokens: int = 12000
    output_tokens: int = 3000
    wall_seconds: int = 60

    def __post_init__(self):
        bounds = {
            "model_calls": 4,
            "tool_calls": 6,
            "tool_steps": 3,
            "input_tokens": 12000,
            "output_tokens": 3000,
            "wall_seconds": 60,
        }
        for name, maximum in bounds.items():
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= maximum
            ):
                raise AssistantContractError("ASSISTANT_LIMIT_INVALID")


@dataclass(frozen=True)
class ProviderReply:
    text: str
    model: str
    response_id: str
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    # Only completed, server-validated response items. Kept in memory for a
    # stateless continuation, never exported as hidden chain of thought.
    tool_calls: tuple[dict, ...] = ()
    output_items: tuple[dict, ...] = ()


class AssistantProvider(Protocol):
    def complete(
        self,
        *,
        model: str,
        instructions: str,
        input_items: list[dict],
        timeout_seconds: float,
        cancel=None,
        response_schema=None,
        tools=None,
        tool_choice=None,
    ) -> ProviderReply: ...


def validate_conversation(conversation, catalog):
    """Prior assistant messages remain untrusted hypotheses, not observations."""
    if not isinstance(conversation, (list, tuple)) or len(conversation) > 2:
        raise AssistantContractError("ASSISTANT_CONVERSATION_BUDGET")
    for turn in conversation:
        if (
            not isinstance(turn, dict)
            or set(turn) != {"question", "report", "mode"}
            or turn["mode"] not in {"C", "D"}
            or not isinstance(turn["question"], str)
            or not 0 < len(turn["question"]) <= 2000
        ):
            raise AssistantContractError("ASSISTANT_CONVERSATION_INVALID")
        validate_report(turn["report"], catalog)
    return list(conversation)


def report_schema(catalog=None):
    """Same shape in provider JSON Schema and local validation; no invented fields."""
    text = {"type": "string", "maxLength": 1200}
    texts = {"type": "array", "items": text, "maxItems": 8}
    definitions = {}
    service = text
    references = texts
    if catalog is not None:
        services = sorted(set(catalog["services"]))
        ids = sorted({fact["id"] for fact in catalog["observations"]})
        definitions = {
            "service_id": {"type": "string"},
            "observation_id": {"type": "string"},
        }
        if services:
            definitions["service_id"]["enum"] = services
        if ids:
            definitions["observation_id"]["enum"] = ids
        service = {"$ref": "#/$defs/service_id"}
        references = {
            "type": "array",
            "items": {"$ref": "#/$defs/observation_id"},
            "maxItems": 12 if ids else 0,
        }

    def obj(properties):
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    check = obj(
        {"action": text, "expected_observation": text, "evidence_ids": references}
    )
    hypothesis = obj(
        {
            "service": service,
            "statement": text,
            "supporting_evidence_ids": references,
            "contradicting_evidence_ids": references,
            "unknowns": texts | {"maxItems": 2},
            "next_checks": {"type": "array", "items": check, "maxItems": 1},
        }
    )
    schema = obj(
        {
            "summary": text,
            "hypotheses": {"type": "array", "items": hypothesis, "maxItems": 2},
            "data_gaps": texts | {"maxItems": 3},
            "limitations": texts | {"maxItems": 2},
            "action_proposals": {"type": "array", "maxItems": 2, "items": obj({
                "service": service,
                "purpose": {"type": "string", "enum": ["mitigation", "corrective", "preventive"]},
                "title": text, "rationale": text,
                "verification_plan": text, "evidence_ids": references,
            })},
        }
    )
    if definitions:
        schema["$defs"] = definitions
        if not services:
            schema["properties"]["hypotheses"]["maxItems"] = 0
    return schema


def parse_report(text, catalog):
    """Reject duplicate keys, non-finite constants and code fences, not just bad JSON."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AssistantContractError("REPORT_DUPLICATE_KEY")
            result[key] = value
        return result

    def constant(_):
        raise AssistantContractError("REPORT_NONFINITE")

    if not isinstance(text, str) or len(text.encode()) > 48 * 1024:
        raise AssistantContractError("REPORT_SIZE_INVALID")
    try:
        report = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError):
        raise AssistantContractError("REPORT_JSON_INVALID") from None
    validated = validate_report(report, catalog)
    # Stored historical answers remain readable via validate_report, but a new
    # provider answer must satisfy the current schema, including explicit [].
    if "action_proposals" not in validated:
        raise AssistantContractError("REPORT_ACTION_PROPOSALS_REQUIRED")
    return validated


def _exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AssistantContractError("REPORT_FIELDS_INVALID")


def _text(value, limit=1200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AssistantContractError("REPORT_TEXT_INVALID")


def _texts(values, maximum=8):
    if not isinstance(values, list) or len(values) > maximum:
        raise AssistantContractError("REPORT_LIST_INVALID")
    for value in values:
        _text(value)


def validate_report(report, catalog):
    """No arbitrary links/fields, all references scoped to the selected snapshot.

    Entailment, critical false claims and usefulness require I04/I09 evaluation;
    this function must never be described as a semantic truth guarantee.
    """
    # Read stored v1 reports as well; new provider output includes proposals.
    old_fields = {"summary", "hypotheses", "data_gaps", "limitations"}
    if not isinstance(report, dict) or set(report) not in (old_fields, old_fields | {"action_proposals"}):
        raise AssistantContractError("REPORT_FIELDS_INVALID")
    _text(report["summary"])
    _texts(report["data_gaps"])
    _texts(report["limitations"])
    hypotheses = report["hypotheses"]
    if not isinstance(hypotheses, list) or len(hypotheses) > 5:
        raise AssistantContractError("REPORT_HYPOTHESES_INVALID")
    services = set(catalog["services"])
    observations = {fact["id"] for fact in catalog["observations"]}

    def refs(values):
        if (
            not isinstance(values, list)
            or len(values) > 12
            or any(
                not isinstance(value, str) or value not in observations
                for value in values
            )
            or len(set(values)) != len(values)
        ):
            raise AssistantContractError("REPORT_EVIDENCE_OUTSIDE_SCOPE")

    for hypothesis in hypotheses:
        _exact(
            hypothesis,
            (
                "service",
                "statement",
                "supporting_evidence_ids",
                "contradicting_evidence_ids",
                "unknowns",
                "next_checks",
            ),
        )
        if (
            not isinstance(hypothesis["service"], str)
            or hypothesis["service"] not in services
        ):
            raise AssistantContractError("REPORT_SERVICE_OUTSIDE_SCOPE")
        _text(hypothesis["statement"])
        refs(hypothesis["supporting_evidence_ids"])
        refs(hypothesis["contradicting_evidence_ids"])
        if set(hypothesis["supporting_evidence_ids"]) & set(
            hypothesis["contradicting_evidence_ids"]
        ):
            raise AssistantContractError("REPORT_CONFLICTING_REFERENCE")
        if not hypothesis["supporting_evidence_ids"] and not hypothesis["unknowns"]:
            raise AssistantContractError("REPORT_UNGROUNDED_HYPOTHESIS")
        _texts(hypothesis["unknowns"])
        checks = hypothesis["next_checks"]
        if not isinstance(checks, list) or len(checks) > 4:
            raise AssistantContractError("REPORT_CHECKS_INVALID")
        for check in checks:
            _exact(check, ("action", "expected_observation", "evidence_ids"))
            _text(check["action"])
            _text(check["expected_observation"])
            refs(check["evidence_ids"])
    proposals = report.get("action_proposals", [])
    if not isinstance(proposals, list) or len(proposals) > 2:
        raise AssistantContractError("REPORT_ACTION_BUDGET")
    for item in proposals:
        _exact(item, ("service", "purpose", "title", "rationale", "verification_plan", "evidence_ids"))
        if not isinstance(item["service"], str) or item["service"] not in services:
            raise AssistantContractError("REPORT_SERVICE_OUTSIDE_SCOPE")
        if item["purpose"] not in {"mitigation", "corrective", "preventive"}:
            raise AssistantContractError("REPORT_ACTION_PURPOSE_INVALID")
        for field in ("title", "rationale", "verification_plan"):
            _text(item[field])
        refs(item["evidence_ids"])
        if not item["evidence_ids"]:
            raise AssistantContractError("REPORT_ACTION_EVIDENCE_REQUIRED")
    return report
