"""Deterministic incident-level stratified splits and root holdouts."""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from collections.abc import Iterable


def stratified_split(
    labels: Iterable[dict],
    *,
    seed: int,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
) -> dict[str, str]:
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for label in labels:
        if label.get("incident_type") != "fault" or not label.get("localization_eligible"):
            continue
        strata[(label["root_service"], label["fault_type"])].append(label)
    assignments: dict[str, str] = {}
    for key in sorted(strata):
        values = sorted(strata[key], key=lambda item: item["incident_id"])
        derived_seed = int.from_bytes(hashlib.sha256(f"{seed}:{key}".encode()).digest()[:8], "big")
        random.Random(derived_seed).shuffle(values)
        count = len(values)
        train_count = int(count * train_fraction)
        validation_count = int(count * validation_fraction)
        if count >= 3:
            train_count = max(1, train_count)
            validation_count = max(1, validation_count)
        if train_count + validation_count >= count and count > 1:
            train_count = max(1, count - validation_count - 1)
        for index, value in enumerate(values):
            split = "train" if index < train_count else "validation" if index < train_count + validation_count else "test"
            assignments[value["incident_id"]] = split
    return assignments


def root_holdout(labels: Iterable[dict], held_out_root: str) -> tuple[list[str], list[str]]:
    train: list[str] = []
    test: list[str] = []
    for label in labels:
        if not label.get("training_eligible"):
            continue
        target = test if label.get("root_service") == held_out_root else train
        target.append(label["incident_id"])
    return sorted(train), sorted(test)


def duplicate_fingerprints_across_splits(labels: Iterable[dict], assignments: dict[str, str]) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: set[str] = set()
    for label in labels:
        incident_id = label["incident_id"]
        split = assignments.get(incident_id)
        if split is None:
            continue
        fingerprint = label["scenario_fingerprint"]
        previous = seen.setdefault(fingerprint, split)
        if previous != split:
            duplicates.add(fingerprint)
    return sorted(duplicates)
