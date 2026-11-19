"""Affordance IDs mentioned in prompts must exist in the catalogs — WS3.

Prompt prose may explain when to use an affordance, but every ID it names must
be real.  This guards the drift class where a catalog rename silently strands
guidance (or worse, teaches the model an ID that validation will reject).
"""
from __future__ import annotations

import re

from learning_pipeline.affordances.elearning import build_elearning_affordance_catalog
from learning_pipeline.affordances.podcast import build_podcast_affordance_catalog
from learning_pipeline.affordances.video import build_video_affordance_catalog
from learning_pipeline.contracts.common import Modality
from learning_pipeline.prompts.loader import PROMPTS_ROOT

# Two-segment e-learning affordance IDs only; (?!\.) excludes three-segment
# production capability names like `elearning.course.author`, which prompts
# legitimately cite as negative examples.
_ELEARNING_ID_RE = re.compile(r"\belearning\.[a-z_]+\b(?!\.)")


def test_elearning_modality_prompt_mentions_only_real_affordances() -> None:
    catalog = build_elearning_affordance_catalog()
    catalog_ids = {a.id for a in catalog.affordances_for(Modality.ELEARNING)}
    prompt = (PROMPTS_ROOT / "modality_planner" / "elearning.md").read_text(encoding="utf-8")
    mentioned = set(_ELEARNING_ID_RE.findall(prompt))
    unknown = sorted(mentioned - catalog_ids)
    assert not unknown, (
        f"prompt mentions affordance IDs missing from the e-learning catalog: {unknown}"
    )


def test_elearning_prompt_has_no_hardcoded_affordance_enum() -> None:
    """The schema example must not enumerate affordance IDs (payload is authoritative)."""
    prompt = (PROMPTS_ROOT / "modality_planner" / "elearning.md").read_text(encoding="utf-8")
    for line in prompt.splitlines():
        if '"affordance_id"' in line:
            assert len(_ELEARNING_ID_RE.findall(line)) == 0, (
                f"schema line hardcodes affordance IDs: {line.strip()!r}"
            )


def test_video_modality_prompt_examples_exist_in_catalog() -> None:
    catalog = build_video_affordance_catalog()
    catalog_ids = {a.id for a in catalog.affordances_for(Modality.VIDEO)}
    prompt = (PROMPTS_ROOT / "modality_planner" / "video.md").read_text(encoding="utf-8")
    mentioned = {
        m for m in re.findall(r'"(avatar_[a-z_]+)"', prompt)
    }
    unknown = sorted(mentioned - catalog_ids)
    assert not unknown, (
        f"prompt mentions affordance IDs missing from the video catalog: {unknown}"
    )


def test_podcast_catalog_loads() -> None:
    """Smoke check so a podcast catalog rename is at least noticed here."""
    assert build_podcast_affordance_catalog().affordances_for(Modality.PODCAST)
