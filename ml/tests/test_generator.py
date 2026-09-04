from __future__ import annotations

import unittest

from rca_ml.generate import GenerationConfig, prepare_incident, scenarios


class FakeClient:
    def __init__(self) -> None:
        self.reset_fault_calls = 0
        self.reset_current_calls = 0
        self.polls = 0

    def reset_faults(self) -> None:
        self.reset_fault_calls += 1

    def reset_current(self) -> None:
        self.reset_current_calls += 1

    def get_json(self, _url: str) -> dict:
        self.polls += 1
        if self.polls == 1:
            return {"operations": [{"current_samples": 1}]}
        return {"operations": [{"current_samples": 0}]}

    rca = "http://fake"


class GeneratorTests(unittest.TestCase):
    def test_drain_barrier_repeats_reset_after_late_batch(self) -> None:
        client = FakeClient()
        resets = prepare_incident(client, GenerationConfig(drain_seconds=0, poll_interval_seconds=0))
        self.assertEqual(resets, 2)
        self.assertEqual(client.reset_current_calls, 2)

    def test_scenario_distribution_and_seed_are_deterministic(self) -> None:
        config = GenerationConfig(incidents_per_pair=4, healthy_controls=2, seed=99)
        first = scenarios(config)
        self.assertEqual(first, scenarios(config))
        self.assertEqual(sum(value["incident_type"] == "fault" for value in first), 24)
        self.assertEqual(sum(value["incident_type"] == "healthy" for value in first), 2)
        self.assertEqual(len({value["scenario_fingerprint"] for value in first}), len(first))


if __name__ == "__main__":
    unittest.main()
