"""
Video affordance definitions — Phase 13C.

Defines the pedagogical affordance catalog for the video modality and the
corresponding production feasibility rules.

All avatar-led affordances map to ``video.avatar.render``.
The ``avatar_with_existing_visual`` affordance additionally requires
``visual_asset_available``, a virtual capability that the planning service
adds to the available-capability set when at least one approved visual asset
is present in the session.

Contains no provider credentials, HeyGen IDs, or executor internals.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality

from .catalog import ModalityAffordance, ModalityAffordanceCatalog
from .feasibility import AffordanceSupportRule, compute_producible_affordances

__all__ = [
    "AffordanceSupportRule",
    "VIDEO_AFFORDANCES",
    "VIDEO_SUPPORT_RULES",
    "ModalityAffordance",
    "ModalityAffordanceCatalog",
    "build_video_affordance_catalog",
    "compute_producible_affordances",
]

_VIDEO = Modality.VIDEO

# ── Affordance definitions ────────────────────────────────────────────────────

VIDEO_AFFORDANCES: tuple[ModalityAffordance, ...] = (
    ModalityAffordance(
        id="avatar_led_hook",
        modality=_VIDEO,
        description=(
            "An avatar delivers an engaging opening that creates relevance, "
            "curiosity, or emotional connection before instruction begins."
        ),
        pedagogical_uses=(
            "Gain attention and motivate learning",
            "Establish relevance to the learner's role",
            "Prime prior knowledge through a compelling scenario",
        ),
        suitable_narrative_roles=("hook", "orientation"),
        accessibility_notes=(
            "Avatar must be visible with sufficient contrast against background",
            "No information should be conveyed by color alone",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_orientation",
        modality=_VIDEO,
        description=(
            "An avatar introduces the learning journey — what will be covered, "
            "why it matters, and how the content is structured."
        ),
        pedagogical_uses=(
            "Set expectations for the learning session",
            "Activate prior knowledge relevant to the content",
            "Reduce cognitive load through advance organizers",
        ),
        suitable_narrative_roles=("orientation", "activate_prior_knowledge"),
        accessibility_notes=(
            "Structure should be communicated verbally, not solely through on-screen text",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_explanation",
        modality=_VIDEO,
        description=(
            "An avatar delivers a clear, direct explanation of a concept, "
            "principle, or procedure — the primary teaching mode for new material."
        ),
        pedagogical_uses=(
            "Introduce unfamiliar concepts",
            "Clarify relationships between ideas",
            "Build conceptual scaffolding before examples or practice",
        ),
        suitable_narrative_roles=("explanation", "orientation"),
        accessibility_notes=(
            "Avatar visible throughout; spoken narration is the primary channel",
            "On-screen text must meet contrast requirements if used",
        ),
    ),
    ModalityAffordance(
        id="avatar_with_existing_visual",
        modality=_VIDEO,
        description=(
            "An avatar presents alongside an approved existing visual asset "
            "(diagram, chart, or image) to support the explanation."
        ),
        pedagogical_uses=(
            "Support abstract concepts with a concrete visual reference",
            "Reduce split-attention by pairing narration with a relevant image",
            "Reference stakeholder-familiar assets to build contextual connection",
        ),
        constraints={
            "requires_existing_asset": (
                "An approved visual asset must be available; "
                "unavailable if no eligible asset exists."
            ),
        },
        suitable_narrative_roles=("explanation", "example", "application"),
        accessibility_notes=(
            "Visual must have an accessible description narrated by the avatar",
            "Important information in the visual must be spoken, not assumed visible",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_scenario",
        modality=_VIDEO,
        description=(
            "An avatar narrates a realistic workplace scenario, showing how a "
            "concept plays out in a job-relevant context."
        ),
        pedagogical_uses=(
            "Demonstrate application in a realistic setting",
            "Bridge abstract concepts to job performance",
            "Provide vicarious experience through a relatable character",
        ),
        suitable_narrative_roles=("example", "application"),
        accessibility_notes=(
            "Scenario characters and setting should be described verbally",
            "Background should not distract from the avatar narration",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_worked_example",
        modality=_VIDEO,
        description=(
            "An avatar walks through a fully solved problem or decision step by step, "
            "making the reasoning process visible."
        ),
        pedagogical_uses=(
            "Model expert problem-solving",
            "Show how rules apply to concrete cases",
            "Reduce cognitive load before independent practice",
        ),
        suitable_narrative_roles=("example", "application"),
        accessibility_notes=(
            "Each step must be narrated explicitly; do not rely on visual alone",
            "Pacing should allow the learner to follow without pausing",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_misconception_correction",
        modality=_VIDEO,
        description=(
            "An avatar names a common misconception, examines why it arises, "
            "and corrects it with clear reasoning or evidence."
        ),
        pedagogical_uses=(
            "Preemptively address predictable errors",
            "Correct prior knowledge that conflicts with the learning objective",
            "Strengthen discrimination between correct and incorrect ideas",
        ),
        suitable_narrative_roles=("explanation", "example"),
        accessibility_notes=(
            "Both the misconception and correction must be spoken clearly",
            "Visual contrast between 'wrong' and 'right' must not rely on color alone",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_reflection",
        modality=_VIDEO,
        description=(
            "An avatar prompts the learner to pause and apply a concept mentally, "
            "recall something, or consider how it relates to their own experience."
        ),
        pedagogical_uses=(
            "Activate retrieval practice",
            "Encourage active engagement between dense content sections",
            "Build metacognitive awareness",
        ),
        suitable_narrative_roles=("reflection", "practice"),
        accessibility_notes=(
            "Pause prompts should be unambiguous; the avatar should signal the wait explicitly",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_knowledge_check",
        modality=_VIDEO,
        description=(
            "An avatar poses a question and invites the learner to answer mentally "
            "before the correct answer is explained."
        ),
        pedagogical_uses=(
            "Assess recall without a written response",
            "Reinforce key facts through active retrieval",
            "Provide immediate verbal feedback in video format",
        ),
        suitable_narrative_roles=("assessment", "practice"),
        accessibility_notes=(
            "Clear question–pause–answer structure required",
            "The answer must be spoken fully, not only shown on screen",
        ),
    ),
    ModalityAffordance(
        id="avatar_led_recap",
        modality=_VIDEO,
        description=(
            "An avatar restates key concepts from the video concisely to "
            "consolidate learning and support retention."
        ),
        pedagogical_uses=(
            "Consolidate and close the video",
            "Support long-term retention through spaced review",
            "Signal topic transitions within a multi-section video",
        ),
        suitable_narrative_roles=("summary", "transition"),
        accessibility_notes=(
            "Brief and structured language is most effective",
            "Recap should not introduce new information",
        ),
    ),
)


# ── Feasibility rules ─────────────────────────────────────────────────────────
# All avatar-led affordances require video.avatar.render.
# avatar_with_existing_visual additionally requires visual_asset_available
# (a virtual capability injected by the planning service when assets exist).

_AVATAR_ONLY = ("video.avatar.render",)
_AVATAR_WITH_ASSET = ("video.avatar.render", "visual_asset_available")

VIDEO_SUPPORT_RULES: tuple[AffordanceSupportRule, ...] = (
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_hook",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_orientation",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_explanation",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_with_existing_visual",
        required_capabilities=_AVATAR_WITH_ASSET,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_scenario",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_worked_example",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_misconception_correction",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_reflection",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_knowledge_check",
        required_capabilities=_AVATAR_ONLY,
    ),
    AffordanceSupportRule(
        modality=_VIDEO,
        affordance_id="avatar_led_recap",
        required_capabilities=_AVATAR_ONLY,
    ),
)


# ── Catalog factory ───────────────────────────────────────────────────────────

def build_video_affordance_catalog() -> ModalityAffordanceCatalog:
    """Return a ModalityAffordanceCatalog pre-loaded with all video affordances."""
    return ModalityAffordanceCatalog(VIDEO_AFFORDANCES)
