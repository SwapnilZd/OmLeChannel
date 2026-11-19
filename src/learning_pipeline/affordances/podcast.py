"""
Podcast affordance definitions — Phase 10.

Defines the pedagogical affordance catalog for the podcast modality and the
corresponding production feasibility rules.  All affordances map to
``speech.synthesize`` + ``audio.assemble`` for the current tool set.

Contains no provider credentials, TTS model details, or executor internals.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality

from .catalog import ModalityAffordance, ModalityAffordanceCatalog
from .feasibility import AffordanceSupportRule, compute_producible_affordances

__all__ = [
    "AffordanceSupportRule",
    "PODCAST_AFFORDANCES",
    "PODCAST_SUPPORT_RULES",
    "ModalityAffordance",
    "ModalityAffordanceCatalog",
    "build_podcast_affordance_catalog",
    "compute_producible_affordances",
]

_PODCAST = Modality.PODCAST

# ── Affordance definitions ────────────────────────────────────────────────────

PODCAST_AFFORDANCES: tuple[ModalityAffordance, ...] = (
    ModalityAffordance(
        id="guided_explanation",
        modality=_PODCAST,
        description=(
            "Expert explains a concept step-by-step while the Host guides "
            "the explanation with concise questions and clarification."
        ),
        pedagogical_uses=(
            "Introduce unfamiliar concepts",
            "Clarify relationships between ideas",
            "Build conceptual scaffolding before examples",
        ),
        suitable_narrative_roles=("explanation", "orientation", "activate_prior_knowledge"),
        accessibility_notes=("Spoken content; no visual required",),
    ),
    ModalityAffordance(
        id="host_expert_dialogue",
        modality=_PODCAST,
        description=(
            "Host and Expert exchange perspectives in structured dialogue, "
            "exploring a concept from complementary angles."
        ),
        pedagogical_uses=(
            "Explore a concept from multiple angles",
            "Show how experts reason about problems",
            "Model analytical thinking",
        ),
        suitable_narrative_roles=("explanation", "example", "application"),
        accessibility_notes=("Distinct voices improve comprehension for auditory learners",),
    ),
    ModalityAffordance(
        id="misconception_correction",
        modality=_PODCAST,
        description=(
            "A common misconception is named, examined, and corrected with "
            "clear evidence or reasoning."
        ),
        pedagogical_uses=(
            "Preemptively address predictable errors",
            "Correct prior knowledge that conflicts with the RLO",
            "Strengthen discrimination between correct and incorrect ideas",
        ),
        suitable_narrative_roles=("explanation", "example"),
        accessibility_notes=("Explicit statement of both error and correction aids retention",),
    ),
    ModalityAffordance(
        id="guided_reflection_dialogue",
        modality=_PODCAST,
        description=(
            "Expert asks the Host to connect or apply a concept; the Host "
            "responds as the learner proxy and the Expert develops the insight."
        ),
        pedagogical_uses=(
            "Model reflective application entirely through dialogue",
            "Connect dense content sections through dialogue",
            "Make metacognitive reasoning audible",
        ),
        suitable_narrative_roles=("reflection", "practice"),
        accessibility_notes=("The full reflection must be expressed in the dialogue",),
    ),
    ModalityAffordance(
        id="scenario_walkthrough",
        modality=_PODCAST,
        description=(
            "A realistic workplace scenario is narrated and analysed, "
            "showing how a concept plays out in context."
        ),
        pedagogical_uses=(
            "Demonstrate application in a realistic setting",
            "Bridge abstract concepts to job performance",
            "Provide vicarious experience",
        ),
        suitable_narrative_roles=("example", "application"),
        accessibility_notes=("Vivid scenario language supports mental imagery without visuals",),
    ),
    ModalityAffordance(
        id="spoken_hook",
        modality=_PODCAST,
        description=(
            "An engaging opening that creates relevance, curiosity, or "
            "emotional connection before instruction begins."
        ),
        pedagogical_uses=(
            "Gain attention and motivate learning",
            "Establish relevance to the learner's role",
            "Prime prior knowledge",
        ),
        suitable_narrative_roles=("hook", "orientation"),
        accessibility_notes=("Should not rely on visuals; attention gained through narrative alone",),
    ),
    ModalityAffordance(
        id="spoken_knowledge_check",
        modality=_PODCAST,
        description=(
            "Expert asks the Host an assigned knowledge-check question; the "
            "Host answers as the learner proxy before the Expert gives feedback."
        ),
        pedagogical_uses=(
            "Model how a learner works through a knowledge check",
            "Reinforce key facts through an audible question-and-answer exchange",
            "Provide immediate Expert feedback in audio format",
        ),
        suitable_narrative_roles=("assessment", "practice"),
        accessibility_notes=("Clear Expert–Host–Expert exchange required",),
    ),
    ModalityAffordance(
        id="summary_recap",
        modality=_PODCAST,
        description=(
            "Key concepts from the episode are restated concisely to "
            "consolidate learning and support retention."
        ),
        pedagogical_uses=(
            "Consolidate and close the episode",
            "Support long-term retention through spaced review",
            "Signal topic transitions",
        ),
        suitable_narrative_roles=("summary", "transition"),
        accessibility_notes=("Brief and structured language is most effective",),
    ),
    ModalityAffordance(
        id="worked_example",
        modality=_PODCAST,
        description=(
            "A fully solved problem or decision is narrated step-by-step, "
            "making the reasoning visible."
        ),
        pedagogical_uses=(
            "Model expert problem-solving",
            "Show how rules apply to concrete cases",
            "Reduce cognitive load before independent practice",
        ),
        suitable_narrative_roles=("example", "application"),
        accessibility_notes=("Self-paced reading not possible; pacing must support comprehension",),
    ),
)


# ── Feasibility rules ─────────────────────────────────────────────────────────
# All current podcast affordances require speech synthesis and audio assembly.

PODCAST_SUPPORT_RULES: tuple[AffordanceSupportRule, ...] = tuple(
    AffordanceSupportRule(
        modality=_PODCAST,
        affordance_id=a.id,
        required_capabilities=("speech.synthesize", "audio.assemble"),
    )
    for a in PODCAST_AFFORDANCES
)


# ── Catalog factory ───────────────────────────────────────────────────────────

def build_podcast_affordance_catalog() -> ModalityAffordanceCatalog:
    """Return a ModalityAffordanceCatalog pre-loaded with all podcast affordances."""
    return ModalityAffordanceCatalog(PODCAST_AFFORDANCES)
