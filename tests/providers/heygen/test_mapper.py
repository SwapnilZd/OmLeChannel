"""Tests for HeyGenSceneMapper — pure, deterministic, no side effects."""
from __future__ import annotations

import pytest

from learning_pipeline.providers.heygen.mapper import HeyGenSceneMapper, clean_script
from learning_pipeline.providers.heygen.models import (
    HeyGenColorBackground,
    HeyGenImageBackground,
    ProviderVideoStatus,
)
from learning_pipeline.tools.avatar_video.contracts import (
    AvatarProfileRef,
    AvatarVideoRenderInput,
    AvatarVideoScene,
    ImageBackground,
    SolidColorBackground,
    VideoDimensions,
    VoiceProfileRef,
)
from learning_pipeline.tools.avatar_video.profiles import (
    HeyGenAvatarProfile,
    HeyGenVoiceProfile,
)


def _avatar_profile() -> HeyGenAvatarProfile:
    return HeyGenAvatarProfile(
        profile="default_instructor",
        avatar_id="Annie_expressive_public",
        avatar_style="normal",
    )


def _voice_profile() -> HeyGenVoiceProfile:
    return HeyGenVoiceProfile(
        profile="default_instructor",
        voice_id="voice-123",
        default_speed=1.0,
    )


def _solid_scene(
    scene_id: str = "s1",
    script: str = "Hello world.",
    estimated: float | None = None,
) -> AvatarVideoScene:
    data = {
        "scene_id": scene_id,
        "source_scene_ids": ["src-1"],
        "script": script,
        "background": {"kind": "color", "color": "#1A1A2E"},
    }
    if estimated:
        data["estimated_duration_seconds"] = estimated
    return AvatarVideoScene.model_validate(data)


def _image_scene(artifact_uri: str = "artifact://bgs/bg.png") -> AvatarVideoScene:
    return AvatarVideoScene.model_validate({
        "scene_id": "s-img",
        "source_scene_ids": ["src-1"],
        "script": "Background scene.",
        "background": {"kind": "image", "artifact_uri": artifact_uri},
    })


def _render_input(scenes: list[AvatarVideoScene]) -> AvatarVideoRenderInput:
    return AvatarVideoRenderInput(
        deliverable_id="vid-001",
        scenes=tuple(scenes),
        avatar=AvatarProfileRef(profile="default_instructor"),
        voice=VoiceProfileRef(profile="default_instructor", speed=1.0),
        dimensions=VideoDimensions(width=1280, height=720),
        captions=False,
    )


# ── clean_script ──────────────────────────────────────────────────────────────


def test_clean_script_normal():
    assert clean_script("Hello world.") == "Hello world."


def test_clean_script_collapses_newlines():
    assert clean_script("Line one.\nLine two.") == "Line one. Line two."


def test_clean_script_removes_control_chars():
    assert clean_script("A\x00B") == "AB"


def test_clean_script_normalises_em_dash():
    result = clean_script("one—two")
    assert " — " in result


def test_clean_script_empty():
    assert clean_script("") == ""


def test_clean_script_collapses_multiple_spaces():
    assert clean_script("a  b") == "a b"


# ── HeyGenSceneMapper ─────────────────────────────────────────────────────────


def test_map_request_color_background():
    mapper = HeyGenSceneMapper()
    request = _render_input([_solid_scene()])
    result = mapper.map_request(request, {}, _avatar_profile(), _voice_profile())

    assert len(result.video_inputs) == 1
    scene = result.video_inputs[0]
    assert scene.character.avatar_id == "Annie_expressive_public"
    assert scene.character.avatar_style == "normal"
    assert scene.voice.voice_id == "voice-123"
    assert scene.voice.speed == 1.0
    assert isinstance(scene.background, HeyGenColorBackground)
    assert scene.background.value == "#1A1A2E"


def test_map_request_preserves_scene_order():
    mapper = HeyGenSceneMapper()
    scenes = [_solid_scene(f"s{i}", f"Script {i}.") for i in range(3)]
    request = _render_input(scenes)
    result = mapper.map_request(request, {}, _avatar_profile(), _voice_profile())
    texts = [s.voice.input_text for s in result.video_inputs]
    assert texts == ["Script 0.", "Script 1.", "Script 2."]


def test_map_request_image_background_uses_resolved_asset():
    mapper = HeyGenSceneMapper()
    uri = "artifact://bgs/bg.png"
    request = _render_input([_image_scene(uri)])
    resolved = {uri: "asset-id-xyz"}
    result = mapper.map_request(request, resolved, _avatar_profile(), _voice_profile())
    bg = result.video_inputs[0].background
    assert isinstance(bg, HeyGenImageBackground)
    assert bg.image_asset_id == "asset-id-xyz"


def test_map_request_image_background_missing_asset_raises():
    mapper = HeyGenSceneMapper()
    request = _render_input([_image_scene("artifact://bgs/bg.png")])
    with pytest.raises(ValueError, match="no resolved asset_id"):
        mapper.map_request(request, {}, _avatar_profile(), _voice_profile())


def test_map_request_caption_setting():
    mapper = HeyGenSceneMapper()
    request = AvatarVideoRenderInput(
        deliverable_id="vid-001",
        scenes=(_solid_scene(),),
        avatar=AvatarProfileRef(profile="default_instructor"),
        voice=VoiceProfileRef(profile="default_instructor", speed=1.0),
        dimensions=VideoDimensions(width=1280, height=720),
        captions=True,
    )
    result = mapper.map_request(request, {}, _avatar_profile(), _voice_profile())
    assert result.caption is True


def test_map_request_dimensions():
    mapper = HeyGenSceneMapper()
    request = _render_input([_solid_scene()])
    result = mapper.map_request(request, {}, _avatar_profile(), _voice_profile())
    assert result.dimension.width == 1280
    assert result.dimension.height == 720


def test_clean_script_whitespace_only_returns_empty():
    # AvatarVideoScene already rejects blank scripts at construction, so test
    # the helper directly: clean_script on whitespace-only input returns "".
    assert clean_script("   \n  ") == ""


def test_map_request_video_background_raises_by_default():
    from learning_pipeline.tools.avatar_video.contracts import VideoBackground
    mapper = HeyGenSceneMapper()
    from learning_pipeline.tools.avatar_video.contracts import AvatarVideoScene as _S

    scene_data = {
        "scene_id": "s1",
        "source_scene_ids": ["src-1"],
        "script": "Hello.",
        "background": {"kind": "video", "artifact_uri": "artifact://bgs/bg.mp4"},
    }
    scene = _S.model_validate(scene_data)
    request = AvatarVideoRenderInput(
        deliverable_id="vid-001",
        scenes=(scene,),
        avatar=AvatarProfileRef(profile="default_instructor"),
        voice=VoiceProfileRef(profile="default_instructor", speed=1.0),
        dimensions=VideoDimensions(width=1280, height=720),
    )
    with pytest.raises(ValueError, match="VideoBackground is not supported"):
        mapper.map_request(request, {}, _avatar_profile(), _voice_profile())


def test_map_request_video_background_color_fallback():
    from learning_pipeline.tools.avatar_video.contracts import AvatarVideoScene as _S

    mapper = HeyGenSceneMapper(
        unsupported_background_policy="color_fallback",
        fallback_color="#000000",
    )
    scene = _S.model_validate({
        "scene_id": "s1",
        "source_scene_ids": ["src-1"],
        "script": "Hello.",
        "background": {"kind": "video", "artifact_uri": "artifact://bgs/bg.mp4"},
    })
    request = AvatarVideoRenderInput(
        deliverable_id="vid-001",
        scenes=(scene,),
        avatar=AvatarProfileRef(profile="default_instructor"),
        voice=VoiceProfileRef(profile="default_instructor", speed=1.0),
        dimensions=VideoDimensions(width=1280, height=720),
    )
    result = mapper.map_request(request, {}, _avatar_profile(), _voice_profile())
    bg = result.video_inputs[0].background
    assert isinstance(bg, HeyGenColorBackground)
    assert bg.value == "#000000"


def test_mapper_is_deterministic():
    mapper = HeyGenSceneMapper()
    request = _render_input([_solid_scene("s1"), _solid_scene("s2")])
    result1 = mapper.map_request(request, {}, _avatar_profile(), _voice_profile())
    result2 = mapper.map_request(request, {}, _avatar_profile(), _voice_profile())
    assert result1.model_dump() == result2.model_dump()
