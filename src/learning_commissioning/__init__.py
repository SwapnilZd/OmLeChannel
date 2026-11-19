"""Learning-request commissioning layer.

This package owns request interpretation, RLO discovery, confirmation, and the
adapter into the existing curriculum-assembly contracts. It intentionally
remains separate from ``learning_pipeline``.
"""

from .contracts import (
    AudienceProfile,
    CandidateCurationDecision,
    CandidateCurationReview,
    CandidateCurationTrace,
    CommissioningJobRecord,
    CommissioningJobState,
    ConfirmedLearningRequest,
    ConfirmedRLOCandidate,
    ContentGap,
    ContentGapReport,
    CurationRecommendation,
    GapSeverity,
    LearningCommissionRequest,
    LearningRequestPreview,
    LearningRequestConfirmation,
    LearningSearchIntent,
    RelevanceBand,
    RLOCandidateDisposition,
    RLOCandidateMatch,
    SearchInterpretationTrace,
)

__all__ = [
    "AudienceProfile",
    "CandidateCurationDecision",
    "CandidateCurationReview",
    "CandidateCurationTrace",
    "CommissioningJobRecord",
    "CommissioningJobState",
    "ConfirmedLearningRequest",
    "ConfirmedRLOCandidate",
    "ContentGap",
    "ContentGapReport",
    "CurationRecommendation",
    "GapSeverity",
    "LearningCommissionRequest",
    "LearningRequestPreview",
    "LearningRequestConfirmation",
    "LearningSearchIntent",
    "RelevanceBand",
    "RLOCandidateDisposition",
    "RLOCandidateMatch",
    "SearchInterpretationTrace",
]
