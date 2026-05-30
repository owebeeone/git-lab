"""Workspace repo discovery and git status collection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence

ChangeKind = Literal["modified", "added", "deleted", "untracked", "renamed"]


@dataclass(frozen=True)
class ChangedFile:
    path: str
    change: ChangeKind


@dataclass(frozen=True)
class RepoStatus:
    path: str
    name: str
    branch: str
    head: str
    ahead: int
    behind: int
    dirty: bool
    changed_files: list[ChangedFile] = field(default_factory=list)
    error: str | None = None


def discover_repos(workspace_root: Path) -> list[Path]:
    """Discover the root repo plus one-level child repos."""

    repos: list[Path] = []
    if (workspace_root / ".git").exists():
        repos.append(workspace_root)
    for child in sorted(workspace_root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / ".git").exists():
            repos.append(child)
    return repos


def collect_workspace_status(workspace_root: Path, *, git: Path | str = "git") -> list[RepoStatus]:
    statuses: list[RepoStatus] = []
    for repo in discover_repos(workspace_root):
        repo_path = "" if repo == workspace_root else repo.relative_to(workspace_root).as_posix()
        statuses.append(collect_repo_status(workspace_root, repo_path, git=git))
    return statuses


def collect_repo_status(workspace_root: Path, repo_path: str, *, git: Path | str = "git") -> RepoStatus:
    repo = workspace_root / repo_path if repo_path else workspace_root
    name = repo.name
    try:
        branch = run_git(repo, ["branch", "--show-current"], git=git).stdout.strip() or "detached"
        head = run_git(repo, ["rev-parse", "--short", "HEAD"], git=git).stdout.strip()
        porcelain = run_git(repo, ["status", "--porcelain=v1", "--branch"], git=git).stdout.splitlines()
        ahead, behind = parse_ahead_behind(porcelain[0] if porcelain else "")
        changed = [parse_changed_file(line) for line in porcelain[1:] if line.strip()]
        return RepoStatus(
            path=repo_path,
            name=name,
            branch=branch,
            head=head,
            ahead=ahead,
            behind=behind,
            dirty=bool(changed),
            changed_files=changed,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return RepoStatus(
            path=repo_path,
            name=name,
            branch="unknown",
            head="unknown",
            ahead=0,
            behind=0,
            dirty=False,
            error=str(exc),
        )


def parse_ahead_behind(line: str) -> tuple[int, int]:
    ahead = 0
    behind = 0
    marker = "..."
    if marker not in line:
        return ahead, behind
    if "ahead " in line:
        ahead = int(line.split("ahead ", 1)[1].split(",", 1)[0].split("]", 1)[0])
    if "behind " in line:
        behind = int(line.split("behind ", 1)[1].split(",", 1)[0].split("]", 1)[0])
    return ahead, behind


def parse_changed_file(line: str) -> ChangedFile:
    status = line[:2]
    raw_path = line[3:]
    path = raw_path.split(" -> ", 1)[-1]
    if status == "??":
        change: ChangeKind = "untracked"
    elif "R" in status:
        change = "renamed"
    elif "A" in status:
        change = "added"
    elif "D" in status:
        change = "deleted"
    else:
        change = "modified"
    return ChangedFile(path=path, change=change)


def run_git(repo: Path, args: Sequence[str], *, git: Path | str = "git") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(git), "-C", str(repo), *args],
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
