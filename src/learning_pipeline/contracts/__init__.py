"""
Learning pipeline domain contracts.

All public contracts are re-exported here so that consumers can write:

    from learning_pipeline.contracts import RLODocument, CourseBlueprint, ...

Internal modules may import directly from sub-modules when they need only
a narrow subset and want to avoid pulling in unrelated types.
"""

from __future__ import annotations

from .assembly import CourseBlueprint, RLOContentSelection, TailoredRLORef
from .common import (
    PROFICIENCY_ORDER,
    ContentDepth,
    FrozenModel,
    InputBinding,
    ListInput,
    LiteralInput,
    Modality,
    ObjectInput,
    TaskOutputInput,
    TopicProficiency,
)
from .execution import BuildPlan, TaskResult, TaskSpec, WorkflowResult
from .planning import (
    AvatarMediaDirective,
    ElearningProductionDraft,
    ManimMediaDirective,
    ModalityCoverageReport,
    ModalityPlanningContext,
    ModalityPlanningResult,
    ModalityPlanningTrace,
    NarrativeRole,
    OmittedScene,
    PlanningTrace,
    PodcastModalityDraft,
    PodcastProductionDraft,
    PodcastSceneDraft,
    PodcastSpeechSegmentDraft,
    ResolvedContentItem,
    ResolvedPlanningContext,
    ResolvedRLOContext,
    ResolvedSceneContext,
    StructuredPlanningResponse,
    WorkflowPlanningResult,
)
from .learner import LearnerContext
from .modality import ModalityPlan, ModalityScene, PresentationCapability, RLOContentRef
from .production import ModalityProductionPlan, ProductionJob
from .curriculum_assembly import (
    AssemblyPlanningTrace,
    AssemblyRLOCandidate,
    CourseAssemblyConstraints,
    CourseAssemblyDraft,
    CourseAssemblyReport,
    CourseAssemblyRequest,
    CourseAssemblyResult,
    OmittedRLODecision,
    PrerequisiteBridge,
    RLOAssemblyContext,
    RLOAssemblyDecision,
    TailoredRLODraft,
)
from .format_selection import (
    DeliveryConstraints,
    FormatRecommendation,
    FormatSelectionDecision,
    FormatSelectionMode,
    FormatSelectionRequest,
    FormatSelectionResult,
    FormatSelectionTrace,
    FormatSelectorStrategy,
    ModalityDeliveryProfile,
    ModalityEvaluation,
    ModalityFeasibility,
    SelectionBasis,
    SelectionFactor,
)
from .rlo import (
    Accessibility,
    AssessmentItem,
    AssessmentOption,
    Concept,
    ContentTypeRecommendation,
    DesignBrief,
    EnablingObjective,
    Evidence,
    GagneEventMapping,
    Governance,
    InstructionalComponent,
    Misconception,
    RLODocument,
    Source,
)

__all__ = [
    # common
    "FrozenModel",
    "Modality",
    "TopicProficiency",
    "ContentDepth",
    "PROFICIENCY_ORDER",
    "LiteralInput",
    "TaskOutputInput",
    "ListInput",
    "ObjectInput",
    "InputBinding",
    # rlo
    "Source",
    "Misconception",
    "EnablingObjective",
    "Evidence",
    "Concept",
    "InstructionalComponent",
    "AssessmentOption",
    "AssessmentItem",
    "DesignBrief",
    "GagneEventMapping",
    "ContentTypeRecommendation",
    "Governance",
    "Accessibility",
    "RLODocument",
    # learner
    "LearnerContext",
    # assembly
    "RLOContentSelection",
    "TailoredRLORef",
    "CourseBlueprint",
    # modality
    "PresentationCapability",
    "RLOContentRef",
    "ModalityScene",
    "ModalityPlan",
    # production
    "ProductionJob",
    "ModalityProductionPlan",
    # execution
    "TaskSpec",
    "BuildPlan",
    "TaskResult",
    "WorkflowResult",
    # planning (Phase 14D)
    "AvatarMediaDirective",
    "ManimMediaDirective",
    "ElearningProductionDraft",
    # planning (Phase 9)
    "ResolvedContentItem",
    "ResolvedSceneContext",
    "ResolvedPlanningContext",
    "PodcastSpeechSegmentDraft",
    "OmittedScene",
    "PodcastProductionDraft",
    "StructuredPlanningResponse",
    "PlanningTrace",
    "WorkflowPlanningResult",
    # planning (Phase 10)
    "NarrativeRole",
    "PodcastSceneDraft",
    "PodcastModalityDraft",
    "ResolvedRLOContext",
    "ModalityPlanningContext",
    "ModalityCoverageReport",
    "ModalityPlanningTrace",
    "ModalityPlanningResult",
    # curriculum assembly (Phase 12)
    "AssemblyRLOCandidate",
    "CourseAssemblyConstraints",
    "CourseAssemblyRequest",
    "RLOAssemblyContext",
    "TailoredRLODraft",
    "OmittedRLODecision",
    "PrerequisiteBridge",
    "CourseAssemblyDraft",
    "RLOAssemblyDecision",
    "CourseAssemblyReport",
    "AssemblyPlanningTrace",
    "CourseAssemblyResult",
    # format selection (Phase 11)
    "FormatSelectionMode",
    "FormatSelectorStrategy",
    "DeliveryConstraints",
    "FormatSelectionRequest",
    "ModalityDeliveryProfile",
    "ModalityFeasibility",
    "SelectionFactor",
    "ModalityEvaluation",
    "FormatRecommendation",
    "SelectionBasis",
    "FormatSelectionDecision",
    "FormatSelectionTrace",
    "FormatSelectionResult",
]
