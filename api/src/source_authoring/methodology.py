"""Versioned baseline requirements for the five POC2 RLO cells."""

from __future__ import annotations

from rlo_schema.v1 import BloomLevel, ContentType

from .authoring_contracts import (
    GuidancePriority,
    MethodologyGuidance,
    MethodologyProfile,
    MethodologyRequirement,
    RLOPartKind,
)


PROFILE_VERSION = "poc2-five-cell-guidance-2026-09-15-v1"

VALID_CELLS = {
    ContentType.FACT: (BloomLevel.REMEMBER,),
    ContentType.CONCEPT: (
        BloomLevel.UNDERSTAND,
        BloomLevel.APPLY,
    ),
    ContentType.PROCESS: (BloomLevel.UNDERSTAND,),
    ContentType.PROCEDURE: (BloomLevel.APPLY,),
}


_TEACH_REQUIREMENTS = {
    ContentType.FACT: (
        "State the precise fact and its scope or qualification.",
        "Explain the fact's practitioner relevance without changing its meaning.",
    ),
    ContentType.CONCEPT: (
        "Define the concept and its critical attributes.",
        "Distinguish instances from non-instances or boundary cases.",
    ),
    ContentType.PROCESS: (
        "Describe the stages, actors, transitions, and dependencies.",
        "Explain entry, exit, and material handoff conditions.",
    ),
    ContentType.PROCEDURE: (
        "Describe the learner's ordered steps and decision points.",
        "Explain entry conditions, exit conditions, common errors, and output.",
    ),
}


_PERFORMANCE_REQUIREMENTS = {
    BloomLevel.REMEMBER: "Require retrieval of the supported fact without interpretation.",
    BloomLevel.UNDERSTAND: "Require explanation, interpretation, or summarization in the learner's own terms.",
    BloomLevel.APPLY: "Require use in a novel but unambiguous practitioner situation.",
}


def _guidance(
    suffix: str,
    part: RLOPartKind,
    instruction: str,
    *,
    priority: GuidancePriority = GuidancePriority.HIGH,
    preferred_shape: dict | None = None,
    acceptable_approximation: str | None = None,
) -> MethodologyGuidance:
    return MethodologyGuidance(
        guidance_id=suffix,
        part=part,
        priority=priority,
        instruction=instruction,
        preferred_shape=preferred_shape,
        acceptable_approximation=acceptable_approximation,
    )


_PROFILE_SPECS = {
    (ContentType.FACT, BloomLevel.REMEMBER): {
        "intent": "Retrieve a precise fact from progressively weaker cues.",
        "guidance": [
            _guidance("setup-workplace-recall", RLOPartKind.SETUP, "Create a brief workplace moment where accurate recall is needed promptly."),
            _guidance("teach-precise-fact", RLOPartKind.TEACH, "State the exact fact, its scope, a useful retrieval cue, and a distinction from a commonly confused fact."),
            _guidance("show-retrieval-cue", RLOPartKind.SHOW, "Show an expert retrieving the fact in context and name the cue that triggered recall."),
            _guidance(
                "practice-cue-fading",
                RLOPartKind.PRACTICE,
                "Use repeated retrieval with progressively weaker cues and include production rather than recognition alone.",
                priority=GuidancePriority.MEDIUM,
                preferred_shape={"attempts": 3, "scaffolds": ["strong", "partial", "none"]},
                acceptable_approximation="Use fewer strong attempts when the claims cannot support credible variation, while still reducing cue support.",
            ),
            _guidance("check-recall-under-interference", RLOPartKind.CHECK, "Check recall in context with plausible interference from a related fact; do not add explanation or application demands."),
        ],
        "avoid": ["Turning recall into scenario judgment.", "Using recognition as the only learner response."],
        "review_dimensions": ["The fact is precise and scoped.", "Practice support decreases without increasing Bloom demand."],
    },
    (ContentType.CONCEPT, BloomLevel.UNDERSTAND): {
        "intent": "Contrast clear instances and non-instances using critical attributes.",
        "guidance": [
            _guidance("setup-recognition-need", RLOPartKind.SETUP, "Establish why recognizing category membership matters before action."),
            _guidance("teach-critical-attributes", RLOPartKind.TEACH, "Define critical and variable attributes and explain explicit is/is-not reasoning."),
            _guidance("show-contrastive-pair", RLOPartKind.SHOW, "Place a clear instance beside a related non-instance and name the deciding attribute."),
            _guidance(
                "practice-contrastive-progression",
                RLOPartKind.PRACTICE,
                "Progress from obvious contrasts toward a near-miss and require the deciding attribute.",
                priority=GuidancePriority.MEDIUM,
                preferred_shape={"pairs": 3},
                acceptable_approximation="Use the strongest available contrast set without inventing unsupported boundary rules.",
            ),
            _guidance("check-unseen-contrast", RLOPartKind.CHECK, "Use a fresh context and require both category membership and the deciding attribute."),
        ],
        "avoid": ["Explaining only a label or definition.", "Letting variable surface features decide membership."],
        "review_dimensions": ["Critical attributes govern classification.", "Non-instances are plausible and diagnostic."],
    },
    (ContentType.CONCEPT, BloomLevel.APPLY): {
        "intent": "Classify novel, unambiguous cases from critical attributes.",
        "guidance": [
            _guidance("setup-novel-classification", RLOPartKind.SETUP, "Present a new case requiring classification without side-by-side comparison support."),
            _guidance("teach-attribute-checklist", RLOPartKind.TEACH, "Turn critical attributes into an actionable checklist and identify irrelevant surface features."),
            _guidance("show-attribute-reasoning", RLOPartKind.SHOW, "Derive a verdict attribute by attribute from case evidence rather than resemblance."),
            _guidance(
                "practice-progressive-fading",
                RLOPartKind.PRACTICE,
                "Reduce checklist support over successive novel classification attempts.",
                priority=GuidancePriority.MEDIUM,
                preferred_shape={"attempts": 3, "scaffolds": ["full", "reduced", "none"]},
                acceptable_approximation="Use fewer distinct attempts when the source cannot support three credible cases; preserve visible scaffold reduction.",
            ),
            _guidance("check-novel-clear-case", RLOPartKind.CHECK, "Use a new unambiguous case and require the verdict and deciding attribute."),
        ],
        "avoid": ["Classifying from surface resemblance.", "Using a genuinely contested case at Apply level."],
        "review_dimensions": ["Attribute reasoning is visible.", "Support decreases without changing the objective."],
    },
    (ContentType.PROCESS, BloomLevel.UNDERSTAND): {
        "intent": "Reconstruct stages, actors, dependencies, and transition triggers.",
        "guidance": [
            _guidance("setup-process-position", RLOPartKind.SETUP, "Establish why knowing the current stage and next transition matters."),
            _guidance("teach-complete-process", RLOPartKind.TEACH, "Name and sequence stages with actors, inputs, outputs, dependencies, and transition triggers."),
            _guidance("show-missed-transition", RLOPartKind.SHOW, "Walk the process and examine one commonly missed transition and its consequence."),
            _guidance("practice-process-reconstruction", RLOPartKind.PRACTICE, "Have the learner reconstruct the flow and associate actors and triggers with stages."),
            _guidance("check-process-structure", RLOPartKind.CHECK, "Check stages, actors, and important transition logic without requiring breakdown diagnosis."),
        ],
        "avoid": ["Reducing a multi-actor process to a learner task list.", "Treating dates as transition triggers without support."],
        "review_dimensions": ["Actors and dependencies are explicit.", "Transitions are explained causally."],
    },
    (ContentType.PROCEDURE, BloomLevel.APPLY): {
        "intent": "Execute steps and decision points on a novel standard case.",
        "guidance": [
            _guidance("setup-procedure-output", RLOPartKind.SETUP, "Present a standard case requiring the procedure's intended output."),
            _guidance("teach-steps-and-rationale", RLOPartKind.TEACH, "State entry conditions, ordered steps, decision branches, rationale, common errors, exit conditions, and output."),
            _guidance("show-action-because-reason", RLOPartKind.SHOW, "Model each material action with its reason and include detection and recovery from a realistic error when supported."),
            _guidance(
                "practice-procedure-fading",
                RLOPartKind.PRACTICE,
                "Reduce support from step prompts to decision prompts to independent execution.",
                priority=GuidancePriority.MEDIUM,
                preferred_shape={"attempts": 3, "scaffolds": ["steps", "decisions", "none"]},
                acceptable_approximation="Use fewer attempts when credible case variation is limited; preserve reduced support and decision reasoning.",
            ),
            _guidance("check-independent-execution", RLOPartKind.CHECK, "Use a new standard case and assess step accuracy and decision-point reasoning."),
        ],
        "avoid": ["Presenting steps without their decision rationale.", "Requiring tailoring in a standard Apply-level case."],
        "review_dimensions": ["Execution and reasoning are both observable.", "The expected output is clear."],
    },
}


def _requirements(content_type: ContentType, bloom_level: BloomLevel):
    prefix = f"{content_type.value}-{bloom_level.value}"
    values = [
        ("cover-metadata", RLOPartKind.COVER, "Record identity, objective, cell, source, duration, and relationships.", False),
        ("setup-hook", RLOPartKind.SETUP, "Establish a practitioner moment of need and present the objective.", False),
        ("setup-prior", RLOPartKind.SETUP, "Activate only prior knowledge required by this objective.", False),
        ("teach-core-1", RLOPartKind.TEACH, _TEACH_REQUIREMENTS[content_type][0], True),
        ("teach-core-2", RLOPartKind.TEACH, _TEACH_REQUIREMENTS[content_type][1], True),
        ("show-case", RLOPartKind.SHOW, "Provide a realistic worked instance with visible expert reasoning and an outcome.", True),
        ("practice-performance", RLOPartKind.PRACTICE, _PERFORMANCE_REQUIREMENTS[bloom_level], True),
        ("practice-feedback", RLOPartKind.PRACTICE, "Provide explanatory feedback tied to the supported decision basis.", True),
        ("check-performance", RLOPartKind.CHECK, f"Assess the exact objective. {_PERFORMANCE_REQUIREMENTS[bloom_level]}", True),
        ("check-standard", RLOPartKind.CHECK, "Define a criterion-referenced correct answer or scoring standard.", True),
        ("sendoff-transfer", RLOPartKind.SEND_OFF, "Provide an on-job retrieval or transfer prompt without expanding scope.", False),
    ]
    return [
        MethodologyRequirement(
            requirement_id=f"{prefix}-{suffix}",
            part=part,
            description=description,
            substantive=substantive,
        )
        for suffix, part, description, substantive in values
    ]


PROFILES = {
    (content_type, bloom_level): MethodologyProfile(
        profile_id=f"{content_type.value}-{bloom_level.value}",
        version=PROFILE_VERSION,
        content_type=content_type,
        bloom_level=bloom_level,
        requirements=_requirements(content_type, bloom_level),
        intent=_PROFILE_SPECS[(content_type, bloom_level)]["intent"],
        guidance=_PROFILE_SPECS[(content_type, bloom_level)]["guidance"],
        avoid=_PROFILE_SPECS[(content_type, bloom_level)]["avoid"],
        review_dimensions=_PROFILE_SPECS[(content_type, bloom_level)]["review_dimensions"],
    )
    for content_type, levels in VALID_CELLS.items()
    for bloom_level in levels
}


def get_methodology_profile(
    content_type: ContentType | str,
    bloom_level: BloomLevel | str,
) -> MethodologyProfile:
    key = (ContentType(content_type), BloomLevel(bloom_level))
    try:
        return PROFILES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported RLO classification cell: {key[0].value} × {key[1].value}") from exc
