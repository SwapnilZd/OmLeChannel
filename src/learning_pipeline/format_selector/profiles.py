"""Modality delivery profiles for the three top-level deliverable types — Phase 11.

Profiles describe high-level learner-facing capabilities.
They do not contain production tool internals, provider clients, or executor details.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import ModalityDeliveryProfile

PODCAST_PROFILE = ModalityDeliveryProfile(
    modality=Modality.PODCAST,
    enabled=True,
    description=(
        "A short, focused host-expert dialogue that illustrates or explains one or "
        "a few related concepts. No screen required. Best suited to concise concept "
        "explanations, grounded examples, reflection, and knowledge reinforcement; "
        "not a substitute for a broad multi-RLO course."
    ),
    supports_interactivity=False,
    supports_offline_access=True,
    supports_low_bandwidth=True,
    supports_screen_free_delivery=True,
    supports_captions=True,
    supports_transcripts=True,
    supports_keyboard_navigation=False,
    suitable_content_signals=(
        "spoken_explanation",
        "narrative",
        "concept_overview",
        "knowledge_reinforcement",
        "audio_first",
        "reflective",
    ),
    unsuitable_content_signals=(
        "broad_multi_rlo_curriculum",
        "mixed_modality_instruction",
        "visual_demonstration",
        "interactive_branching",
        "code_walkthrough_with_syntax",
        "data_table_analysis",
        "scored_assessment",
    ),
    production_cost_class="low",
    generation_latency_class="medium",
)

VIDEO_PROFILE = ModalityDeliveryProfile(
    modality=Modality.VIDEO,
    enabled=True,
    description=(
        "Recorded video content with on-screen presentation. "
        "Supports visual demonstrations, animations, and step-by-step walkthroughs. "
        "Screen required."
    ),
    supports_interactivity=False,
    supports_offline_access=True,
    supports_low_bandwidth=False,
    supports_screen_free_delivery=False,
    supports_captions=True,
    supports_transcripts=True,
    supports_keyboard_navigation=False,
    suitable_content_signals=(
        "visual_demonstration",
        "step_by_step",
        "animation",
        "screen_recording",
        "talking_head",
        "process_walkthrough",
    ),
    unsuitable_content_signals=(
        "interactive_branching",
        "scored_assessment",
        "screen_free",
        "audio_first",
    ),
    production_cost_class="high",
    generation_latency_class="high",
)

ELEARNING_PROFILE = ModalityDeliveryProfile(
    modality=Modality.ELEARNING,
    enabled=True,
    description=(
        "Interactive web-based or SCORM-compatible e-learning. "
        "Supports structured multi-topic instruction, mixed media, scored assessments, "
        "branching scenarios, practice activities, and full keyboard navigation for "
        "accessibility compliance."
    ),
    supports_interactivity=True,
    supports_offline_access=True,
    supports_low_bandwidth=False,
    supports_screen_free_delivery=False,
    supports_captions=True,
    supports_transcripts=True,
    supports_keyboard_navigation=True,
    suitable_content_signals=(
        "broad_multi_rlo_curriculum",
        "mixed_modality_instruction",
        "scored_assessment",
        "interactive_branching",
        "practice_activity",
        "knowledge_check",
        "simulation",
    ),
    unsuitable_content_signals=(
        "screen_free",
        "audio_first",
    ),
    production_cost_class="high",
    generation_latency_class="high",
)

MODALITY_PROFILES: dict[Modality, ModalityDeliveryProfile] = {
    Modality.VIDEO: VIDEO_PROFILE,
    Modality.PODCAST: PODCAST_PROFILE,
    Modality.ELEARNING: ELEARNING_PROFILE,
}

DEFAULT_PROFILES: tuple[ModalityDeliveryProfile, ...] = tuple(MODALITY_PROFILES.values())
