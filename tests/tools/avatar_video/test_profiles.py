"""Tests for HeyGen logical avatar and voice profile registry."""
from __future__ import annotations

import pytest

from learning_pipeline.tools.avatar_video.profiles import (
    HeyGenAvatarProfile,
    HeyGenProfileRegistry,
    HeyGenVoiceProfile,
    build_fake_profile_registry,
)
from learning_pipeline.tools.errors import MissingRealModeConfigError


# ── Registry basics ───────────────────────────────────────────────────────────


def _registry() -> HeyGenProfileRegistry:
    return HeyGenProfileRegistry(
        avatar_profiles={
            "default_instructor": HeyGenAvatarProfile(
                profile="default_instructor",
                avatar_id="Annie_expressive_public",
                avatar_style="normal",
            )
        },
        voice_profiles={
            "default_instructor": HeyGenVoiceProfile(
                profile="default_instructor",
                voice_id="330290724a1b470fb63153f34d4c0183",
                default_speed=1.0,
            )
        },
    )


def test_resolve_avatar_known_profile():
    reg = _registry()
    ap = reg.resolve_avatar("default_instructor")
    assert ap.avatar_id == "Annie_expressive_public"
    assert ap.avatar_style == "normal"


def test_resolve_voice_known_profile():
    reg = _registry()
    vp = reg.resolve_voice("default_instructor")
    assert vp.voice_id == "330290724a1b470fb63153f34d4c0183"


def test_resolve_avatar_unknown_raises():
    reg = _registry()
    with pytest.raises(MissingRealModeConfigError, match="default_narrator"):
        reg.resolve_avatar("default_narrator")


def test_resolve_voice_unknown_raises():
    reg = _registry()
    with pytest.raises(MissingRealModeConfigError, match="unknown_voice"):
        reg.resolve_voice("unknown_voice")


def test_profile_names():
    reg = _registry()
    assert "default_instructor" in reg.avatar_profile_names
    assert "default_instructor" in reg.voice_profile_names


# ── Provider IDs absent from planner manifest ─────────────────────────────────


def test_provider_ids_not_in_manifest():
    from learning_pipeline.tools.avatar_video.definition import avatar_video_tool_definition

    definition = avatar_video_tool_definition()
    manifest_str = str(definition.manifest.model_dump())
    # Provider-specific IDs must not appear in the planner-safe manifest
    assert "Annie_expressive_public" not in manifest_str
    assert "330290724a1b470fb63153f34d4c0183" not in manifest_str
    assert "api_key" not in manifest_str.lower()


# ── Fake registry ─────────────────────────────────────────────────────────────


def test_fake_registry_resolves_default_instructor():
    reg = build_fake_profile_registry()
    ap = reg.resolve_avatar("default_instructor")
    vp = reg.resolve_voice("default_instructor")
    assert ap.avatar_id  # not empty
    assert vp.voice_id   # not empty


def test_fake_registry_resolves_default_narrator():
    reg = build_fake_profile_registry()
    # default_narrator aliases to the same fake avatar profile; just confirm it resolves.
    ap = reg.resolve_avatar("default_narrator")
    assert ap is not None
    assert ap.avatar_id  # non-empty


# ── Environment-based loading ─────────────────────────────────────────────────


def test_load_profile_settings_from_env(monkeypatch):
    monkeypatch.setenv(
        "HEYGEN_AVATAR_PROFILE_DEFAULT_INSTRUCTOR_ID", "test-avatar-id"
    )
    monkeypatch.setenv(
        "HEYGEN_VOICE_PROFILE_DEFAULT_INSTRUCTOR_ID", "test-voice-id"
    )
    from learning_pipeline.tools.avatar_video.profiles import load_profile_settings

    reg = load_profile_settings()
    ap = reg.resolve_avatar("default_instructor")
    assert ap.avatar_id == "test-avatar-id"
    vp = reg.resolve_voice("default_instructor")
    assert vp.voice_id == "test-voice-id"


def test_load_profile_settings_empty_env(monkeypatch):
    monkeypatch.delenv("HEYGEN_AVATAR_PROFILE_DEFAULT_INSTRUCTOR_ID", raising=False)
    monkeypatch.delenv("HEYGEN_VOICE_PROFILE_DEFAULT_INSTRUCTOR_ID", raising=False)
    from learning_pipeline.tools.avatar_video.profiles import load_profile_settings

    reg = load_profile_settings()
    # Empty env → no profiles registered → resolve raises
    with pytest.raises(MissingRealModeConfigError):
        reg.resolve_avatar("default_instructor")
