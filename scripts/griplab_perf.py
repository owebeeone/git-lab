#!/usr/bin/env python3
"""Fetch grip-lab service timing diagnostics over the websocket protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

try:
    from aiohttp import ClientSession
except ImportError as exc:  # pragma: no cover - exercised manually by environment.
    raise SystemExit("aiohttp is required; run with `uv run --with aiohttp python scripts/griplab_perf.py ...`") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:3140/ws", help="service websocket URL")
    parser.add_argument("--target", help="route debug.perf.get to a peer through the hub")
    parser.add_argument("--limit", type=int, default=120, help="maximum events to return")
    parser.add_argument("--clear", action="store_true", help="clear timings instead of reading them")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    method = "debug.perf.clear" if args.clear else "debug.perf.get"
    payload: dict[str, Any] = {} if args.clear else {"limit": args.limit}
    if args.target:
        method_payload = {
            "targetPeerId": args.target,
            "method": method,
            "payload": payload,
        }
        method = "hub.route.request"
        payload = method_payload

    async with ClientSession() as session:
        async with session.ws_connect(args.url) as ws:
            await ws.send_json({
                "messageId": "perf000001",
                "kind": "request",
                "method": method,
                "payload": payload,
            })
            response = await ws.receive_json(timeout=10)
            print(json.dumps(response, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
