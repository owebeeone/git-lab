"""Dependency graph scan for workspace repos."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
    repo_paths = {repo: ("" if repo == workspace_root else repo.relative_to(workspace_root).as_posix()) for repo in repos}
    name_index = build_name_index(workspace_root, repos)
    path_index = {repo.resolve(): path for repo, path in repo_paths.items()}
    edges: set[DependencyEdge] = set()
    errors: dict[str, str] = {}

    for repo in repos:
        repo_path = repo_paths[repo]
        source = id_of(repo_path)
        add_manifest_edges(workspace_root, repo, source, name_index, path_index, edges)
        add_explicit_edges(repo, repo_path, source, name_index, edges, errors)

    return DependencyGraph(
        repos=list(repo_paths.values()),
        edges=sorted(edges, key=lambda edge: (edge.source, edge.target)),
        errors=errors,
    )


def build_name_index(workspace_root: Path, repos: Iterable[Path]) -> dict[str, str]:
    index: dict[str, str] = {}
    for repo in repos:
        repo_path = "" if repo == workspace_root else repo.relative_to(workspace_root).as_posix()
        names = {repo.name}
        package_name = read_package_name(repo)
        if package_name:
            names.add(package_name)
        project_name = read_pyproject_name(repo)
        if project_name:
            names.add(project_name)
        for name in names:
            add_name(index, name, repo_path)
    return index


def add_name(index: dict[str, str], name: str, repo_path: str) -> None:
    index.setdefault(name, repo_path)
    index.setdefault(normalize_name(name), repo_path)


def add_manifest_edges(
    workspace_root: Path,
    repo: Path,
    source: str,
    name_index: dict[str, str],
    path_index: dict[Path, str],
    edges: set[DependencyEdge],
) -> None:
    for dep_name, dep_spec in read_package_dependencies(repo):
        target = name_index.get(dep_name) or name_index.get(normalize_name(dep_name))
        if target is None:
            target = resolve_path_dependency(repo, workspace_root, path_index, dep_spec)
        if target is not None:
            add_edge(edges, source, target)

    for dep_name in read_pyproject_dependencies(repo):
        target = name_index.get(dep_name) or name_index.get(normalize_name(dep_name))
        if target is not None:
            add_edge(edges, source, target)

    for dep_name, dep_spec in read_uv_sources(repo):
        target = name_index.get(dep_name) or name_index.get(normalize_name(dep_name))
        if target is None:
            target = resolve_path_dependency(repo, workspace_root, path_index, dep_spec)
        if target is not None:
            add_edge(edges, source, target)


def add_explicit_edges(
    repo: Path,
    repo_path: str,
    source: str,
    name_index: dict[str, str],
    edges: set[DependencyEdge],
    errors: dict[str, str],
) -> None:
    deps_file = repo / ".grip-lab" / "deps.json"
    if not deps_file.exists():
        return
    try:
        payload = json.loads(deps_file.read_text(encoding="utf-8"))
        deps = payload.get("dependencies", [])
        if not isinstance(deps, list):
            raise ValueError("dependencies must be a list")
        for dep_name in deps:
            dep_key = str(dep_name)
            target = name_index.get(dep_key) or name_index.get(normalize_name(dep_key))
            if target is None:
                errors.setdefault(repo_path, f"unknown dependency: {dep_name}")
                continue
            add_edge(edges, source, target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors[repo_path] = str(exc)


def add_edge(edges: set[DependencyEdge], source: str, target_path: str) -> None:
    target = id_of(target_path)
    if source != target:
        edges.add(DependencyEdge(source=source, target=target))


def read_package_name(repo: Path) -> str | None:
    package = read_json_object(repo / "package.json")
    if not package:
        return None
    name = package.get("name")
    return name if isinstance(name, str) and name else None


def read_package_dependencies(repo: Path) -> list[tuple[str, str]]:
    package = read_json_object(repo / "package.json")
    if not package:
        return []
    deps: list[tuple[str, str]] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = package.get(section)
        if not isinstance(value, dict):
            continue
        for dep_name, dep_spec in value.items():
            deps.append((str(dep_name), str(dep_spec)))
    return deps


def read_json_object(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_pyproject_name(repo: Path) -> str | None:
    pyproject = read_toml_object(repo / "pyproject.toml")
    if not pyproject:
        return None
    project = pyproject.get("project")
    if not isinstance(project, dict):
        return None
    name = project.get("name")
    return name if isinstance(name, str) and name else None


def read_pyproject_dependencies(repo: Path) -> list[str]:
    pyproject = read_toml_object(repo / "pyproject.toml")
    if not pyproject:
        return []
    project = pyproject.get("project")
    if not isinstance(project, dict):
        return []
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return []
    names: list[str] = []
    for requirement in dependencies:
        if not isinstance(requirement, str):
            continue
        name = requirement_name(requirement)
        if name:
            names.append(name)
    return names


def read_uv_sources(repo: Path) -> list[tuple[str, str]]:
    pyproject = read_toml_object(repo / "pyproject.toml")
    if not pyproject:
        return []
    tool = pyproject.get("tool")
    if not isinstance(tool, dict):
        return []
    uv = tool.get("uv")
    if not isinstance(uv, dict):
        return []
    sources = uv.get("sources")
    if not isinstance(sources, dict):
        return []
    deps: list[tuple[str, str]] = []
    for dep_name, source in sources.items():
        if isinstance(source, dict):
            path = source.get("path")
            if isinstance(path, str):
                deps.append((str(dep_name), path))
    return deps


def read_toml_object(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def resolve_path_dependency(
    repo: Path,
    workspace_root: Path,
    path_index: dict[Path, str],
    dep_spec: str,
) -> str | None:
    spec = strip_path_scheme(dep_spec)
    if spec is None:
        return None
    dep_path = (repo / spec).resolve()
    try:
        dep_path.relative_to(workspace_root.resolve())
    except ValueError:
        return None
    return path_index.get(dep_path)


def strip_path_scheme(dep_spec: str) -> str | None:
    spec = dep_spec.strip()
    matched_scheme = False
    for prefix in ("file:", "link:", "workspace:"):
        if spec.startswith(prefix):
            spec = spec.removeprefix(prefix)
            matched_scheme = True
            break
    if not matched_scheme and not (spec.startswith(".") or spec.startswith("/")):
        return None
    if spec in ("", "*", "^", "~"):
        return None
    return spec


def requirement_name(requirement: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return match.group(1) if match else None


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def id_of(repo_path: str) -> str:
    return repo_path or "root"
