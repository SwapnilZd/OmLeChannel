"""Contract consistency tests.

Verifies that the four layers of the elearning authoring system remain in sync:
  1. AUTHORABLE_SCREEN_TYPES — the registry of LLM-authorable types
  2. _REQUIRED_CONTENT_FIELDS — parse-time required-field table
  3. Component-specific learner-copy schemas used at the LLM boundary
  4. SCREEN_MODELS (pipeline/src/schema.py) — the authoritative pipeline models
  5. course_author.md — the authoring system prompt

A test in this file failing means a gap or duplicate was introduced that would
allow the LLM to produce structurally wrong output that passes parse-time
validation but fails pipeline schema validation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AUTHORABLE_SCREEN_TYPES,
    RESERVED_SCREEN_TYPES,
    ALL_SCREEN_TYPES,
    ScreenContent,
    _SCREEN_COPY_FIELDS,
    _REQUIRED_CONTENT_FIELDS,
)


# ── _REQUIRED_CONTENT_FIELDS coverage ────────────────────────────────────────


def test_every_authorable_type_has_required_fields_entry():
    """Every authorable screen type must appear in _REQUIRED_CONTENT_FIELDS."""
    missing = AUTHORABLE_SCREEN_TYPES - set(_REQUIRED_CONTENT_FIELDS)
    assert not missing, (
        f"Authorable types with no entry in _REQUIRED_CONTENT_FIELDS: {sorted(missing)}. "
        "Add an entry for each type."
    )


def test_required_fields_only_for_authorable_types():
    """_REQUIRED_CONTENT_FIELDS must not contain reserved or unknown types."""
    extra = set(_REQUIRED_CONTENT_FIELDS) - AUTHORABLE_SCREEN_TYPES
    assert not extra, (
        f"_REQUIRED_CONTENT_FIELDS has entries for non-authorable types: {sorted(extra)}."
    )


def test_no_empty_required_fields_sets():
    """Every entry in _REQUIRED_CONTENT_FIELDS must declare at least one field."""
    empty = [t for t, fields in _REQUIRED_CONTENT_FIELDS.items() if not fields]
    assert not empty, (
        f"Screen types with empty required-fields set: {empty}. "
        "Every authorable type must declare at least one required content field."
    )


# ── ScreenContent field coverage ─────────────────────────────────────────────


@pytest.mark.parametrize("screen_type", sorted(AUTHORABLE_SCREEN_TYPES))
def test_required_fields_exist_in_screen_content(screen_type):
    """Every required field for a screen type must be a field in ScreenContent."""
    screen_content_fields = set(ScreenContent.model_fields.keys())
    required = _REQUIRED_CONTENT_FIELDS.get(screen_type, frozenset())
    missing_from_model = required - screen_content_fields
    assert not missing_from_model, (
        f"screen_type={screen_type!r}: required fields not present in ScreenContent: "
        f"{sorted(missing_from_model)}. "
        "Add the missing fields to ScreenContent so the LLM output schema includes them."
    )


# ── SCREEN_MODELS consistency ─────────────────────────────────────────────────


def test_screen_models_covers_all_screen_types():
    """SCREEN_MODELS must have an entry for every type in ALL_SCREEN_TYPES."""
    from learning_pipeline.tools.elearning_bundle._pipeline_bridge import CourseContent  # noqa: F401 — sets up sys.path
    import sys
    schema_module = sys.modules.get("schema")
    assert schema_module is not None, "pipeline schema module not loaded"
    screen_models: dict = getattr(schema_module, "SCREEN_MODELS")

    missing = ALL_SCREEN_TYPES - set(screen_models)
    assert not missing, (
        f"SCREEN_MODELS is missing entries for: {sorted(missing)}."
    )


def test_screen_models_has_no_unknown_types():
    """SCREEN_MODELS must not contain types outside of ALL_SCREEN_TYPES."""
    from learning_pipeline.tools.elearning_bundle._pipeline_bridge import CourseContent  # noqa: F401
    import sys
    schema_module = sys.modules.get("schema")
    assert schema_module is not None
    screen_models: dict = getattr(schema_module, "SCREEN_MODELS")

    unknown = set(screen_models) - ALL_SCREEN_TYPES
    assert not unknown, (
        f"SCREEN_MODELS has entries for unrecognised types: {sorted(unknown)}."
    )


def test_authorable_types_all_have_pipeline_model():
    """Every authorable screen type must map to a pipeline schema model."""
    from learning_pipeline.tools.elearning_bundle._pipeline_bridge import CourseContent  # noqa: F401
    import sys
    schema_module = sys.modules.get("schema")
    assert schema_module is not None
    screen_models: dict = getattr(schema_module, "SCREEN_MODELS")

    missing = AUTHORABLE_SCREEN_TYPES - set(screen_models)
    assert not missing, (
        f"Authorable types with no pipeline model: {sorted(missing)}."
    )


# ── Prompt coverage ───────────────────────────────────────────────────────────


_PROMPT_PATH = (
    Path(__file__).resolve()
    .parent   # elearning/
    .parent   # tools/
    .parent   # tests/
    .parent   # repo root
    / "src"
    / "learning_pipeline"
    / "prompts"
    / "elearning_author"
    / "course_author.md"
)


def test_prompt_file_exists():
    assert _PROMPT_PATH.exists(), f"Authoring system prompt not found at {_PROMPT_PATH}"


@pytest.mark.parametrize("screen_type", sorted(AUTHORABLE_SCREEN_TYPES))
def test_prompt_mentions_screen_type(screen_type):
    """The authoring prompt must reference every authorable screen type."""
    prompt_text = _PROMPT_PATH.read_text(encoding="utf-8")
    assert f"**{screen_type}**" in prompt_text or screen_type in prompt_text, (
        f"Authoring prompt does not mention screen_type {screen_type!r}. "
        "Add a slot reference section for this type."
    )


@pytest.mark.parametrize("screen_type,required_field", [
    (st, f)
    for st, fields in sorted(_REQUIRED_CONTENT_FIELDS.items())
    for f in sorted(fields & set(_SCREEN_COPY_FIELDS[st]))
])
def test_prompt_mentions_required_field(screen_type, required_field):
    """Every model-authored required field must be named in the author prompt."""
    prompt_text = _PROMPT_PATH.read_text(encoding="utf-8")
    assert f"`{required_field}`" in prompt_text, (
        f"Authoring prompt does not reference field `{required_field}` "
        f"(required for screen_type {screen_type!r}). "
        "Add it to the screen type slot reference section."
    )


def test_source_and_navigation_fields_are_not_in_learner_copy_schemas():
    assert _SCREEN_COPY_FIELDS["knowledge_check"] == {}
    assert "branch_id" not in _SCREEN_COPY_FIELDS["scenario_branch"]
    assert "resolution_screen_id" not in _SCREEN_COPY_FIELDS["scenario_branch"]


# ── No reserved types in required-fields table ───────────────────────────────


def test_reserved_types_not_in_required_fields():
    """Reserved types (video_slot, video_player) must not appear in _REQUIRED_CONTENT_FIELDS."""
    overlap = RESERVED_SCREEN_TYPES & set(_REQUIRED_CONTENT_FIELDS)
    assert not overlap, (
        f"Reserved types appear in _REQUIRED_CONTENT_FIELDS: {overlap}."
    )
