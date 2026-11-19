"""Private internal contracts for video.manim.render bounded agent.

These models represent intermediate work inside ManimGenerationController.
They are NOT public tool boundaries — callers use AnimationBrief and
ManimVideoOutput from elearning_bundle/contracts.py.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from learning_pipeline.contracts.common import FrozenModel


# ── Manim component binding sub-models ────────────────────────────────────────
# All use FrozenModel (extra="forbid") so the JSON schema includes
# additionalProperties: false — required for responses.parse() strict mode.


class ManimListItem(FrozenModel):
    label: str | None = None
    detail: str | None = None
    narration: str | None = None


class ManimPairItem(FrozenModel):
    """Covers two_column pairs (left/right) and myth_vs_reality pairs."""
    left: str | None = None
    right: str | None = None
    narration: str | None = None
    misconception: str | None = None
    myth_narration: str | None = None
    correction: str | None = None
    correction_narration: str | None = None


class ManimCalloutItem(FrozenModel):
    label: str
    narration: str | None = None


class ManimActionItem(FrozenModel):
    type: str | None = None
    file: str | None = None
    rank: int | None = None
    color: str | None = None
    to_file: str | None = None
    to_rank: int | None = None


class ManimStepItem(FrozenModel):
    """A `steps` entry — label/detail for process_flow and cycle,
    actions for chess_board. Each template's validate() reads only
    the fields it defines."""
    label: str | None = None
    detail: str | None = None
    narration: str | None = None
    actions: list[ManimActionItem] | None = None


class ManimAttributeItem(FrozenModel):
    """definition template attribute rows."""
    key: str | None = None
    value: str | None = None
    narration: str | None = None


class ManimEventItem(FrozenModel):
    """timeline template events."""
    date: str | None = None
    label: str | None = None
    narration: str | None = None


class ManimPieceItem(FrozenModel):
    symbol: str | None = None
    file: str | None = None
    rank: int | None = None
    color: str | None = None


class ManimComponentBindings(FrozenModel):
    """All possible component binding fields across all 12 Manim templates.

    FrozenModel (extra="forbid") generates additionalProperties: false throughout,
    which is required for OpenAI responses.parse() structured-output strict mode.
    A template whose bindings this model cannot express is a template the LLM
    cannot draft — tests/tools/manim_video/test_templates.py locks coverage
    against the template registry.
    """
    # Common
    scene_narration: str | None = None
    closing_narration: str | None = None
    title: str | None = None
    # vertical_stack
    items: list[ManimListItem] | None = None
    # two_column
    left_header: str | None = None
    right_header: str | None = None
    pairs: list[ManimPairItem] | None = None  # also myth_vs_reality
    # central_callouts
    center_label: str | None = None
    center_narration: str | None = None
    callouts: list[ManimCalloutItem] | None = None
    # scenario
    setup: str | None = None
    setup_narration: str | None = None
    question: str | None = None
    question_narration: str | None = None
    wrong_answer: str | None = None
    wrong_narration: str | None = None
    correct_answer: str | None = None
    correct_narration: str | None = None
    # chess_board / process_flow / cycle
    initial_pieces: list[ManimPieceItem] | None = None
    steps: list[ManimStepItem] | None = None
    # definition
    term: str | None = None
    definition: str | None = None
    definition_narration: str | None = None
    attributes: list[ManimAttributeItem] | None = None
    # pyramid
    levels: list[ManimCalloutItem] | None = None
    # timeline
    events: list[ManimEventItem] | None = None
    # quadrant
    x_low: str | None = None
    x_high: str | None = None
    y_low: str | None = None
    y_high: str | None = None
    tl_label: str | None = None
    tl_items: list[str] | None = None
    tl_narration: str | None = None
    tr_label: str | None = None
    tr_items: list[str] | None = None
    tr_narration: str | None = None
    bl_label: str | None = None
    bl_items: list[str] | None = None
    bl_narration: str | None = None
    br_label: str | None = None
    br_items: list[str] | None = None
    br_narration: str | None = None


class ManimSceneDraft(FrozenModel):
    """Structured output from the Manim LLM agent.

    The agent produces this instead of prose + arbitrary code.
    The controller validates it before narration generation or rendering.
    """

    scene_id: str
    source_scene_ids: tuple[str, ...]
    template_id: str | None = None
    template_version: str | None = None
    visual_summary: str
    component_bindings: ManimComponentBindings = Field(default_factory=ManimComponentBindings)
    generated_source: str | None = None
    estimated_duration_seconds: float

    @field_validator("scene_id", "visual_summary")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be blank")
        return v

    @field_validator("source_scene_ids")
    @classmethod
    def _non_empty_scenes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("source_scene_ids must not be empty")
        return v

    @field_validator("estimated_duration_seconds")
    @classmethod
    def _positive_duration(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("estimated_duration_seconds must be positive")
        return v

    @model_validator(mode="after")
    def _template_or_source(self) -> "ManimSceneDraft":
        if self.template_id is None and self.generated_source is None:
            raise ValueError(
                "ManimSceneDraft must provide either template_id or generated_source"
            )
        return self


class ManimRenderPolicy(FrozenModel):
    """Manim-specific render bounds.

    Separate from AgenticExecutionPolicy because these settings are
    renderer-specific and do not apply to general LLM-authoring tasks.
    """

    max_render_attempts: int = Field(3, ge=1)
    render_timeout_seconds: int = Field(300, ge=30)
    duration_tolerance_seconds: float = Field(10.0, ge=0.0)


class ManimRenderRequest(FrozenModel):
    """Canonical manifest sent from the controller to the render runner."""

    job_id: str
    idempotency_key: str
    scene_class: str
    source_code: str
    quality: str = "medium_quality"
    expected_duration_seconds: float | None = None
    workflow_id: str | None = None
    task_id: str | None = None


class ManimRenderResult(FrozenModel):
    """Canonical result returned from the render runner to the controller."""

    status: Literal["success", "failure"]
    video_bytes: bytes | None = None
    captions_bytes: bytes | None = None
    log_bytes: bytes = b""
    failure_category: str | None = None
    failure_message: str | None = None
    duration_seconds: float | None = None
    has_audio: bool | None = None

    model_config = {"frozen": True, "extra": "forbid", "arbitrary_types_allowed": True}


class ManimTrace(FrozenModel):
    """Structured trace persisted after each Manim render job.

    Written to the artifact store; referenced via ManimVideoOutput.trace_uri.
    """

    workflow_id: str
    task_id: str
    animation_id: str
    idempotency_key: str
    prompt_version: str
    model: str

    model_call_count: int = Field(..., ge=0)
    repair_attempt_count: int = Field(..., ge=0)
    render_attempt_count: int = Field(..., ge=0)

    template_id: str | None = None
    template_version: str | None = None
    source_generated: bool = False
    source_repaired: bool = False

    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None

    checkpoint_stages_reused: tuple[str, ...] = ()
    source_scene_ids: tuple[str, ...]
    duration_seconds: float | None = None

    validation_warnings: tuple[str, ...] = ()


# ── Manim-specific errors ──────────────────────────────────────────────────────


class ManimError(RuntimeError):
    """Base class for all Manim executor errors."""


class ManimPolicyError(ManimError):
    """Policy limit (calls, cost, timeout) exceeded."""


class ManimRepairBudgetError(ManimError):
    """Repair budget exhausted without a successful render."""


class ManimSourcePolicyError(ManimError):
    """Generated source failed the safety policy check."""


class ManimBindingValidationError(ManimError):
    """Template bindings failed validation (e.g. a narration word budget).

    Raised before any render; the controller routes it through the bounded
    LLM repair loop rather than failing the task outright.
    """


class ManimInfrastructureError(ManimError):
    """Render infrastructure failure (container, timeout, OOM)."""


class ManimRenderError(ManimError):
    """Render failure not classified as source or infrastructure error."""


class ManimMediaValidationError(ManimError):
    """Produced media failed validation (bad MP4, invalid captions)."""
