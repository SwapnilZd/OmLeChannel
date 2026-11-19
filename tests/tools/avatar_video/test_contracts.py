"""Tests for video.avatar.render typed contracts."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_pipeline.tools.avatar_video.contracts import (
    AvatarProfileRef,
    AvatarVideoRenderInput,
    AvatarVideoScene,
    ImageBackground,
    SolidColorBackground,
    VideoDimensions,
    VideoBackground,
    VoiceProfileRef,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _solid_scene(scene_id: str = "s1", script: str = "Hello world.") -> dict:
    return {
        "scene_id": scene_id,
        "source_scene_ids": ["src-1"],
        "script": script,
        "background": {"kind": "color", "color": "#1A1A2E"},
    }


def _minimal_input(**overrides) -> dict:
    base = {
        "deliverable_id": "video-001",
        "scenes": [_solid_scene()],
        "avatar": {"profile": "default_instructor"},
        "voice": {"profile": "default_instructor", "speed": 1.0},
        "dimensions": {"width": 1280, "height": 720},
        "captions": False,
    }
    base.update(overrides)
    return base


# ── SolidColorBackground ──────────────────────────────────────────────────────


def test_solid_color_valid():
    bg = SolidColorBackground(color="#1A1A2E")
    assert bg.kind == "color"
    assert bg.color == "#1A1A2E"


def test_solid_color_uppercase_hex():
    bg = SolidColorBackground(color="#FFFFFF")
    assert bg.color == "#FFFFFF"


@pytest.mark.parametrize("bad_color", ["1A1A2E", "#ZZZ", "#12345", "red", ""])
def test_solid_color_invalid(bad_color):
    with pytest.raises(ValidationError, match="hex color"):
        SolidColorBackground(color=bad_color)


# ── ImageBackground ───────────────────────────────────────────────────────────


def test_image_background_valid():
    bg = ImageBackground(artifact_uri="artifact://backgrounds/bg.png")
    assert bg.kind == "image"


def test_image_background_fake_uri():
    bg = ImageBackground(artifact_uri="fake://test/bg.png")
    assert bg.artifact_uri.startswith("fake://")


def test_image_background_invalid_uri():
    with pytest.raises(ValidationError, match="artifact_uri"):
        ImageBackground(artifact_uri="/local/path/bg.png")


# ── VideoBackground ───────────────────────────────────────────────────────────


def test_video_background_valid():
    bg = VideoBackground(artifact_uri="artifact://bgs/video.mp4")
    assert bg.play_style == "fit_to_scene"


def test_video_background_invalid_play_style():
    with pytest.raises(ValidationError, match="play_style"):
        VideoBackground(artifact_uri="artifact://bgs/v.mp4", play_style="stretch")


# ── VideoDimensions ───────────────────────────────────────────────────────────


def test_dimensions_supported():
    d = VideoDimensions(width=1280, height=720)
    assert d.width == 1280


@pytest.mark.parametrize("w,h", [(800, 600), (1280, 600), (0, 0)])
def test_dimensions_unsupported(w, h):
    with pytest.raises(ValidationError, match="dimensions"):
        VideoDimensions(width=w, height=h)


# ── VoiceProfileRef ───────────────────────────────────────────────────────────


def test_voice_profile_positive_speed():
    vp = VoiceProfileRef(profile="default_instructor", speed=1.5)
    assert vp.speed == 1.5


def test_voice_profile_zero_speed_fails():
    with pytest.raises(ValidationError):
        VoiceProfileRef(profile="default_instructor", speed=0.0)


def test_voice_profile_negative_speed_fails():
    with pytest.raises(ValidationError):
        VoiceProfileRef(profile="default_instructor", speed=-1.0)


# ── AvatarVideoScene ──────────────────────────────────────────────────────────


def test_scene_valid():
    scene = AvatarVideoScene(**_solid_scene())
    assert scene.scene_id == "s1"
    assert scene.source_scene_ids == ("src-1",)


def test_scene_blank_script_fails():
    with pytest.raises(ValidationError, match="blank"):
        AvatarVideoScene(**_solid_scene(script="   "))


def test_scene_empty_source_scene_ids_fails():
    data = _solid_scene()
    data["source_scene_ids"] = []
    with pytest.raises(ValidationError, match="at least one entry"):
        AvatarVideoScene(**data)


def test_scene_blank_id_fails():
    with pytest.raises(ValidationError):
        AvatarVideoScene(**_solid_scene(scene_id="  "))


def test_scene_path_separator_id_fails():
    with pytest.raises(ValidationError):
        AvatarVideoScene(**_solid_scene(scene_id="a/b"))


def test_scene_positive_duration():
    data = _solid_scene()
    data["estimated_duration_seconds"] = 30.0
    scene = AvatarVideoScene(**data)
    assert scene.estimated_duration_seconds == 30.0


def test_scene_zero_duration_fails():
    data = _solid_scene()
    data["estimated_duration_seconds"] = 0.0
    with pytest.raises(ValidationError, match="positive"):
        AvatarVideoScene(**data)


# ── AvatarVideoRenderInput ────────────────────────────────────────────────────


def test_render_input_valid():
    inp = AvatarVideoRenderInput.model_validate(_minimal_input())
    assert inp.deliverable_id == "video-001"
    assert len(inp.scenes) == 1


def test_render_input_empty_scenes_fails():
    data = _minimal_input(scenes=[])
    with pytest.raises(ValidationError, match="at least one scene"):
        AvatarVideoRenderInput.model_validate(data)


def test_render_input_duplicate_scene_ids_fails():
    data = _minimal_input(scenes=[_solid_scene("s1"), _solid_scene("s1")])
    with pytest.raises(ValidationError, match="duplicate scene_id"):
        AvatarVideoRenderInput.model_validate(data)


def test_render_input_blank_deliverable_id_fails():
    with pytest.raises(ValidationError, match="blank"):
        AvatarVideoRenderInput.model_validate(_minimal_input(deliverable_id="  "))


def test_render_input_path_separator_in_deliverable_id_fails():
    with pytest.raises(ValidationError):
        AvatarVideoRenderInput.model_validate(_minimal_input(deliverable_id="a/b"))


def test_render_input_multiple_scenes_unique_ids():
    data = _minimal_input(
        scenes=[_solid_scene("s1"), _solid_scene("s2")]
    )
    inp = AvatarVideoRenderInput.model_validate(data)
    assert len(inp.scenes) == 2


def test_render_input_image_background():
    scene_data = _solid_scene()
    scene_data["background"] = {
        "kind": "image",
        "artifact_uri": "artifact://bgs/slide.png",
    }
    data = _minimal_input(scenes=[scene_data])
    inp = AvatarVideoRenderInput.model_validate(data)
    from learning_pipeline.tools.avatar_video.contracts import ImageBackground
    assert isinstance(inp.scenes[0].background, ImageBackground)


def test_render_input_captions_true():
    inp = AvatarVideoRenderInput.model_validate(_minimal_input(captions=True))
    assert inp.captions is True
