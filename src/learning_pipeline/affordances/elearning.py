"""E-learning affordance catalog — Phase 14E (expanded from Phase 14D).

Twelve pedagogical affordances for e-learning:

  Static (require only elearning.course.author + elearning.bundle.assemble):
    elearning.orientation           — welcome/course overview
    elearning.objective_preview     — learning objectives display
    elearning.static_explanation    — authored concept explanation
    elearning.guided_example        — worked example with narration
    elearning.guided_practice       — scaffolded application exercise
    elearning.knowledge_check       — inline formative check
    elearning.assessment            — scored knowledge assessment
    elearning.reflection            — metacognitive prompt
    elearning.summary               — consolidation/close

  Avatar (require elearning.course.author + video.avatar.render):
    elearning.avatar_framing        — avatar presenter for orientation/motivation
    elearning.avatar_explanation    — avatar-led concept explanation

  Manim animated (require elearning.course.author + video.manim.render):
    elearning.animated_demonstration — process/transformation animation
    elearning.animated_explanation  — abstract concept visualization

Production capability requirements:
  static affordances require only elearning.course.author.
  avatar affordances also require video.avatar.render.
  animated affordances also require video.manim.render.

Note: elearning.bundle.assemble is a baseline requirement for the entire modality
(enforced in the format_selector registry), not per-affordance.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality

from .catalog import ModalityAffordance, ModalityAffordanceCatalog
from .feasibility import AffordanceSupportRule

# ── Capability IDs exposed in this catalog ─────────────────────────────────────

CAP_ELEARNING_AUTHOR = "elearning.course.author"
CAP_AVATAR_RENDER = "video.avatar.render"
CAP_MANIM_RENDER = "video.manim.render"

# ── Affordance definitions ─────────────────────────────────────────────────────

_ELEARNING_AFFORDANCES = (
    # ── Static affordances ────────────────────────────────────────────────────
    ModalityAffordance(
        id="elearning.orientation",
        modality=Modality.ELEARNING,
        description=(
            "Authored welcome and course-overview screens that establish context, "
            "purpose, and relevance before instruction begins. No video is produced."
        ),
        pedagogical_uses=(
            "course welcome and introduction",
            "establishing learner relevance",
            "setting expectations",
            "activating prior knowledge framing",
        ),
        suitable_narrative_roles=("orientation", "hook", "transition"),
        accessibility_notes=(
            "All images must have alt text.",
            "Contrast ratios must meet WCAG AA.",
        ),
    ),
    ModalityAffordance(
        id="elearning.objective_preview",
        modality=Modality.ELEARNING,
        description=(
            "Authored screens that display learning objectives and success criteria "
            "so learners know what they will be able to do by the end of the course."
        ),
        pedagogical_uses=(
            "making learning goals explicit",
            "orienting the learner before content",
            "activating prior knowledge",
        ),
        suitable_narrative_roles=("orientation", "activate_prior_knowledge"),
        accessibility_notes=(
            "Objective lists should use semantic HTML list markup.",
            "Contrast ratios must meet WCAG AA.",
        ),
    ),
    ModalityAffordance(
        id="elearning.static_explanation",
        modality=Modality.ELEARNING,
        description=(
            "Authored text and media screens that explain a concept, rule, or process. "
            "No video is produced; the learner reads and interacts with static content."
        ),
        pedagogical_uses=(
            "concept introduction",
            "rule explanation",
            "process overview",
            "fact presentation",
        ),
        suitable_narrative_roles=(
            "explanation",
            "orientation",
            "transition",
            "summary",
        ),
        accessibility_notes=(
            "All images must have alt text.",
            "Contrast ratios must meet WCAG AA.",
        ),
    ),
    ModalityAffordance(
        id="elearning.guided_example",
        modality=Modality.ELEARNING,
        description=(
            "Authored screens that walk through a fully solved problem or realistic "
            "scenario step-by-step, making expert reasoning visible to the learner."
        ),
        pedagogical_uses=(
            "modelling expert problem-solving",
            "showing how rules apply to concrete cases",
            "reducing cognitive load before independent practice",
            "worked example with self-explanation prompts",
        ),
        suitable_narrative_roles=("example", "application", "explanation"),
        accessibility_notes=(
            "Step-by-step structure should use semantic heading hierarchy.",
            "All diagrams must have descriptive alt text.",
        ),
    ),
    ModalityAffordance(
        id="elearning.guided_practice",
        modality=Modality.ELEARNING,
        description=(
            "Authored interactive screens that walk the learner through applying a skill "
            "or procedure, with feedback at each step."
        ),
        pedagogical_uses=(
            "step-by-step skill building",
            "procedure rehearsal",
            "scaffolded application",
        ),
        suitable_narrative_roles=("application", "practice", "example"),
        accessibility_notes=(
            "All interactions must be keyboard-accessible.",
            "Error feedback must be programmatically associated with the control.",
        ),
    ),
    ModalityAffordance(
        id="elearning.knowledge_check",
        modality=Modality.ELEARNING,
        description=(
            "Authored inline formative check screens with one or two questions and "
            "immediate explanatory feedback. Low-stakes; not scored toward completion."
        ),
        pedagogical_uses=(
            "inline comprehension check after explanation",
            "retrieval practice within a module",
            "identifying and correcting misconceptions",
        ),
        suitable_narrative_roles=("assessment", "practice", "reflection"),
        accessibility_notes=(
            "All response options must be reachable via keyboard.",
            "Feedback messages must be announced to screen readers.",
        ),
    ),
    ModalityAffordance(
        id="elearning.assessment",
        modality=Modality.ELEARNING,
        description=(
            "Authored knowledge-check screens with questions and scored feedback. "
            "Supports multiple-choice, true/false, and matching question types. "
            "Used for formal module or course-level assessment."
        ),
        pedagogical_uses=(
            "formative knowledge check",
            "summative assessment",
            "self-assessment",
        ),
        suitable_narrative_roles=("assessment", "reflection"),
        accessibility_notes=(
            "All response options must be reachable via keyboard.",
            "Feedback messages must be announced to screen readers.",
        ),
    ),
    ModalityAffordance(
        id="elearning.reflection",
        modality=Modality.ELEARNING,
        description=(
            "Authored metacognitive prompt screens that invite the learner to connect "
            "new knowledge to their own role, experience, or prior understanding."
        ),
        pedagogical_uses=(
            "metacognitive consolidation",
            "connecting learning to role context",
            "deepening retention through self-explanation",
            "transfer preparation",
        ),
        suitable_narrative_roles=("reflection", "summary", "application"),
        accessibility_notes=(
            "Open-ended prompts should not require text input if not supported.",
            "All interactions must be keyboard-accessible.",
        ),
    ),
    ModalityAffordance(
        id="elearning.summary",
        modality=Modality.ELEARNING,
        description=(
            "Authored consolidation screens that restate key concepts and next steps, "
            "closing the module and supporting long-term retention."
        ),
        pedagogical_uses=(
            "concept consolidation and close",
            "reinforcing key takeaways",
            "signalling course or module completion",
        ),
        suitable_narrative_roles=("summary", "transition"),
        accessibility_notes=(
            "Summary structure should use semantic heading hierarchy.",
            "Contrast ratios must meet WCAG AA.",
        ),
    ),
    # ── Avatar affordances ────────────────────────────────────────────────────
    ModalityAffordance(
        id="elearning.avatar_framing",
        modality=Modality.ELEARNING,
        description=(
            "Authored screens plus one avatar-presenter video slot used for orientation, "
            "motivation, or major topic transitions. The avatar establishes human presence "
            "and role relevance. Treat it as a brief presenter interlude that introduces or "
            "connects authored instruction, not as the primary vehicle for dense content."
        ),
        pedagogical_uses=(
            "course or module welcome with human presence",
            "establishing role relevance and motivation",
            "major concept transition with instructor framing",
            "closing encouragement and next-steps",
        ),
        suitable_narrative_roles=(
            "hook",
            "orientation",
            "transition",
            "reflection",
            "summary",
        ),
        accessibility_notes=(
            "Avatar video must include captions.",
            "Narration script must be complete and accurate.",
        ),
    ),
    ModalityAffordance(
        id="elearning.avatar_explanation",
        modality=Modality.ELEARNING,
        description=(
            "Authored screens plus one avatar-presenter video slot. "
            "An AI avatar gives a brief, personable setup for one concept while authored "
            "screens carry the substantive explanation and learner action."
        ),
        pedagogical_uses=(
            "personable concept explanation",
            "instructor-style delivery",
            "emotional engagement",
            "narrative hook",
        ),
        suitable_narrative_roles=(
            "explanation",
            "hook",
            "activate_prior_knowledge",
            "reflection",
        ),
        accessibility_notes=(
            "Avatar video must include captions.",
            "Narration script must be complete and accurate.",
        ),
    ),
    # ── Manim animated affordances ────────────────────────────────────────────
    ModalityAffordance(
        id="elearning.animated_demonstration",
        modality=Modality.ELEARNING,
        description=(
            "Authored screens plus one Manim-animated video slot showing a process, "
            "transformation, or multi-step procedure over time. Use when movement, "
            "sequencing, spatial relationships, or progressive construction materially "
            "improves understanding."
        ),
        pedagogical_uses=(
            "process changing over time",
            "system or data flow visualisation",
            "multi-step procedure demonstration",
            "progressive construction of a framework, matrix, or worked answer",
            "relationships that become clearer as parts are placed or connected",
        ),
        suitable_narrative_roles=("example", "application", "explanation"),
        accessibility_notes=(
            "Animation must include narration or captions.",
            "Key visual transitions must be described in narration.",
        ),
    ),
    ModalityAffordance(
        id="elearning.animated_explanation",
        modality=Modality.ELEARNING,
        description=(
            "Authored screens plus one Manim-animated video slot. "
            "Progressive visual builds explain abstract concepts and structured business "
            "frameworks. Best for mapped relationships, comparisons, hierarchies, data "
            "flows, algorithms, and conceptual visualizations."
        ),
        pedagogical_uses=(
            "abstract concept visualization",
            "structured business framework visualization",
            "matrix, quadrant, or relationship mapping",
            "algorithm or process animation",
            "data-driven explanation",
            "mathematical illustration",
        ),
        suitable_narrative_roles=("explanation", "example", "application"),
        accessibility_notes=(
            "Animation must include narration or captions.",
            "Key visual transitions must be described in narration.",
        ),
    ),
)

# ── Support rules ──────────────────────────────────────────────────────────────

_STATIC_CAP = (CAP_ELEARNING_AUTHOR,)
_AVATAR_CAPS = (CAP_ELEARNING_AUTHOR, CAP_AVATAR_RENDER)
_MANIM_CAPS = (CAP_ELEARNING_AUTHOR, CAP_MANIM_RENDER)

ELEARNING_SUPPORT_RULES: tuple[AffordanceSupportRule, ...] = (
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.orientation",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.objective_preview",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.static_explanation",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.guided_example",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.guided_practice",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.knowledge_check",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.assessment",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.reflection",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.summary",
        required_capabilities=_STATIC_CAP,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.avatar_framing",
        required_capabilities=_AVATAR_CAPS,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.avatar_explanation",
        required_capabilities=_AVATAR_CAPS,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.animated_demonstration",
        required_capabilities=_MANIM_CAPS,
    ),
    AffordanceSupportRule(
        modality=Modality.ELEARNING,
        affordance_id="elearning.animated_explanation",
        required_capabilities=_MANIM_CAPS,
    ),
)


def build_elearning_affordance_catalog() -> ModalityAffordanceCatalog:
    """Return a ModalityAffordanceCatalog populated with all e-learning affordances."""
    return ModalityAffordanceCatalog(_ELEARNING_AFFORDANCES)
