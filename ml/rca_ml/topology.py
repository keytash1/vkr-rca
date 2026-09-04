"""Versioned topology metadata for controlled M8A benchmark systems."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .generate import RCAClient


@dataclass(frozen=True)
class BenchmarkTopology:
    topology_id: str
    name: str
    compose_file: str
    compose_project: str
    entry_service: str
    entry_url: str
    rca_url: str
    services: dict[str, str]
    edges: tuple[tuple[str, str], ...]

    @classmethod
    def load(cls, path: str | Path) -> "BenchmarkTopology":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        topology = cls(
            topology_id=str(payload["topology_id"]),
            name=str(payload["name"]),
            compose_file=str(payload["compose_file"]),
            compose_project=str(payload["compose_project"]),
            entry_service=str(payload["entry_service"]),
            entry_url=str(payload["entry_url"]),
            rca_url=str(payload["rca_url"]),
            services={str(key): str(value) for key, value in payload["services"].items()},
            edges=tuple((str(source), str(target)) for source, target in payload["edges"]),
        )
        topology.validate()
        return topology

    def validate(self) -> None:
        if self.topology_id not in {"B", "C"}:
            raise ValueError("M8A benchmark topology must be B or C")
        if self.entry_service not in self.services:
            raise ValueError("entry service is missing")
        if len(self.services) < 5:
            raise ValueError("benchmark topology needs at least five services")
        if set(self.services) & {"gateway", "orders", "payment"}:
            raise ValueError("M8A service names must differ from topology A")
        if len(set(self.edges)) != len(self.edges):
            raise ValueError("duplicate topology edge")
        for source, target in self.edges:
            if source not in self.services or target not in self.services or source == target:
                raise ValueError(f"invalid edge {source!r}->{target!r}")
        self._topological_order()

    def client(self) -> RCAClient:
        return RCAClient(
            self.entry_url,
            rca=self.rca_url,
            fault_urls=self.services,
            work_path="/work",
        )

    def ancestors(self, service: str) -> list[str]:
        reverse: dict[str, set[str]] = {name: set() for name in self.services}
        for source, target in self.edges:
            reverse[target].add(source)
        reached = {service}
        pending = [service]
        while pending:
            current = pending.pop()
            for parent in reverse[current]:
                if parent not in reached:
                    reached.add(parent)
                    pending.append(parent)
        return sorted(reached)

    def descendants(self, service: str) -> list[str]:
        forward: dict[str, set[str]] = {name: set() for name in self.services}
        for source, target in self.edges:
            forward[source].add(target)
        reached = {service}
        pending = [service]
        while pending:
            current = pending.pop()
            for child in forward[current]:
                if child not in reached:
                    reached.add(child)
                    pending.append(child)
        return sorted(reached)

    def _topological_order(self) -> list[str]:
        indegree = {service: 0 for service in self.services}
        forward = {service: [] for service in self.services}
        for source, target in self.edges:
            forward[source].append(target)
            indegree[target] += 1
        pending = sorted(service for service, count in indegree.items() if count == 0)
        result = []
        while pending:
            service = pending.pop(0)
            result.append(service)
            for target in sorted(forward[service]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    pending.append(target)
                    pending.sort()
        if len(result) != len(self.services):
            raise ValueError("benchmark topology must be acyclic")
        return result
