"""New controlled teaching cases for the registered R2 evaluation protocol.

Controller and oracle stay evaluator-side. The assistant receives only a later
pseudonymous projection of input/catalog.json. No provider calls in this script.
Groups/roles are fixed before collection; six actual interventions per group,
not six paraphrases of one JSON. Locked collection requires a frozen config.
Only our two named local acceptance stacks can be controlled.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "cmd/thesis_demo")]
from evaluation_ledger import validate_ledger
from live_sources import collect
from server import DiagnosticApplication

GROUPS = (
    ("g01", "development", "local-three", "payment", "latency"),
    ("g02", "development", "local-three", "orders", "error"),
    ("g03", "development", "petclinic", "vets-service", "pause"),
    ("g04", "development", "petclinic", "customers-service", "pause"),
    ("g05", "development", "petclinic", "api-gateway", "pause"),
    ("g06", "locked", "local-three", "gateway", "latency"),
    ("g07", "locked", "local-three", "payment", "error"),
    ("g08", "locked", "local-three", "orders", "latency"),
    ("g09", "locked", "local-three", "gateway", "error"),
    ("g10", "locked", "petclinic", "visits-service", "pause"),
)
PORTS = {"gateway": 18680, "orders": 18681, "payment": 18682}
REPEATS = 6


def wire(value):
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        ).encode()
        + b"\n"
    )


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = wire(value)
    with path.open("xb") as target:
        target.write(data)
    return hashlib.sha256(data).hexdigest()


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=20).strip()


def fault(service, payload=None):
    url = f"http://127.0.0.1:{PORTS[service]}/debug/fault"
    req = Request(
        url,
        data=wire(payload) if payload is not None else None,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urlopen(req, timeout=10) as response:
        return json.load(response)


class Controller:
    def __init__(self, system, service, kind):
        self.system, self.service, self.kind = system, service, kind
        self.container = "rca-petclinic-acceptance-" + service + "-1"
        self.applied = False
        self.watchdog = None
        self.cancellation = None

    def arm_watchdog(self):
        directory = ROOT / ".rca-private/watchdogs"
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.cancellation = directory / (str(uuid.uuid4()) + ".cancelled")
        self.watchdog = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts/restore_teaching_fault.py"),
                "--system",
                self.system,
                "--service",
                self.service,
                "--kind",
                self.kind,
                "--cancel-file",
                str(self.cancellation),
                "--deadline",
                str(time.time() + 55),
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def state(self):
        if self.system == "local-three":
            return fault(self.service)
        # Read only state/labels, never credentials or environment.
        value = json.loads(
            docker("inspect", "--format", "{{json .State}}", self.container)
        )
        return {"running": value["Running"], "paused": value["Paused"]}

    def apply(self):
        if self.system == "local-three":
            for service in PORTS:
                if fault(service) != {"latency_ms": 0, "error_rate": 0}:
                    raise RuntimeError(
                        "teaching Go stack already has an active fault; preserve it"
                    )
            expected = {
                "latency_ms": 250 if self.kind == "latency" else 0,
                "error_rate": 1 if self.kind == "error" else 0,
            }
            self.arm_watchdog()
            self.applied = True
            result = fault(self.service, expected)
            if result != expected or self.state() != expected:
                raise RuntimeError("fault was not read back")
        else:
            project = docker(
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}',
                self.container,
            )
            if project != "rca-petclinic-acceptance" or self.state() != {
                "running": True,
                "paused": False,
            }:
                raise RuntimeError(
                    "only our running, unpaused Petclinic acceptance service can be paused"
                )
            self.arm_watchdog()
            self.applied = True
            docker("pause", self.container)
            if not self.state()["paused"]:
                raise RuntimeError("pause was not read back")
        return self.state()

    def reset(self):
        if not self.applied:
            return self.state()
        if self.system == "local-three":
            fault(self.service, {"latency_ms": 0, "error_rate": 0})
            expected = {"latency_ms": 0, "error_rate": 0}
        else:
            if self.state()["paused"]:
                docker("unpause", self.container)
            expected = {"running": True, "paused": False}
        actual = self.state()
        if actual != expected:
            raise RuntimeError("RESET FAILED: inspect teaching stack before continuing")
        self.applied = False
        if self.cancellation is not None:
            self.cancellation.touch(exist_ok=False)
        return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["development", "locked"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--edition", default="capture-v2")
    args = parser.parse_args()
    if not args.edition or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in args.edition):
        parser.error("invalid edition")
    groups = [g for g in GROUPS if g[1] == args.role]
    design = {
        "schema_version": "controlled-assistant-cases-v1",
        "role": args.role,
        "edition": args.edition,
        "canonical_window_saved_at_collection": True,
        "collector_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "groups": groups,
        "repeats_per_group": REPEATS,
        "case_count": len(groups) * REPEATS,
        "timing_seconds": {
            "settle": 5,
            "observation": 30,
            "ingestion_drain": 10,
            "recovery": 10,
        },
        "inference": "old frozen ranking; no retraining",
        "sampling_unit": "intervention_group",
        "note": "Repeated episodes are clustered, not independent systems/incidents. Go faults are deterministic 250ms/100% error; Petclinic uses bounded pause with verified unpause.",
    }
    if args.dry_run:
        print(wire(design).decode())
        return
    if args.output.exists():
        parser.error("output must be new; failed attempts are never overwritten")
    if args.role == "locked":
        if not args.freeze_manifest or not args.freeze_manifest.is_file():
            parser.error(
                "locked collection requires a prior frozen assistant configuration"
            )
        freeze = json.loads(args.freeze_manifest.read_text())
        from evaluate_assistant_cases import configuration
        if (freeze["configuration"] != configuration(role="locked") or
            freeze["collector_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
            raise ValueError("locked collector/configuration differs from freeze")
        design["freeze_manifest_sha256"] = hashlib.sha256(
            args.freeze_manifest.read_bytes()
        ).hexdigest()
    lock_path = ROOT / ".rca-private/evaluation-controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        args.output.mkdir(parents=True)
        save(args.output / "design.json", design)
        profiles = {
            "local-three": ROOT / ".rca-private/onboarding/onboarding-go3-v3-1/active",
            "petclinic": ROOT
            / ".rca-private/onboarding/onboarding-petclinic-v3-1/active",
        }
        apps = {
            system: DiagnosticApplication(ROOT, path)
            for system, path in profiles.items()
        }
        for system, app in apps.items():
            if system not in app.profiles:
                raise RuntimeError(
                    f"accepted v3 onboarding profile unavailable: {system}"
                )

        def stop(_signum, _frame):
            raise KeyboardInterrupt("controller interrupted; resetting in finally")

        signal.signal(signal.SIGTERM, stop)
        ledger = []
        for group, role, system, service, kind in groups:
            for repeat in range(1, REPEATS + 1):
                identifier = f"r2-{args.edition}-{group}-r{repeat:02d}"
                controller = Controller(system, service, kind)
                oracle = {
                    "case_id": identifier,
                    "group_id": group,
                    "system_id": system,
                    "role": role,
                    "controlled_service": service,
                    "intervention": kind,
                    "causal_scope": "controlled technical intervention; not an organizational RCA",
                    "rubric": {
                        "must_not_claim": [
                            "proven cause from correlation alone",
                            "actions already executed by assistant",
                            "sampling 100% without evidence",
                            "ML score is probability",
                        ],
                        "expected_check": "inspect the selected service and upstream/downstream call timing/errors; verify recovery",
                        "abstention_allowed_if": "the returned snapshot lacks distinguishing observations",
                        "root_hypothesis_allowed_only_with_observations": service,
                    },
                }
                try:
                    oracle["state_after_apply"] = controller.apply()
                    oracle["applied_at_unix"] = time.time()
                    time.sleep(5)
                    start = int(time.time()) + 1
                    time.sleep(31)
                    end = start + 30
                    oracle["selected_start_unix"], oracle["selected_end_unix"] = (
                        start,
                        end,
                    )
                finally:
                    oracle["state_after_reset"] = controller.reset()
                    oracle["reset_at_unix"] = time.time()
                    # A controller failure is retained even before collection.
                    save(args.output / "oracle" / f"{identifier}-control.json", oracle)
                time.sleep(10)
                app = apps[system]
                question = (
                    "Наблюдается замедление пользовательских запросов. Какие гипотезы и проверки следуют из этого интервала?"
                    if kind == "latency"
                    else "Наблюдаются сбои или таймауты пользовательских запросов. Какие гипотезы и проверки следуют из этого интервала?"
                )
                try:
                    profile = app.profiles[system]
                    window,status = collect(profile,start,end)
                    canonical_sha = save(args.output / "canonical" / f"{identifier}.json",window)
                    result = app.analyze(window,app.profile_runtimes[system],profile=profile,source_status=status)
                    if result["input_sha256"] != status["input_sha256"]:
                        raise RuntimeError("canonical input/result checksum mismatch")
                    result.update(profile_id=system,profile_version=profile.version,source_status=status)
                    catalog = app.evidence_registry.get(result["result_id"])
                    if catalog is None:
                        raise RuntimeError("missing evidence; no fabricated case")
                    case = {
                        "catalog": catalog,
                        "analysis": result,
                        "question": question,
                        "collection_status": "completed",
                        "canonical_file_sha256":canonical_sha,
                    }
                    controlled = [
                        o
                        for o in catalog["observations"]
                        if o["service"] == service and o["kind"] == "traces"
                    ]
                    oracle["controlled_trace_observations"] = controlled
                    oracle["available_observations"] = {
                        "source_status": result["source_status"],
                        "controlled_candidate_present": service in catalog["services"],
                    }
                except Exception as error:
                    # Still in the denominator. Do not retry the failed interval
                    # or replace it with a successful-looking zero-filled case.
                    case = {
                        "collection_status": "failed",
                        "error_type": type(error).__name__,
                        "question": question,
                    }
                    oracle["collection_failure"] = type(error).__name__
                input_hash = save(args.output / "input" / f"{identifier}.json", case)
                gold_hash = save(
                    args.output / "oracle" / f"{identifier}-gold.json", oracle
                )
                entry = {
                    "case_id": identifier,
                    "group_id": group,
                    "system_id": system,
                    "role": role,
                    "input_sha256": input_hash,
                    "gold_sha256": gold_hash,
                    "origin": "actual bounded intervention on isolated local acceptance stack with apply/reset readback",
                    "transmission": "approved_synthetic_to_openai",
                }
                ledger.append(entry)
                validate_ledger(ledger)
                # Append-only checkpoint, including earlier successful cases if
                # a later episode fails. No result-dependent retry or dropping.
                save(args.output / "ledger" / f"{len(ledger):03d}.json", ledger)
                print(
                    json.dumps(
                        {
                            "case_id": identifier,
                            "role": role,
                            "collection_status": case["collection_status"],
                            "completed": len(ledger),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                time.sleep(10)
        save(args.output / "ledger.json", ledger)
        save(args.output / "summary.json", validate_ledger(ledger))


if __name__ == "__main__":
    main()
