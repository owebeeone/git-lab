"""Exception types for filedelta validation and apply failures."""


class FiledeltaError(Exception):
    """Base class for filedelta errors."""


class DeltaValidationError(FiledeltaError, ValueError):
    """A delta or byte op is structurally invalid."""


class DeltaApplyError(FiledeltaError):
    """A structurally valid delta cannot be applied to the target bytes."""

