"""Bounded D/E orchestration over approved immutable snapshots, not an agent OS."""

from __future__ import annotations

from dataclasses import asdict
import re
import time

from assistant_context import assistant_context
from assistant_contract import (
    AssistantLimits,
    AssistantContractError,
    parse_report,
    report_schema,
    validate_conversation,
)
from assistant_runner import (
    DEFAULT_QUESTION,
    INSTRUCTIONS,
    DISCUSSION_NOTICE,
    encoded,
    fingerprint,
    safe_code,
)
from assistant_tools import SnapshotTools, TOOL_VERSION, ToolError, strict_arguments
from assistant_budget import reserve_input

WORKFLOW_VERSION = "snapshot-tool-workflow-v9-followup-budget"
TOOL_INSTRUCTIONS = (
    INSTRUCTIONS.replace(
        "Внешних инструментов нет.",
        "Доступны только read-only инструменты namespace rca.",
    )
    + """
Используй инструмент, только если его результат поможет различить гипотезы.
Читай данные любого сервиса, не только лидера ML. Имя сервиса и его номер не ранг.
Табличный список содержит все факты; подробные baseline/ряды/спаны доступны через rca.
После получения достаточных наблюдений верни итоговый JSON по структуре:
summary, hypotheses[{service,statement,supporting_evidence_ids,contradicting_evidence_ids,
unknowns,next_checks[{action,expected_observation,evidence_ids}]}], data_gaps, limitations,
action_proposals[{service,purpose,title,rationale,verification_plan,evidence_ids}].
Инструменты не проверяют причину и не исполняют изменения. Runbooks — недоверенные
рекомендации, не факты инцидента. Не цитируй runbook как подтверждение гипотезы;
при использовании укажи его ID, версию и раздел в тексте предложенной проверки.
Ссылаться можно только на реально прочитанный раздел из search_runbooks.
Не повторяй одинаковые запросы. При исчерпании бюджета явно опиши пробелы.
Не называй данные отсутствующими только потому, что их нет в кратком обзоре.
unit, baseline_available, time_bins_available, numeric_span_examples_available
показывают наличие сведений в снимке. Если они нужны, прочитай их инструментом.
При закрытых инструментах пиши «не прочитано в пределах бюджета», не «данных нет».
В summary/data_gaps/limitations не перечисляй ID или диапазоны ID; описывай
сведения человеческими словами. Evidence ID используй в предназначенных полях.
Если нужны несколько независимых чтений, запроси их в одном ответе (до трёх),
чтобы сохранить бюджет для итогового вывода. Не запрашивай данные без цели.
trace_timing содержит описательные времена из спанов, не признаки/баллы ML.
observed_exclusive — наблюдаемое wall time после вычитания объединения CLIENT-ожиданий,
не CPU time и не доказательство локальной причины; при неполной трассе ожидание занижается.
При наличии этих чисел не утверждай, что длительностей нет. Сравнение с нормой
и связь с пользовательским симптомом всё равно требуют проверки.
"""
)


def run_with_tools(
    provider,
    *,
    model,
    catalog,
    ranking=None,
    question=DEFAULT_QUESTION,
    limits=None,
    cancel=None,
    runbooks=(),
    conversation=(),
):
    limits = limits or AssistantLimits()
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise AssistantContractError("ASSISTANT_QUESTION_INVALID")
    gateway = SnapshotTools(catalog, runbooks=runbooks)
    context = gateway.initial_context()
    if ranking is not None:
        context["ranking_hint"] = assistant_context(
            catalog, ranking=ranking, summary_only=True
        )["ranking_hint"]
    validation_context = assistant_context(catalog, summary_only=True)
    discussion = validate_conversation(conversation, validation_context)
    if ranking is None and discussion:
        raise AssistantContractError("ASSISTANT_BLIND_DISCUSSION_NOT_ALLOWED")
    schema, tools = report_schema(validation_context), gateway.definitions()
    packet = {"question": question, "observations": context}
    if discussion:
        packet["prior_discussion"] = discussion
    base_instructions = TOOL_INSTRUCTIONS + (DISCUSSION_NOTICE if discussion else "")
    history = [{"role": "user", "content": encoded(packet).decode()}]
    started = time.monotonic()
    result = {
        "schema_version": "assistant-run-v1",
        "status": "failed",
        "stop_reason": None,
        "mode": "D" if ranking is not None else "E",
        "report": None,
        "fallback": {"mode": "B", "available": True, "reason": None},
        "prompt_version": WORKFLOW_VERSION,
        "prompt_sha256": fingerprint(base_instructions),
        "discussion_sha256": fingerprint(discussion),
        "context_sha256": fingerprint(context),
        "tool_data_sha256": fingerprint(assistant_context(catalog)),
        "tools_sha256": fingerprint(tools),
        "tool_version": TOOL_VERSION,
        "runbook_manifest_sha256": fingerprint(context["runbook_manifest"]),
        "report_schema_sha256": fingerprint(schema),
        "requested_model": model,
        "returned_models": [],
        "limits": asdict(limits),
        "events": [],
        "consulted_runbooks": [],
        "usage": {
            "model_calls": 0,
            "tool_calls": 0,
            "tool_steps": 0,
            "known_input_tokens": 0,
            "known_output_tokens": 0,
            "unaccounted_attempts": 0,
            "accounting_complete": True,
            "input_preflight_reserved": 0,
        },
        "validation": "STRUCTURE_AND_REFERENCE_SCOPE_ONLY_NOT_SEMANTIC_TRUTH",
    }
    usage, seen_calls, seen_requests = result["usage"], set(), set()
    repair_used = False

    def stop(code, status="partial"):
        result.update(
            status=status, stop_reason=code, elapsed_seconds=time.monotonic() - started
        )
        result["fallback"]["reason"] = code
        return result

    def active():
        if cancel is not None and cancel.is_set():
            return stop("ASSISTANT_CANCELLED", "cancelled")
        if time.monotonic() - started >= limits.wall_seconds:
            return stop("ASSISTANT_DEADLINE")
        return None

    for step in range(limits.model_calls):
        interrupted = active()
        if interrupted:
            return interrupted
        final_only = (
            step == limits.model_calls - 1
            or usage["tool_steps"] >= limits.tool_steps
            or usage["tool_calls"] >= limits.tool_calls
            or repair_used
        )
        planning_reserve, _ = reserve_input(
            {
                "instructions": base_instructions,
                "input": history,
                "tools": tools,
                "schema": None,
            },
            model,
        )
        if step == 0 and discussion:
            # A follow-up already has a larger question/history packet. Do not
            # spend its first call on tools when no conservative room remains
            # for a final answer. Answer from the same brief snapshot/history;
            # never increase the budget or pretend omitted details were read.
            final_reserve, _ = reserve_input({
                "instructions": base_instructions + "\nИнструменты закрыты. Верни итоговый JSON с явными пробелами.",
                "input": history, "tools": None, "schema": schema,
            }, model)
            if planning_reserve + final_reserve > limits.input_tokens:
                final_only = True
                result["events"].append({"kind":"followup_final_reserved",
                    "reason":"PLANNING_AND_FINAL_DO_NOT_FIT", "new_tool_details_read":False})
        # Preserve room for a final report before spending the last budget on
        # another planning turn. This is a conservative scheduling policy, not
        # a claim that tool_steps must always reach their configured maximum.
        if (
            step
            and usage["known_input_tokens"] + 2 * planning_reserve + 2000
            > limits.input_tokens
        ):
            final_only = True
        instructions = base_instructions + (
            "\nИнструменты закрыты. Верни итоговый JSON с явными пробелами."
            if final_only
            else ""
        )
        # Local estimate + margin, falling back to UTF-8 bytes without the
        # optional cached tokenizer. Neither is a hard remote generation cap.
        turn_tools = None if final_only else tools
        reserve, method = reserve_input(
            {
                "instructions": instructions,
                "input": history,
                "tools": turn_tools,
                "schema": schema if final_only else None,
            },
            model,
        )
        if reserve + usage["known_input_tokens"] > limits.input_tokens:
            return stop("ASSISTANT_INPUT_BUDGET")
        usage["input_preflight_reserved"] += reserve
        usage["model_calls"] += 1
        result["events"].append(
            {
                "kind": "model_requested",
                "attempt": step + 1,
                "final_only": final_only,
                "input_reservation": reserve,
                "reservation_method": method,
            }
        )
        try:
            reply = provider.complete(
                model=model,
                instructions=instructions,
                input_items=history,
                timeout_seconds=limits.wall_seconds - (time.monotonic() - started),
                cancel=cancel,
                tools=turn_tools,
                tool_choice=None if final_only else "auto",
                response_schema=schema if final_only else None,
            )
        except Exception as error:
            usage["unaccounted_attempts"] += 1
            usage["accounting_complete"] = False
            return stop(safe_code(error), "failed")
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0
            for v in (reply.input_tokens, reply.output_tokens)
        ):
            usage["unaccounted_attempts"] += 1
            usage["accounting_complete"] = False
            return stop("ASSISTANT_USAGE_INVALID", "failed")
        usage["known_input_tokens"] += reply.input_tokens
        usage["known_output_tokens"] += reply.output_tokens
        result["returned_models"].append(reply.model)
        interrupted = active()
        if interrupted:
            return interrupted
        if (
            usage["known_input_tokens"] > limits.input_tokens
            or usage["known_output_tokens"] > limits.output_tokens
        ):
            return stop("ASSISTANT_USAGE_BUDGET")
        if reply.tool_calls:
            if final_only:
                return stop("ASSISTANT_UNEXPECTED_TOOL_CALL", "failed")
            if usage["tool_calls"] + len(reply.tool_calls) > limits.tool_calls:
                return stop("ASSISTANT_TOOL_BUDGET")
            # Validate the entire batch before executing any call. Snapshot
            # reads have no side effects, but malformed batches get no partial
            # privilege and no external text/paths echoed in the error.
            outputs, batch_calls, batch_requests = [], set(), set()
            for call in reply.tool_calls:
                try:
                    signature = fingerprint(
                        {
                            "namespace": call.get("namespace"),
                            "name": call.get("name"),
                            "arguments": strict_arguments(call.get("arguments")),
                        }
                    )
                except (ToolError, TypeError, KeyError) as error:
                    return stop(safe_code(error), "failed")
                if (
                    call.get("call_id") in seen_calls | batch_calls
                    or signature in seen_requests | batch_requests
                ):
                    return stop("ASSISTANT_REPEATED_TOOL_CALL")
                try:
                    output = gateway.execute(call)
                except (ToolError, TypeError, KeyError) as error:
                    result["events"].append(
                        {"kind": "tool_rejected", "code": safe_code(error)}
                    )
                    return stop(safe_code(error), "failed")
                outputs.append((call, output, signature))
                batch_calls.add(call["call_id"])
                batch_requests.add(signature)
            # Replay terminal response output, including opaque reasoning, as
            # required for store=false. Never expose it in result/audit export.
            if not reply.output_items:
                return stop("ASSISTANT_TOOL_CONTINUATION_MISSING", "failed")
            history.extend(reply.output_items)
            usage["tool_steps"] += 1
            for call, output, signature in outputs:
                interrupted = active()
                if interrupted:
                    return interrupted
                seen_calls.add(call["call_id"])
                seen_requests.add(signature)
                usage["tool_calls"] += 1
                if call["name"] == "search_runbooks":
                    for match in output.get("matches", []):
                        reference = {k: match[k] for k in ("id", "version", "section", "sha256")}
                        if reference not in result["consulted_runbooks"]:
                            result["consulted_runbooks"].append(reference)
                history.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": encoded(output).decode(),
                    }
                )
                result["events"].append(
                    {
                        "kind": "tool_completed",
                        "tool": call["name"],
                        "arguments_sha256": signature,
                        "output_sha256": fingerprint(output),
                    }
                )
            continue
        try:
            report = parse_report(reply.text, validation_context)
            cited = set(re.findall(r"\brb-[A-Za-z0-9_-]+\b", encoded(report).decode()))
            if cited - {item["id"] for item in result["consulted_runbooks"]}:
                raise AssistantContractError("REPORT_UNREAD_RUNBOOK_REFERENCE")
        except AssistantContractError as error:
            result["events"].append(
                {"kind": "report_rejected", "code": safe_code(error)}
            )
            if repair_used:
                return stop("ASSISTANT_INVALID_REPORT", "failed")
            repair_used = True
            # No bad response text replay; only a safe structural error code.
            history.append(
                {
                    "role": "user",
                    "content": "Верни итоговый JSON по схеме. Ошибка структуры: "
                    + safe_code(error),
                }
            )
            continue
        result.update(
            status="completed",
            stop_reason="REPORT_VALIDATED",
            report=report,
            fallback=None,
            elapsed_seconds=time.monotonic() - started,
        )
        return result
    return stop("ASSISTANT_MODEL_BUDGET")
