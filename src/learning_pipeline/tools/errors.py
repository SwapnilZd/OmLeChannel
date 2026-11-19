"""Error types for production tool registration and runtime execution."""
from __future__ import annotations


class DuplicateCapabilityError(ValueError):
    """Raised when the same capability name is registered twice."""

    def __init__(self, capability: str) -> None:
        super().__init__(f"Capability already registered: {capability!r}")
        self.capability = capability


class DuplicateTaskTypeError(ValueError):
    """Raised when the same task type is already claimed by another capability."""

    def __init__(self, task_type: str) -> None:
        super().__init__(f"Task type already registered: {task_type!r}")
        self.task_type = task_type


class UnsupportedCapabilityError(KeyError):
    """Raised when a requested capability is not in the catalog."""

    def __init__(self, capability: str) -> None:
        super().__init__(capability)
        self.capability = capability


class InvalidToolRegistrationError(ValueError):
    """Raised when a tool definition is structurally invalid."""


class InvalidToolInputError(ValueError):
    """Raised when an executor receives inputs that fail contract validation."""


class InvalidToolOutputError(ValueError):
    """Raised when an executor produces outputs that fail contract validation."""


class MissingRealModeConfigError(RuntimeError):
    """Raised at startup when required real-mode configuration is absent."""
