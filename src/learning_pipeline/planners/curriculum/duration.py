"""Duration estimation policy v1 — Phase 12.

Policy: duration_v1
-------------------
For each included RLO:
  1. Base = rlo.estimated_duration_minutes
  2. Content proportion = selected_ids / total_ids (1.0 if no explicit selection)
  3. Depth multiplier: SUMMARY=0.5, WORKING=1.0, COMPREHENSIVE=1.3
  4. Proficiency gap adjustment:
       same level           → 1.0
       one level gap        → 1.1
       two level gap (max)  → 1.2
  5. rlo_duration = ceil(base * proportion * depth * gap)

Total = sum(rlo_durations) + 2 * len(prerequisite_bridges)

All multipliers are documented here; no LLM contributes to final duration.
"""
from __future__ import annotations

import math

from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    RLOAssemblyContext,
    TailoredRLODraft,
)

DURATION_POLICY_VERSION = "duration_v1"

DEPTH_MULTIPLIERS: dict[ContentDepth, float] = {
    ContentDepth.SUMMARY: 0.5,
    ContentDepth.WORKING: 1.0,
    ContentDepth.COMPREHENSIVE: 1.3,
}

_PROFICIENCY_ORDER: dict[TopicProficiency, int] = {
    TopicProficiency.BEGINNER: 0,
    TopicProficiency.INTERMEDIATE: 1,
    TopicProficiency.ADVANCED: 2,
}

_BRIDGE_MINUTES = 2


def _gap_adjustment(start: TopicProficiency, target: TopicProficiency) -> float:
    gap = _PROFICIENCY_ORDER[target] - _PROFICIENCY_ORDER[start]
    if gap <= 0:
        return 1.0
    if gap == 1:
        return 1.1
    return 1.2  # gap == 2


def _content_proportion(draft: TailoredRLODraft, context: RLOAssemblyContext) -> float:
    sel = draft.selected_content
    selected_count = (
        len(sel.concept_ids) + len(sel.component_ids) + len(sel.assessment_item_ids)
    )
    total_count = (
        len(context.concepts) + len(context.components) + len(context.assessment_items)
    )
    if selected_count == 0 or total_count == 0:
        return 1.0
    return min(selected_count / total_count, 1.0)


def estimate_rlo_duration(
    draft: TailoredRLODraft,
    context: RLOAssemblyContext,
    starting_proficiency: TopicProficiency,
) -> int:
    """Estimate duration (minutes) for one included RLO under policy_v1."""
    base = context.estimated_duration_minutes
    proportion = _content_proportion(draft, context)
    depth = DEPTH_MULTIPLIERS[draft.content_depth]
    gap = _gap_adjustment(starting_proficiency, draft.target_proficiency)
    return max(1, math.ceil(base * proportion * depth * gap))


def estimate_total_duration(
    drafts: tuple[TailoredRLODraft, ...],
    contexts: dict[str, RLOAssemblyContext],
    starting_proficiencies: dict[str, TopicProficiency],
    bridge_count: int = 0,
) -> int:
    """Estimate total course duration (minutes) under policy_v1."""
    total = sum(
        estimate_rlo_duration(d, contexts[d.rlo_id], starting_proficiencies[d.rlo_id])
        for d in drafts
        if d.rlo_id in contexts
    )
    total += bridge_count * _BRIDGE_MINUTES
    return max(1, total)
