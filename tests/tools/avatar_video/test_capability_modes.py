"""Tests for avatar video executor registry and catalog registration."""
from __future__ import annotations

from learning_pipeline.config import build_fake_registry


# ── Registry ──────────────────────────────────────────────────────────────────


def test_build_fake_registry_registers_avatar_video():
    registry = build_fake_registry()
    assert "video.avatar.render" in registry.registered_task_types


def test_build_fake_registry_registers_all_capabilities():
    registry = build_fake_registry()
    assert "speech.synthesize" in registry.registered_task_types
    assert "audio.assemble" in registry.registered_task_types
    assert "video.avatar.render" in registry.registered_task_types


# ── Catalog registration ──────────────────────────────────────────────────────


def test_avatar_video_in_catalog():
    from learning_pipeline.config import build_tool_catalog
    catalog = build_tool_catalog()
    assert "video.avatar.render" in catalog.capabilities


def test_registered_task_types_includes_avatar_video():
    from learning_pipeline.config import REGISTERED_TASK_TYPES
    assert "video.avatar.render" in REGISTERED_TASK_TYPES


def test_catalog_has_six_capabilities():
    from learning_pipeline.config import build_tool_catalog
    catalog = build_tool_catalog()
    # speech + audio + avatar + elearning author + manim + elearning assemble
    assert len(catalog.capabilities) == 6


# ── BuildPlan is unchanged by executor mode ───────────────────────────────────


def test_build_plan_unchanged_by_executor_mode():
    """The frozen BuildPlan must not reference executor mode."""
    from pathlib import Path
    import json

    plan_path = (
        Path(__file__).parent.parent.parent.parent
        / "examples" / "reference" / "video" / "build_plan.json"
    )
    data = json.loads(plan_path.read_text())
    # Verify no executor-mode references exist in the BuildPlan
    plan_str = json.dumps(data)
    assert "executor_mode" not in plan_str
    assert "HEYGEN_API_KEY" not in plan_str
    assert "avatar_id" not in plan_str  # provider IDs absent
