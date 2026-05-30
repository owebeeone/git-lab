"""Errors raised by diffstream model and codec validation."""

from __future__ import annotations


class DiffStreamError(Exception):
    """Base error for diffstream failures."""


class DiffStreamValidationError(DiffStreamError, ValueError):
    """Raised when a structured diff payload is malformed."""
