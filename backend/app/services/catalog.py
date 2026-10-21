"""Service catalog loading, validation, and topology queries."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CatalogError(RuntimeError):
    """Raised when the service catalog is missing or invalid."""


class ServiceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    owner: str = Field(min_length=1, max_length=120)
    team: str = Field(min_length=1, max_length=120)
    tier: Literal["critical", "high", "medium", "low"]
    environments: list[str] = Field(min_length=1, max_length=20)
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    repository: str | None = Field(default=None, max_length=200)
    runbook: str | None = Field(default=None, max_length=200)

    @field_validator("environments", "depends_on")
    @classmethod
    def dedupe_list(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in value:
            normalized = item.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    @field_validator("environments")
    @classmethod
    def validate_environments(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one environment is required")
        return value

    @model_validator(mode="after")
    def no_self_dependency(self) -> ServiceDefinition:
        if self.id in self.depends_on:
            raise ValueError(f"service '{self.id}' cannot depend on itself")
        return self


class CatalogFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    services: list[ServiceDefinition] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_graph(self) -> CatalogFile:
        ids = [service.id for service in self.services]
        if len(ids) != len(set(ids)):
            duplicates = sorted({service_id for service_id in ids if ids.count(service_id) > 1})
            raise ValueError(f"duplicate service ids: {', '.join(duplicates)}")
        known = set(ids)
        for service in self.services:
            unknown = sorted(set(service.depends_on) - known)
            if unknown:
                raise ValueError(
                    f"service '{service.id}' depends on unknown service(s): {', '.join(unknown)}"
                )
        _assert_acyclic(ids, [service.depends_on for service in self.services])
        return self


def _assert_acyclic(ids: list[str], dependencies: list[list[str]]) -> None:
    graph = dict(zip(ids, dependencies, strict=True))
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle_start = path.index(node) if node in path else 0
            cycle = " -> ".join([*path[cycle_start:], node])
            raise ValueError(f"dependency cycle detected: {cycle}")
        visiting.add(node)
        path.append(node)
        for child in graph.get(node, []):
            visit(child, path)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for service_id in ids:
        visit(service_id, [])


class Relationship(BaseModel):
    """A service reached from a focus service."""

    service_id: str
    depth: int
    path: list[str]


class Catalog:
    """Validated, read-only in-memory view of the service catalog."""

    def __init__(self, catalog_file: CatalogFile, source_path: Path) -> None:
        self._file = catalog_file
        self.source_path = source_path
        self._services = {service.id: service for service in catalog_file.services}
        self._dependents: dict[str, list[str]] = {service_id: [] for service_id in self._services}
        for service in catalog_file.services:
            for dependency in service.depends_on:
                self._dependents[dependency].append(service.id)
        for service_id in self._dependents:
            self._dependents[service_id].sort()

    @property
    def version(self) -> int:
        return self._file.version

    @property
    def services(self) -> list[ServiceDefinition]:
        return sorted(self._file.services, key=lambda item: (item.tier != "critical", item.name))

    def get(self, service_id: str) -> ServiceDefinition | None:
        return self._services.get(service_id)

    def require(self, service_id: str) -> ServiceDefinition:
        service = self.get(service_id)
        if service is None:
            raise KeyError(service_id)
        return service

    def direct_dependencies(self, service_id: str) -> list[ServiceDefinition]:
        service = self.require(service_id)
        return [self._services[item] for item in service.depends_on]

    def direct_dependents(self, service_id: str) -> list[ServiceDefinition]:
        self.require(service_id)
        return [self._services[item] for item in self._dependents.get(service_id, [])]

    def downstream(self, service_id: str, depth: int = 3) -> list[Relationship]:
        """Services the focus calls, directly or transitively."""

        return self._walk(service_id, depth=depth, upstream=False)

    def upstream(self, service_id: str, depth: int = 3) -> list[Relationship]:
        """Services that call the focus, directly or transitively."""

        return self._walk(service_id, depth=depth, upstream=True)

    def neighbors(self, service_id: str, depth: int = 1) -> set[str]:
        if self.get(service_id) is None:
            return set()
        result = {relation.service_id for relation in self.downstream(service_id, depth)}
        result.update(relation.service_id for relation in self.upstream(service_id, depth))
        return result

    def relation_to(self, focus_id: str, candidate_id: str) -> tuple[str, str] | None:
        """Return ``(relation, direction)`` for a direct relationship.

        ``dependency`` means the candidate is downstream of focus (focus calls candidate).
        ``dependent`` means the candidate is upstream of focus (candidate calls focus).
        """

        if self.get(focus_id) is None or self.get(candidate_id) is None or focus_id == candidate_id:
            return None
        if candidate_id in self.require(focus_id).depends_on:
            return ("dependency", "downstream")
        if focus_id in self.require(candidate_id).depends_on:
            return ("dependent", "upstream")
        return None

    def environments(self) -> list[str]:
        values = {
            environment for service in self._file.services for environment in service.environments
        }
        return sorted(values)

    def edges(self) -> list[tuple[str, str]]:
        return [
            (service.id, dependency)
            for service in self.services
            for dependency in sorted(service.depends_on)
        ]

    def _walk(self, service_id: str, *, depth: int, upstream: bool) -> list[Relationship]:
        self.require(service_id)
        if depth <= 0:
            return []
        adjacency = (
            self._dependents
            if upstream
            else {item.id: item.depends_on for item in self._file.services}
        )
        results: list[Relationship] = []
        seen = {service_id}
        queue: deque[tuple[str, int, list[str]]] = deque([(service_id, 0, [service_id])])
        while queue:
            current, current_depth, path = queue.popleft()
            if current_depth >= depth:
                continue
            for child in sorted(adjacency.get(current, [])):
                if child in seen:
                    continue
                seen.add(child)
                child_path = [*path, child]
                results.append(
                    Relationship(service_id=child, depth=current_depth + 1, path=child_path)
                )
                queue.append((child, current_depth + 1, child_path))
        return results


def load_catalog(path: Path) -> Catalog:
    if not path.exists():
        raise CatalogError(
            f"Service catalog not found at {path}. Set BAMBOO11Y_SERVICE_CATALOG_PATH "
            "or restore config/services.yaml."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"Could not read service catalog: {exc}") from exc
    if not isinstance(raw, dict):
        raise CatalogError("Service catalog must be a YAML mapping with a 'services' list.")
    try:
        catalog_file = CatalogFile.model_validate(raw)
    except Exception as exc:
        raise CatalogError(f"Invalid service catalog: {exc}") from exc
    return Catalog(catalog_file, source_path=path)
