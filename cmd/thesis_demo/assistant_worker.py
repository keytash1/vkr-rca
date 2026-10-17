"""Private one-job process entrypoint, never a shell/tool execution service."""

import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys

from assistant_contract import AssistantLimits
from assistant_provider import ChatGPTPlanProvider
from assistant_runner import run_snapshot
from assistant_workflow import run_with_tools

MAX_JOB_BYTES = 256 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args()
    payload = sys.stdin.buffer.read(MAX_JOB_BYTES + 1)
    if len(payload) > MAX_JOB_BYTES:
        raise ValueError("JOB_TOO_LARGE")
    job = json.loads(payload)
    if not isinstance(job, dict) or set(job) - {
        "catalog",
        "ranking",
        "model",
        "question",
        "limits",
        "workflow",
        "runbooks",
        "conversation",
    }:
        raise ValueError("JOB_FIELDS_INVALID")
    if job.get("workflow", "snapshot") not in {"snapshot", "tools"}:
        raise ValueError("JOB_WORKFLOW_INVALID")
    settings = job.get("limits", {})
    if not isinstance(settings, dict) or set(settings) - {
        item.name for item in fields(AssistantLimits)
    }:
        raise ValueError("JOB_LIMITS_INVALID")
    limits = AssistantLimits(**settings)
    runner = run_with_tools if job.get("workflow") == "tools" else run_snapshot
    extra = {"runbooks": job.get("runbooks", [])} if runner is run_with_tools else {}
    outcome = runner(
        ChatGPTPlanProvider(args.state_dir),
        model=job["model"],
        catalog=job["catalog"],
        ranking=job.get("ranking"),
        question=job["question"],
        limits=limits,
        conversation=job.get("conversation", []),
        **extra,
    )
    sys.stdout.write(json.dumps(outcome, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No upstream body, prompt, traceback or credential may leave this pipe.
        sys.stdout.write('{"status":"failed","stop_reason":"ASSISTANT_WORKER_FAILURE"}')
        raise SystemExit(1)
