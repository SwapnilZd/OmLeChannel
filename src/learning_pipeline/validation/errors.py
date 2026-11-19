"""Cross-contract validation error type."""

from __future__ import annotations


class CrossContractValidationError(ValueError):
    """
    Raised when a cross-contract validation check fails.

    The ``code`` attribute provides a stable, machine-readable identifier so
    tests and callers do not depend solely on prose message strings.

    Suggested codes:
        rlo_not_found
        rlo_version_mismatch
        content_reference_not_found
        content_not_selected
        duplicate_id
        missing_dependency
        dependency_cycle
        invalid_output_binding
        missing_deliverable
        unsupported_capability
        unsupported_task_type
        invalid_scene_reference
        invalid_duration
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        object_id: str | None = None,
        field: str | None = None,
    ) -> None:
        self.code = code
        self.object_id = object_id
        self.field = field
        super().__init__(message)
