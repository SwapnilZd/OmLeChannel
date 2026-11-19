"""Format selection package — Phase 11.

Public surface:

    from learning_pipeline.format_selector import (
        FormatSelectionService,
        FormatSelectionError,
        AvailableWorkflowRegistry,
        WorkflowEntry,
        build_default_registry,
        FakeFormatRecommender,
        MODALITY_PROFILES,
        SCORING_POLICY_VERSION,
    )
"""
from .feasibility import evaluate_all_feasibility, evaluate_feasibility
from .profiles import DEFAULT_PROFILES, MODALITY_PROFILES
from .recommender import (
    FakeFormatRecommender,
    FormatOutputValidationError,
    FormatRecommender,
    FormatRecommenderError,
    LiteLLMFormatRecommender,
    PROMPT_VERSION,
)
from .registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)
from .scoring import SCORING_POLICY_VERSION, score_modality, select_best
from .service import FormatSelectionError, FormatSelectionService

__all__ = [
    # service
    "FormatSelectionService",
    "FormatSelectionError",
    # registry
    "AvailableWorkflowRegistry",
    "WorkflowEntry",
    "build_default_registry",
    # profiles
    "MODALITY_PROFILES",
    "DEFAULT_PROFILES",
    # feasibility
    "evaluate_feasibility",
    "evaluate_all_feasibility",
    # scoring
    "SCORING_POLICY_VERSION",
    "score_modality",
    "select_best",
    # recommender
    "FormatRecommender",
    "FakeFormatRecommender",
    "LiteLLMFormatRecommender",
    "FormatRecommenderError",
    "FormatOutputValidationError",
    "PROMPT_VERSION",
]
