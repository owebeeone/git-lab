"""Persistent JSON chat store for service and hub chat streams."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

LINK_KINDS = {"file", "repo", "peer", "session", "state"}


class ChatStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._counter = 0
        self.subscribers: set[Any] = set()

    def messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            with path.open("r", encoding="utf-8") as f:
                messages.append(validate_message(json.load(f)))
        return sorted(messages, key=lambda item: str(item["id"]))

    def post(self, payload: dict[str, Any], *, default_sender_id: str) -> dict[str, Any]:
        sender_id = clean_text(payload.get("senderId"), default_sender_id)
        ts = int(payload.get("ts", int(time.time() * 1000)))
        text = clean_text(payload.get("text"), "")
        links = validate_links(list(payload.get("links", [])))
        if not text.strip() and not links:
            raise ValueError("chat.post requires text or links")
        self._counter += 1
        message = {
            "id": f"{ts:013d}-{safe_id(sender_id)}-{self._counter:06d}",
            "senderId": sender_id,
            "ts": ts,
            "text": text,
            "links": links,
        }
        self._write(message)
        self.publish()
        return message

    def add_subscriber(self, queue: Any) -> None:
        self.subscribers.add(queue)

    def remove_subscriber(self, queue: Any) -> None:
        self.subscribers.discard(queue)

    def publish(self) -> None:
        for queue in list(self.subscribers):
            queue.put_nowait(None)

    def _write(self, message: dict[str, Any]) -> None:
        path = self.root / f"{message['id']}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(message, f, sort_keys=True, separators=(",", ":"))
            f.write("\n")


def chat_store_root(config_path: Path | None, workspace_root: Path) -> Path:
    if config_path is not None:
        return config_path.parent / ".grip-lab" / "chat"
    return workspace_root / ".grip-lab" / "chat"


def validate_message(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("chat message must be an object")
    message = {
        "id": clean_text(value.get("id"), ""),
        "senderId": clean_text(value.get("senderId"), ""),
        "ts": int(value.get("ts", 0)),
        "text": clean_text(value.get("text"), ""),
        "links": validate_links(list(value.get("links", []))),
    }
    if not message["id"]:
        raise ValueError("chat message id must not be empty")
    if not message["senderId"]:
        raise ValueError("chat senderId must not be empty")
    return message


def validate_links(values: list[Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("chat links must be objects")
        kind = clean_text(item.get("kind"), "")
        if kind not in LINK_KINDS:
            raise ValueError(f"unsupported chat link kind: {kind}")
        link = {
            "kind": kind,
            "label": clean_text(item.get("label"), ""),
            "target": clean_text(item.get("target"), ""),
        }
        peer_id = item.get("peerId")
        if peer_id is not None:
            link["peerId"] = clean_text(peer_id, "")
        if not link["label"] or not link["target"]:
            raise ValueError("chat links require label and target")
        links.append(link)
    return links


def clean_text(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value) or "peer"
