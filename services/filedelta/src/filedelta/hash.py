"""Hash helpers for protocol payload validation."""

from __future__ import annotations

from hashlib import sha256


def hash_bytes(data: bytes) -> str:
    """Return the protocol hash for a byte payload."""

    return "sha256:" + sha256(data).hexdigest()
