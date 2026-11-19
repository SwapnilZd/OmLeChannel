"""Prompt version bookkeeping — WS5 of docs/prompt-tuning-plan.md.

Every module-level PROMPT_VERSION (or equivalent) constant must appear in the
header line of the prompt file it governs.  This forces a version bump and a
content change to travel together: bumping the constant without touching the
file (or vice versa) fails here.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _cases() -> list[tuple[str, str, Path]]:
    from learning_pipeline.planners.curriculum import agent as curriculum_agent
    from learning_pipeline.format_selector import recommender
    from learning_pipeline.planners.modality.elearning import planner as mod_elearning
    from learning_pipeline.planners.modality.podcast import planner as mod_podcast
    from learning_pipeline.planners.modality.video import planner as mod_video
    from learning_pipeline.planners.workflow.elearning import planner as wf_elearning
    from learning_pipeline.planners.workflow.podcast import planner as wf_podcast
    from learning_pipeline.planners.workflow.video import planner as wf_video
    from learning_pipeline.tools.elearning_bundle import _authoring_client
    from learning_pipeline.tools.elearning_bundle import _authoring_controller
    from learning_pipeline.tools.elearning_bundle import executor_real_author
    from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
        CONTENT_CHARTER_VERSION,
        REVIEW_RUBRIC_VERSION,
    )
    from learning_pipeline.tools.manim_video import _controller as manim_controller
    from learning_pipeline.tools.manim_video import _manim_client

    prompts_root = Path(executor_real_author._PROMPT_PATH).parents[1]

    return [
        (
            "curriculum_assembly",
            curriculum_agent.PROMPT_VERSION,
            curriculum_agent._PROMPTS_DIR / "course_assembly.md",
        ),
        ("format_selector", recommender.PROMPT_VERSION, recommender._DEFAULT_PROMPT_PATH),
        ("modality_elearning", mod_elearning.PROMPT_VERSION, mod_elearning._DEFAULT_PROMPT_PATH),
        ("modality_podcast", mod_podcast.PROMPT_VERSION, mod_podcast._DEFAULT_PROMPT_PATH),
        ("modality_video", mod_video.PROMPT_VERSION, mod_video._DEFAULT_PROMPT_PATH),
        ("workflow_elearning", wf_elearning.PROMPT_VERSION, wf_elearning._DEFAULT_PROMPT_PATH),
        ("workflow_podcast", wf_podcast.PROMPT_VERSION, wf_podcast._DEFAULT_PROMPT_PATH),
        ("workflow_video", wf_video.PROMPT_VERSION, wf_video._DEFAULT_PROMPT_PATH),
        ("course_author", _authoring_client.PROMPT_VERSION, executor_real_author._PROMPT_PATH),
        ("course_review", REVIEW_RUBRIC_VERSION, _authoring_controller._REVIEW_PROMPT_PATH),
        ("manim_scene_draft", _manim_client.PROMPT_VERSION, manim_controller._PROMPT_PATH),
        (
            "content_charter",
            CONTENT_CHARTER_VERSION,
            prompts_root / "shared" / "learner_facing_content.md",
        ),
    ]


@pytest.mark.parametrize("name,version,path", _cases(), ids=lambda v: v if isinstance(v, str) and "/" not in str(v) else None)
def test_prompt_version_appears_in_file_header(name: str, version: str, path: Path) -> None:
    assert path.exists(), f"{name}: prompt file missing at {path}"
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert version in header, (
        f"{name}: PROMPT_VERSION '{version}' not found in header line of {path.name!r} "
        f"(header: {header!r}). Bump both together."
    )


def test_no_version_suffixed_prompt_filenames() -> None:
    """Filenames carry no version — the constant + header own versioning."""
    from learning_pipeline.tools.elearning_bundle import executor_real_author

    prompts_root = Path(executor_real_author._PROMPT_PATH).parents[1]
    offenders = sorted(
        p.relative_to(prompts_root)
        for p in prompts_root.rglob("*.md")
        if p.stem.rsplit("_", 1)[-1].startswith("v")
        and p.stem.rsplit("_", 1)[-1][1:].isdigit()
    )
    assert not offenders, f"version-suffixed prompt filenames found: {offenders}"
