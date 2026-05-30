"""Data-driven git workspace builder for service integration tests."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Sequence

RepoKind = Literal["react", "pyproject"]


@dataclass(frozen=True)
class BuiltWorkspace:
    workspace_root: Path
    root_repo: Path
    repos: dict[str, Path]


@dataclass(frozen=True)
class RepoSpec:
    name: str
    kind: RepoKind
    dependencies: tuple[str, ...] = ()
    files: dict[str, str] = field(default_factory=dict)
    dirty_files: dict[str, str] = field(default_factory=dict)
    untracked_files: dict[str, str] = field(default_factory=dict)

    def dep(self, *names: str) -> "RepoSpec":
        return replace(self, dependencies=self.dependencies + tuple(names))

    def file(self, path: str, content: str) -> "RepoSpec":
        return replace(self, files={**self.files, path: content})

    def dirty(self, path: str, content: str) -> "RepoSpec":
        return replace(self, dirty_files={**self.dirty_files, path: content})

    def untracked(self, path: str, content: str) -> "RepoSpec":
        return replace(self, untracked_files={**self.untracked_files, path: content})

    def build(self, workspace_root: Path, *, git: Path | str = "git") -> Path:
        repo = workspace_root / self.name
        repo.mkdir(parents=True)
        self._write_project_files(repo)
        for path, content in self.files.items():
            write_text(repo / path, content)
        init_git_repo(repo, git=git)
        for path, content in self.dirty_files.items():
            write_text(repo / path, content)
        for path, content in self.untracked_files.items():
            write_text(repo / path, content)
        return repo

    def _write_project_files(self, repo: Path) -> None:
        write_text(repo / "README.md", f"# {self.name}\n")
        write_text(repo / ".grip-lab" / "deps.json", json.dumps({
            "name": self.name,
            "kind": self.kind,
            "dependencies": list(self.dependencies),
        }, indent=2) + "\n")
        if self.kind == "react":
            self._write_react_project(repo)
        elif self.kind == "pyproject":
            self._write_pyproject(repo)
        else:
            raise ValueError(f"unsupported repo kind: {self.kind}")

    def _write_react_project(self, repo: Path) -> None:
        deps = {name: f"file:../{name}" for name in self.dependencies}
        package = {
            "name": self.name,
            "private": True,
            "version": "0.0.0",
            "type": "module",
            "dependencies": deps,
            "devDependencies": {
                "typescript": "^5.0.0",
                "vite": "^7.0.0",
            },
        }
        write_text(repo / "package.json", json.dumps(package, indent=2) + "\n")
        write_text(repo / "src" / "index.ts", f"export const name = {self.name!r};\n")

    def _write_pyproject(self, repo: Path) -> None:
        module = python_module_name(self.name)
        write_text(repo / "pyproject.toml", "\n".join([
            "[build-system]",
            'requires = ["setuptools>=69"]',
            'build-backend = "setuptools.build_meta"',
            "",
            "[project]",
            f'name = "{self.name}"',
            'version = "0.0.0"',
            'requires-python = ">=3.11"',
            "dependencies = [",
            *[f'  "{name} @ file:../{name}",' for name in self.dependencies],
            "]",
            "",
        ]))
        write_text(repo / "src" / module / "__init__.py", f'"""Test package for {self.name}."""\n')


@dataclass(frozen=True)
class RepoDefinition:
    repos: tuple[RepoSpec, ...]

    def __init__(self, *repos: RepoSpec) -> None:
        if not repos:
            raise ValueError("RepoDefinition requires at least one repo")
        names = [repo.name for repo in repos]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate repo names: {', '.join(duplicates)}")
        object.__setattr__(self, "repos", tuple(repos))

    def build(self, workspace_root: Path | str, *, git: Path | str = "git") -> BuiltWorkspace:
        root = Path(workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        repo_paths = {repo.name: repo.build(root, git=git) for repo in self.repos}
        return BuiltWorkspace(
            workspace_root=root,
            root_repo=repo_paths[self.repos[0].name],
            repos=repo_paths,
        )


def react_repo(name: str) -> RepoSpec:
    return RepoSpec(name=name, kind="react")


def pyproj_repo(name: str) -> RepoSpec:
    return RepoSpec(name=name, kind="pyproject")


CLASSIC = RepoDefinition(
    react_repo("test-grip-core"),
    react_repo("test-grip-react").dep("test-grip-core"),
    react_repo("test-grip-react-demo").dep("test-grip-react"),
    pyproj_repo("test-grip-py"),
)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def init_git_repo(repo: Path, *, git: Path | str = "git") -> None:
    run([str(git), "-C", str(repo), "init", "-q"])
    run([str(git), "-C", str(repo), "config", "user.email", "test@example.invalid"])
    run([str(git), "-C", str(repo), "config", "user.name", "SSH Fixture"])
    run([str(git), "-C", str(repo), "add", "."])
    run([str(git), "-C", str(repo), "commit", "-q", "-m", "init"])


def run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=10, check=True)


def python_module_name(name: str) -> str:
    module = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if module and module[0].isdigit():
        module = f"_{module}"
    return module
