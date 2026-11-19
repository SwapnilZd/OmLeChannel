"""Format selection contracts — Phase 11.

All types here describe format-selection concepts only.
They contain no production tool internals, executor factories,
provider credentials, or component catalogs.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .common import FrozenModel, Modality


class FormatSelectionMode(StrEnum):
    EXPLICIT = "explicit"
    AUTO = "auto"


class FormatSelectorStrategy(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"


class DeliveryConstraints(FrozenModel):
    """Hard and soft delivery requirements imposed by the learner or deployment context."""

    requires_interactivity: bool = False
    requires_offline_access: bool = False
    low_bandwidth_required: bool = False
    screen_free_preferred: bool = False

    captions_required: bool = False
    transcript_required: bool = False
    keyboard_navigation_required: bool = False

    maximum_delivery_minutes: int | None = None
    maximum_production_cost_usd: float | None = None
    maximum_artifact_size_mb: float | None = None

    excluded_modalities: tuple[Modality, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> DeliveryConstraints:
        if self.maximum_delivery_minutes is not None and self.maximum_delivery_minutes <= 0:
            raise ValueError("maximum_delivery_minutes must be positive")
        if self.maximum_production_cost_usd is not None and self.maximum_production_cost_usd <= 0:
            raise ValueError("maximum_production_cost_usd must be positive")
        if self.maximum_artifact_size_mb is not None and self.maximum_artifact_size_mb <= 0:
            raise ValueError("maximum_artifact_size_mb must be positive")
        if len(self.excluded_modalities) != len(set(self.excluded_modalities)):
            raise ValueError("excluded_modalities must contain unique values")
        return self


class FormatSelectionRequest(FrozenModel):
    """Request to the FormatSelectionService."""

    request_id: str = Field(min_length=1)
    blueprint_id: str = Field(min_length=1)
    mode: FormatSelectionMode
    requested_modality: Modality | None = None
    allow_fallback: bool = False
    preferred_modalities: tuple[Modality, ...] = ()
    constraints: DeliveryConstraints = Field(default_factory=DeliveryConstraints)

    @model_validator(mode="after")
    def _validate(self) -> FormatSelectionRequest:
        if self.mode == FormatSelectionMode.EXPLICIT and self.requested_modality is None:
            raise ValueError("explicit mode requires requested_modality")
        if self.mode == FormatSelectionMode.AUTO and self.requested_modality is not None:
            raise ValueError("auto mode must not specify requested_modality")
        if len(self.preferred_modalities) != len(set(self.preferred_modalities)):
            raise ValueError("preferred_modalities must contain unique values")
        overlap = set(self.preferred_modalities) & set(self.constraints.excluded_modalities)
        if overlap:
            raise ValueError(
                f"modalities cannot be both preferred and excluded: "
                f"{sorted(m.value for m in overlap)}"
            )
        if (
            self.requested_modality is not None
            and self.requested_modality in self.constraints.excluded_modalities
        ):
            raise ValueError(
                f"requested_modality '{self.requested_modality}' cannot also be excluded"
            )
        return self


class ModalityDeliveryProfile(FrozenModel):
    """Describes the delivery characteristics of one top-level modality.

    This is not the modality-affordance catalog and not a production tool catalog.
    It describes high-level learner-facing capabilities only.
    """

    modality: Modality
    enabled: bool
    description: str

    supports_interactivity: bool
    supports_offline_access: bool
    supports_low_bandwidth: bool
    supports_screen_free_delivery: bool

    supports_captions: bool
    supports_transcripts: bool
    supports_keyboard_navigation: bool

    suitable_content_signals: tuple[str, ...] = ()
    unsuitable_content_signals: tuple[str, ...] = ()

    production_cost_class: str | None = None
    generation_latency_class: str | None = None


class ModalityFeasibility(FrozenModel):
    """Result of deterministic feasibility evaluation for one modality."""

    modality: Modality
    available: bool
    feasible: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class SelectionFactor(FrozenModel):
    """One scored factor in the deterministic selection policy."""

    factor: str
    score: float
    rationale: str


class ModalityEvaluation(FrozenModel):
    """Full evaluation of a modality: feasibility + scoring factors."""

    modality: Modality
    feasible: bool
    blockers: tuple[str, ...]
    factors: tuple[SelectionFactor, ...]
    total_score: float


class FormatRecommendation(FrozenModel):
    """Structured output from the optional LLM-assisted recommender."""

    selected_modality: Modality
    rationale: str
    tradeoffs: tuple[str, ...] = ()


class SelectionBasis(StrEnum):
    EXPLICIT = "explicit"
    EXPLICIT_FALLBACK = "explicit_fallback"
    SOLE_FEASIBLE = "sole_feasible"
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    LLM_FALLBACK = "llm_fallback"


class FormatSelectionDecision(FrozenModel):
    """The auditable format-selection decision returned to callers."""

    selection_id: str
    request_id: str
    blueprint_id: str
    selected_modality: Modality
    basis: SelectionBasis
    evaluations: tuple[ModalityEvaluation, ...]
    rationale: str
    tradeoffs: tuple[str, ...] = ()
    policy_version: str
    fallback_from: Modality | None = None


class FormatSelectionTrace(FrozenModel):
    """Audit and idempotency trace for one format-selection request."""

    selection_id: str
    request_id: str
    blueprint_hash: str
    constraints_hash: str
    registry_snapshot_hash: str
    profiles_hash: str
    policy_version: str
    strategy: str
    input_hash: str
    selected_modality: Modality
    basis: SelectionBasis
    prompt_version: str | None = None
    model: str | None = None
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    llm_fallback_reason: str | None = None


class FormatSelectionResult(FrozenModel):
    """What FormatSelectionService.select_format() returns."""

    decision: FormatSelectionDecision
    trace: FormatSelectionTrace
    from_cache: bool = False
