"""Self-contained synthetic operator profile for experiment-free unit tests."""


def profile_document():
    return {
        "id": "synthetic",
        "title": "Synthetic test only",
        "version": "1",
        "candidate_services": ["api", "worker"],
        "artifact_dir": "deploy/profiles/artifacts/synthetic",
        "metrics": {
            "url": "http://127.0.0.1:1",
            "service_label": "service",
            "query_step_seconds": 2,
            "queries": {name: name for name in ("cpu", "memory", "network", "traffic_rate")},
        },
        "traces": {"url": "http://127.0.0.1:1", "query_services": ["api"]},
        "workload": {"prometheus_query": "synthetic_request_rate"},
    }
