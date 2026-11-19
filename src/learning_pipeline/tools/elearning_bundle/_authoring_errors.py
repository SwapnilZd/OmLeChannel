"""Typed failure categories for the bounded authoring agent."""


class AuthoringAgentError(RuntimeError):
    """Base class for controller-owned authoring failures."""


class AuthoringToolError(AuthoringAgentError):
    """A scoped deterministic tool failed unexpectedly."""


class AuthoringValidationError(AuthoringAgentError):
    """A draft could not satisfy the immutable production contract."""


class AuthoringPreflightError(AuthoringValidationError):
    """A frozen plan requests behavior its selected component cannot produce."""

    owner = "planner"
    repairability = "replan"

    def __init__(self, code: str, screen_id: str, message: str) -> None:
        self.code = code
        self.screen_id = screen_id
        super().__init__(
            f"{code} screen_id={screen_id!r} owner={self.owner} "
            f"repairability={self.repairability}: {message}"
        )


class AuthoringReviewError(AuthoringAgentError):
    """Publication review returned invalid or unresolved findings."""


class AuthoringInfrastructureError(AuthoringAgentError):
    """Checkpoint or artifact infrastructure could not be read or written."""
