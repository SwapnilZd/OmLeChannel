"""
Podcast Modality Planner — Phase 10.

Implements the Modality Planner layer: CourseBlueprint → ModalityPlan.

Components:
  ModalityContextResolver    — loads RLO content into ModalityPlanningContext
  PodcastModalityPlanner     — one LLM call per uncached request
  PodcastModalityPlanBuilder — deterministic draft → ModalityPlan
  validate_podcast_modality_draft — semantic validation of LLM output
"""
