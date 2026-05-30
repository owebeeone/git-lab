"""Workspace tree snapshots and watchdog-backed change notifications."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from griplab_service.local_client.workspace import discover_repos

DEFAULT_TREE_IGNORE_NAMES = frozenset({
    ".git",
    ".grip-lab",
    ".grip-lab-hub",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "venv",
})


@dataclass(frozen=True)
class TreeEntry:
    repo_path: str
    path: str
    kind: str
    size: int | None = None
    mtime_ms: int | None = None


@dataclass(frozen=True)
class TreeSnapshot:
    version: str
    entries: list[TreeEntry]


def build_tree_snapshot(workspace_root: Path, ignore_names: frozenset[str] = DEFAULT_TREE_IGNORE_NAMES) -> TreeSnapshot:
    entries: list[TreeEntry] = []
    for repo in discover_repos(workspace_root):
        entries.extend(scan_repo_tree(workspace_root, repo, ignore_names))
    entries.sort(key=lambda item: (item.repo_path, item.path, item.kind))
    version = tree_version(entries)
    return TreeSnapshot(version=version, entries=entries)


def scan_repo_tree(workspace_root: Path, repo: Path, ignore_names: frozenset[str]) -> list[TreeEntry]:
    repo_path = "" if repo == workspace_root else repo.relative_to(workspace_root).as_posix()
    entries: list[TreeEntry] = []
    for root, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(name for name in dirnames if name not in ignore_names)
        root_path = Path(root)
        for filename in sorted(filenames):
            if filename in ignore_names:
                continue
            path = root_path / filename
            if has_ignored_part(path.relative_to(repo), ignore_names):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(TreeEntry(
                repo_path=repo_path,
                path=path.relative_to(repo).as_posix(),
                kind="file",
                size=stat.st_size,
                mtime_ms=int(stat.st_mtime * 1000),
            ))
    return entries


def tree_snapshot_payload(workspace_root: Path) -> dict[str, object]:
    return tree_snapshot_to_json(build_tree_snapshot(workspace_root))


def tree_snapshot_to_json(snapshot: TreeSnapshot) -> dict[str, object]:
    return {
        "version": snapshot.version,
        "entries": [tree_entry_to_json(entry) for entry in snapshot.entries],
    }


def tree_entry_to_json(entry: TreeEntry) -> dict[str, object]:
    return {
        "repoPath": entry.repo_path,
        "path": entry.path,
        "kind": entry.kind,
        "size": entry.size,
        "mtimeMs": entry.mtime_ms,
    }


def tree_version(entries: list[TreeEntry]) -> str:
    payload = [
        {
            "repoPath": entry.repo_path,
            "path": entry.path,
            "kind": entry.kind,
            "size": entry.size,
            "mtimeMs": entry.mtime_ms,
        }
        for entry in entries
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def has_ignored_part(path: Path, ignore_names: frozenset[str] = DEFAULT_TREE_IGNORE_NAMES) -> bool:
    return any(part in ignore_names for part in path.parts)


class TreeChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        workspace_root: Path,
        ignore_names: frozenset[str],
        notify: Callable[[], None],
    ) -> None:
        self.workspace_root = workspace_root
        self.ignore_names = ignore_names
        self.notify = notify

    def on_any_event(self, event: FileSystemEvent) -> None:
        paths = [Path(event.src_path)]
        dest_path = getattr(event, "dest_path", "")
        if dest_path:
            paths.append(Path(dest_path))
        if all(self._is_ignored(path) for path in paths):
            return
        self.notify()

    def _is_ignored(self, path: Path) -> bool:
        try:
            rel = path.resolve().relative_to(self.workspace_root)
        except ValueError:
            return True
        return has_ignored_part(rel, self.ignore_names)


class TreeWatcher:
    """Bridge watchdog callbacks into an asyncio loop."""

    def __init__(
        self,
        workspace_root: Path,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[None],
        ignore_names: frozenset[str] = DEFAULT_TREE_IGNORE_NAMES,
        observer_factory: Callable[[], BaseObserver] = Observer,
    ) -> None:
        self.workspace_root = workspace_root
        self.loop = loop
        self.queue = queue
        self.ignore_names = ignore_names
        self.observer = observer_factory()
        self.handler = TreeChangeHandler(workspace_root, ignore_names, self._notify)
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self.observer.schedule(self.handler, str(self.workspace_root), recursive=True)
        self.observer.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self.observer.stop()
        self.observer.join(timeout=2)
        self._running = False

    def _notify(self) -> None:
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)
