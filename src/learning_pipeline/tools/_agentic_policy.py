"""Shared agentic execution policy for bounded AI agent tasks.

Both elearning.course.author and video.manim.render use this policy
to enforce call, cost, and repair limits within a single task. Provider-call
timeouts and retries are owned centrally by LiteLLM; ``timeout_seconds`` is
retained for contract compatibility and non-provider operations only.

Do not create per-capability duplicates — import from here.
"""
from __future__ import annotations

from pydantic import Field

from learning_pipeline.contracts.common import FrozenModel


class AgenticExecutionPolicy(FrozenModel):
    """Bounds on a bounded AI agent's execution within a single task.

    All loops must check these limits. Exceeding any limit fails the
    task rather than looping indefinitely.
    """

    max_model_calls: int = Field(3, ge=1)
    max_internal_tool_calls: int = Field(12, ge=0)
    max_fitting_attempts: int = Field(2, ge=1)
    max_repair_attempts: int = Field(2, ge=0)
    timeout_seconds: int = Field(120, ge=10)

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cost_usd: float | None = None
