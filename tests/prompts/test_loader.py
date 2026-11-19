"""Tests for the prompt composition loader — WS6 of docs/prompt-tuning-plan.md."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.prompts import PromptIncludeError, load_prompt
from learning_pipeline.prompts.loader import PROMPTS_ROOT

_STYLE = "confident, clear and human"
_BOUNDARY = "Personalization changes presentation, not instructional truth"
_PODCAST_MEDIUM = "heard, not read"
_AVATAR_MEDIUM = "single synthetic presenter"


def test_plain_file_passes_through(tmp_path: Path) -> None:
    p = tmp_path / "plain.md"
    p.write_text("# Title\n\nNo markers here.", encoding="utf-8")
    assert load_prompt(p) == "# Title\n\nNo markers here."


def test_include_resolves_and_strips_header(tmp_path: Path) -> None:
    p = tmp_path / "with_include.md"
    p.write_text("before\n\n{{include:shared/deloitte_style.md}}\n\nafter", encoding="utf-8")
    text = load_prompt(p)
    assert _STYLE in text
    assert "Shared block" not in text  # header line stripped
    assert "{{include:" not in text


def test_missing_include_target_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text("{{include:shared/does_not_exist.md}}", encoding="utf-8")
    with pytest.raises(PromptIncludeError, match="does_not_exist"):
        load_prompt(p)


def test_include_cannot_escape_prompts_root(tmp_path: Path) -> None:
    p = tmp_path / "escape.md"
    p.write_text("{{include:../loader.py/../../pyproject.toml}}", encoding="utf-8")
    with pytest.raises(PromptIncludeError):
        load_prompt(p)


def test_nested_includes_rejected(tmp_path: Path) -> None:
    nested = PROMPTS_ROOT / "shared" / "_test_nested.md"
    nested.write_text("# t\n\n{{include:shared/deloitte_style.md}}", encoding="utf-8")
    try:
        p = tmp_path / "outer.md"
        p.write_text("{{include:shared/_test_nested.md}}", encoding="utf-8")
        with pytest.raises(PromptIncludeError, match="nested"):
            load_prompt(p)
    finally:
        nested.unlink()


@pytest.mark.parametrize(
    "rel,needles",
    [
        ("workflow_planner/podcast.md", (_STYLE, _BOUNDARY, _PODCAST_MEDIUM)),
        ("workflow_planner/elearning.md", (_STYLE, _BOUNDARY, _AVATAR_MEDIUM)),
        ("workflow_planner/video.md", (_STYLE, _AVATAR_MEDIUM)),
        ("modality_planner/podcast.md", (_BOUNDARY, _PODCAST_MEDIUM)),
        ("modality_planner/video.md", (_BOUNDARY, _AVATAR_MEDIUM)),
        (
            "elearning_author/course_author.md",
            (
                "Produce polished Deloitte corporate-training content",
                "Translate directions into concise teaching",
                _STYLE,
            ),
        ),
    ],
)
def test_shipped_prompts_compose(rel: str, needles: tuple[str, ...]) -> None:
    text = load_prompt(PROMPTS_ROOT / rel)
    assert "{{include:" not in text
    for needle in needles:
        assert needle in text, f"{needle!r} missing from composed {rel}"


def test_all_shipped_prompts_resolve_cleanly() -> None:
    """Every .md under the prompts root loads without unresolved markers."""
    for p in sorted(PROMPTS_ROOT.rglob("*.md")):
        text = load_prompt(p)
        assert "{{include:" not in text, f"unresolved include in {p}"


def test_elearning_planners_preserve_meaningful_manim_intent() -> None:
    modality = load_prompt(PROMPTS_ROOT / "modality_planner" / "elearning.md")
    workflow = load_prompt(PROMPTS_ROOT / "workflow_planner" / "elearning.md")

    assert "normally use an animated affordance for" in modality
    assert "content-fit preference, not a media quota" in modality
    assert "explicit production intent" in workflow
    assert "create a required" in workflow
    assert "matching `manim_directive`" in workflow


def test_elearning_avatar_guidance_is_brief_without_constraining_video_modality() -> None:
    modality = load_prompt(PROMPTS_ROOT / "modality_planner" / "elearning.md")
    workflow = load_prompt(PROMPTS_ROOT / "workflow_planner" / "elearning.md")
    video = load_prompt(PROMPTS_ROOT / "workflow_planner" / "video.md")

    assert "brief presenter interlude" in modality
    assert "brief presenter interlude" in workflow
    assert "20–45 seconds" in modality
    assert "20–45 seconds" in workflow
    assert "brief presenter interlude" not in video


def test_curriculum_and_modality_prompts_prefer_minimum_sufficient_scope() -> None:
    curriculum = load_prompt(
        PROMPTS_ROOT / "curriculum_assembly" / "course_assembly.md"
    )
    modality = load_prompt(PROMPTS_ROOT / "modality_planner" / "elearning.md")

    assert "minimum sufficient content" in curriculum
    assert "does not imply inclusion of every example" in curriculum
    assert "consolidate them into a shared scene" in modality
    assert "without adding new claims" in modality
