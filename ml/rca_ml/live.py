"""Six deterministic live scenarios for the selected offline model."""

from __future__ import annotations

import time
from collections import Counter

from .generate import GenerationConfig, RCAClient, prepare_incident, wait_for_samples
from .predict import predict_snapshot


def run_live_scenarios(model, client: RCAClient, config: GenerationConfig) -> list[dict]:
    cases = [
        ("gateway", "latency", 700),
        ("orders", "latency", 700),
        ("payment", "latency", 700),
        ("gateway", "error", 1.0),
        ("orders", "error", 1.0),
        ("payment", "error", 1.0),
    ]
    results = []
    required_by_root = {
        "gateway": ["gateway"],
        "orders": ["gateway", "orders"],
        "payment": ["gateway", "orders", "payment"],
    }
    for root, fault_type, value in cases:
        scenario = f"{root}-{fault_type}"
        prepare_incident(client, config)
        if fault_type == "latency":
            client.set_fault(root, latency_ms=int(value))
        else:
            client.set_fault(root, error_rate=float(value))
        statuses = Counter(client.send_traffic(f"m7-live-{scenario}", config.requests_per_incident, config.concurrency))
        required = ["gateway", "orders", "payment"] if fault_type == "latency" else required_by_root[root]
        def top_up(cycle: int) -> None:
            statuses.update(client.send_traffic(f"m7-live-{scenario}-topup-{cycle}", 5, 5))

        top_up_cycles = wait_for_samples(
            client,
            required,
            config.requests_per_incident,
            config,
            top_up=top_up,
        )
        if fault_type == "error":
            time.sleep(config.collector_settle_seconds)
        snapshot = client.get_json(f"{client.rca}/api/features")
        prediction = predict_snapshot(model, snapshot)
        truth_rank = next(
            (candidate["rank"] for candidate in prediction["ranking"] if candidate["service"] == root),
            0,
        )
        results.append(
            {
                "scenario": scenario,
                "root_service": root,
                "fault_type": fault_type,
                "fault_value": value,
                "http_status_counts": dict(sorted(statuses.items())),
                "top_up_cycles": top_up_cycles,
                "state": snapshot.get("state"),
                "ready_universe": snapshot.get("ready_universe", []),
                "ranking": prediction["ranking"],
                "truth_rank": truth_rank,
            }
        )
    client.reset_faults()
    return results
