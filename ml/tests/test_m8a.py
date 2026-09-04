from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rca_ml.dataset import write_jsonl
from rca_ml.fixtures import fixture_topology_dataset
from rca_ml.m8a_evaluate import evaluate_topology, feature_distribution_shift, system_holdout_matrix
from rca_ml.m8a_generate import M8AGenerationConfig, _segments, scenarios
from rca_ml.topology import BenchmarkTopology
from rca_ml.train import load_model


REPOSITORY = Path(__file__).resolve().parents[2]
MODEL = REPOSITORY / "ml/models/m7-lambdamart-v1/model.json"


class M8ATests(unittest.TestCase):
    def test_topologies_are_unseen_acyclic_structures(self) -> None:
        topology_b = BenchmarkTopology.load(REPOSITORY / "deploy/m8a/topology-b.json")
        topology_c = BenchmarkTopology.load(REPOSITORY / "deploy/m8a/topology-c.json")
        self.assertEqual(topology_b.ancestors("billing"), ["billing", "fulfillment", "portal"])
        self.assertNotIn("catalog", topology_b.ancestors("billing"))
        self.assertEqual(topology_c.ancestors("journal"), ["checkout", "entry", "journal", "settlement", "warehouse"])
        self.assertGreaterEqual(len(topology_c.services), 6)

    def test_scenario_counts_and_temporal_segments(self) -> None:
        topology = BenchmarkTopology.load(REPOSITORY / "deploy/m8a/topology-b.json")
        config = M8AGenerationConfig(incidents_per_pair=2, healthy_controls=3, stability_scenarios=4)
        values = scenarios(topology, config)
        self.assertEqual(sum(value["experiment_kind"] == "zero_shot" for value in values), 23)
        self.assertEqual(sum(value["experiment_kind"] == "temporal" for value in values), 50)
        self.assertEqual(sum(value["experiment_kind"] == "stability" for value in values), 20)
        for profile in ("step_early", "step_late", "ramp", "intermittent", "burst"):
            scenario = {"temporal_profile": profile}
            self.assertEqual(sum(segment[2] for segment in _segments(scenario, 20)), 20)

    def test_zero_shot_and_system_holdout_pipeline(self) -> None:
        systems = {
            "A": (("a0", "a1", "a2"), (("a0", "a1"), ("a1", "a2"))),
            "B": (("b0", "b1", "b2", "b3", "b4"), (("b0", "b1"), ("b1", "b2"), ("b0", "b3"), ("b3", "b4"))),
            "C": (("c0", "c1", "c2", "c3", "c4", "c5"), (("c0", "c1"), ("c1", "c2"), ("c1", "c3"), ("c2", "c4"), ("c3", "c4"), ("c1", "c5"))),
        }
        datasets = {
            system: fixture_topology_dataset(system, services, edges)
            for system, (services, edges) in systems.items()
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            b_directory = root / "b"
            b_directory.mkdir()
            write_jsonl(b_directory / "features.jsonl", datasets["B"][0])
            write_jsonl(b_directory / "labels.jsonl", datasets["B"][1])
            (b_directory / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "fixture-b",
                        "topology": {"id": "B", "name": "fixture", "services": list(systems["B"][0]), "edges": [list(value) for value in systems["B"][1]], "entry_service": "b0"},
                        "frozen_model": {"version": "m7-lambdamart-v1", "sha256": "fixture"},
                    }
                ),
                encoding="utf-8",
            )
            result = evaluate_topology(b_directory, load_model(MODEL), seed=7)
            self.assertEqual(result["counts"]["zero_shot_fault_incidents"], 30)
            self.assertIn(result["transfer_status"], {"STRONG_TRANSFER", "PARTIAL_TRANSFER", "FAILED_TRANSFER"})
            holdouts = system_holdout_matrix(
                datasets,
                MODEL,
                root / "models",
                selected_parameters={"max_depth": 2, "eta": 0.1, "min_child_weight": 1, "subsample": 0.8, "colsample_bytree": 0.8},
                rounds=1,
                seed=7,
            )
            self.assertEqual(set(holdouts), {"A", "B", "C"})
            shift = feature_distribution_shift(datasets)
            self.assertEqual(len(shift["largest_shifts"]), 9)


if __name__ == "__main__":
    unittest.main()
