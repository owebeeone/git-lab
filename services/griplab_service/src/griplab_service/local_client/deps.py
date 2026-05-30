"""Dependency graph scan for workspace repos."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .workspace import discover_repos


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str


@dataclass(frozen=True)
class DependencyGraph:
    repos: list[str]
    edges: list[DependencyEdge]
    errors: dict[str, str]


def get_dependency_graph(workspace_root: Path) -> DependencyGraph:
    repos = discover_repos(workspace_root)
    repo_names = {repo.name: ("" if repo == workspace_root else repo.relative_to(workspace_root).as_posix()) for repo in repos}
    present_paths = set(repo_names.values())
    edges: list[DependencyEdge] = []
    errors: dict[str, str] = {}

    for repo in repos:
        repo_path = "" if repo == workspace_root else repo.relative_to(workspace_root).as_posix()
        deps_file = repo / ".grip-lab" / "deps.json"
        if not deps_file.exists():
            continue
        try:
            payload = json.loads(deps_file.read_text(encoding="utf-8"))
            deps = payload.get("dependencies", [])
            if not isinstance(deps, list):
                raise ValueError("dependencies must be a list")
            for dep_name in deps:
                target = repo_names.get(str(dep_name))
                if target is None:
                    errors.setdefault(repo_path, f"unknown dependency: {dep_name}")
                    continue
                if target in present_paths:
                    edges.append(DependencyEdge(source=id_of(repo_path), target=id_of(target)))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors[repo_path] = str(exc)

    return DependencyGraph(
        repos=["" if repo == workspace_root else repo.relative_to(workspace_root).as_posix() for repo in repos],
        edges=edges,
        errors=errors,
    )


def id_of(repo_path: str) -> str:
    return repo_path or "root"
