"""Tests for Phase 14A e-learning contracts."""
from __future__ import annotations

import pytest

from learning_pipeline.tools.elearning_bundle.contracts import (
    AnimationBrief,
    AuthoredScreenRequirement,
    BundleAssetRef,
    CourseStructureRequirement,
    ElearningAuthoringBrief,
    ElearningAuthorOutput,
    ElearningBundleAssemblyInput,
    LearnerAction,
    ManimVideoOutput,
    SlotPreservationReport,
    VideoInsertion,
    VideoSlotRequirement,
)
from learning_pipeline.runtime.artifact_store import ArtifactRef


# ── Helpers ───────────────────────────────────────────────────────────────────


def test_authored_screen_requirement_accepts_structured_learner_action():
    requirement = AuthoredScreenRequirement(
        screen_id="screen-choice",
        screen_type="scenario_setup",
        source_scene_ids=("scene-1",),
        content_direction="Ask the learner to choose a response.",
        learner_action=LearnerAction.CHOOSE,
    )

    assert requirement.learner_action == LearnerAction.CHOOSE


def _artifact(uri: str = "artifact://ns/file.bin", media_type: str = "application/octet-stream") -> ArtifactRef:
    return ArtifactRef(uri=uri, media_type=media_type, sha256="a" * 64, size_bytes=10)


def _slot(slot_id: str = "intro-video", scenes: tuple = ("scene-1",), screen_id: str = "screen-intro-video", title: str = "Test Slot") -> VideoSlotRequirement:
    return VideoSlotRequirement(slot_id=slot_id, source_scene_ids=scenes, screen_id=screen_id, title=title)


# ── VideoSlotRequirement ──────────────────────────────────────────────────────


def test_slot_requirement_valid():
    s = _slot("my-slot-01")
    assert s.slot_id == "my-slot-01"
    assert s.required is True
    assert s.captions_required is True  # default changed to True


def test_slot_requirement_blank_id():
    with pytest.raises(Exception, match="must not be blank"):
        VideoSlotRequirement(slot_id="", source_scene_ids=("s1",), screen_id="sc1", title="T")


def test_slot_requirement_invalid_chars():
    with pytest.raises(Exception):
        VideoSlotRequirement(slot_id="bad slot!", source_scene_ids=("s1",), screen_id="sc1", title="T")


def test_slot_requirement_empty_scenes():
    with pytest.raises(Exception, match="must not be empty"):
        VideoSlotRequirement(slot_id="slot-1", source_scene_ids=(), screen_id="sc1", title="T")


def test_slot_requirement_hyphens_underscores_allowed():
    s = VideoSlotRequirement(slot_id="slot_one-two", source_scene_ids=("s1",), screen_id="sc1", title="T")
    assert s.slot_id == "slot_one-two"


# ── AuthoredScreenRequirement ─────────────────────────────────────────────────


def test_authored_screen_requirement_valid():
    req = AuthoredScreenRequirement(
        screen_id="screen-intro",
        screen_type="title",
        source_scene_ids=("scene-01",),
        content_direction="Write a title.",
    )
    assert req.kind == "authored_screen"
    assert req.screen_id == "screen-intro"


def test_authored_screen_requirement_blank_id_fails():
    with pytest.raises(Exception, match="must not be blank"):
        AuthoredScreenRequirement(
            screen_id="",
            screen_type="title",
            source_scene_ids=("scene-01",),
            content_direction="x",
        )


def test_authored_screen_requirement_blank_type_fails():
    with pytest.raises(Exception, match="must not be blank"):
        AuthoredScreenRequirement(
            screen_id="s-01",
            screen_type="",
            source_scene_ids=("scene-01",),
            content_direction="x",
        )


def test_authored_screen_requirement_blank_direction_fails():
    with pytest.raises(Exception, match="must not be blank"):
        AuthoredScreenRequirement(
            screen_id="s-01",
            screen_type="title",
            source_scene_ids=("scene-01",),
            content_direction="",
        )


def test_authored_screen_requirement_empty_scenes_fails():
    with pytest.raises(Exception, match="must not be empty"):
        AuthoredScreenRequirement(
            screen_id="s-01",
            screen_type="title",
            source_scene_ids=(),
            content_direction="x",
        )


# ── BundleAssetRef ────────────────────────────────────────────────────────────


def test_bundle_asset_ref_valid():
    ref = BundleAssetRef(logical_path="assets/img.png", artifact=_artifact())
    assert ref.logical_path == "assets/img.png"


def test_bundle_asset_ref_absolute_rejected():
    with pytest.raises(Exception, match="must be relative"):
        BundleAssetRef(logical_path="/abs/path.png", artifact=_artifact())


def test_bundle_asset_ref_traversal_rejected():
    with pytest.raises(Exception, match="must not contain"):
        BundleAssetRef(logical_path="../escape.png", artifact=_artifact())


def test_bundle_asset_ref_blank_rejected():
    with pytest.raises(Exception, match="must not be blank"):
        BundleAssetRef(logical_path="   ", artifact=_artifact())


# ── SlotPreservationReport ────────────────────────────────────────────────────


def test_slot_report_all_present():
    report = SlotPreservationReport.build(("a", "b"), ["a", "b"])
    assert report.valid is True
    assert report.missing_slot_ids == ()
    assert report.duplicate_slot_ids == ()


def test_slot_report_missing():
    report = SlotPreservationReport.build(("a", "b"), ["a"])
    assert report.valid is False
    assert "b" in report.missing_slot_ids


def test_slot_report_duplicate():
    report = SlotPreservationReport.build(("a",), ["a", "a"])
    assert report.valid is False
    assert "a" in report.duplicate_slot_ids


def test_slot_report_unexpected_not_invalid():
    report = SlotPreservationReport.build(("a",), ["a", "extra"])
    assert report.valid is True
    assert "extra" in report.unexpected_slot_ids


def test_slot_report_empty_required_empty_discovered():
    report = SlotPreservationReport.build((), [])
    assert report.valid is True


# ── ElearningAuthoringBrief ───────────────────────────────────────────────────


def _brief(**overrides) -> dict:
    base = {
        "deliverable_id": "course-001",
        "source_plan_id": "plan-001",
        "resolved_context_uri": "fake://ctx/001.json",
        "resolved_context_sha256": "a" * 64,
        "screen_requirements": [
            {
                "kind": "authored_screen",
                "screen_id": "screen-title",
                "screen_type": "title",
                "source_scene_ids": ("scene-1",),
                "content_direction": "Write a title.",
            },
            {
                "kind": "video_slot",
                "screen_id": "screen-slot-1",
                "slot_id": "slot-1",
                "source_scene_ids": ("scene-1",),
                "title": "Intro Video",
            },
        ],
    }
    base.update(overrides)
    return base


def test_authoring_brief_valid():
    brief = ElearningAuthoringBrief.model_validate(_brief())
    assert brief.deliverable_id == "course-001"


def test_authoring_brief_blank_deliverable_id():
    with pytest.raises(Exception):
        ElearningAuthoringBrief.model_validate(_brief(deliverable_id=""))


def test_authoring_brief_duplicate_slot_ids():
    with pytest.raises(Exception, match="unique slot_ids"):
        ElearningAuthoringBrief.model_validate(_brief(
            screen_requirements=[
                {
                    "kind": "authored_screen",
                    "screen_id": "screen-title",
                    "screen_type": "title",
                    "source_scene_ids": ("s1",),
                    "content_direction": "x",
                },
                {"kind": "video_slot", "screen_id": "sc-a", "slot_id": "dup", "source_scene_ids": ("s1",), "title": "T"},
                {"kind": "video_slot", "screen_id": "sc-b", "slot_id": "dup", "source_scene_ids": ("s2",), "title": "T"},
            ]
        ))


def test_authoring_brief_duplicate_screen_ids():
    with pytest.raises(Exception, match="unique screen_ids"):
        ElearningAuthoringBrief.model_validate(_brief(
            screen_requirements=[
                {
                    "kind": "authored_screen",
                    "screen_id": "same-id",
                    "screen_type": "title",
                    "source_scene_ids": ("s1",),
                    "content_direction": "x",
                },
                {
                    "kind": "authored_screen",
                    "screen_id": "same-id",
                    "screen_type": "objectives",
                    "source_scene_ids": ("s2",),
                    "content_direction": "y",
                },
            ]
        ))


def test_authoring_brief_no_authored_screen_fails():
    with pytest.raises(Exception, match="AuthoredScreenRequirement"):
        ElearningAuthoringBrief.model_validate(_brief(
            screen_requirements=[
                {"kind": "video_slot", "screen_id": "sc-a", "slot_id": "slot-1", "source_scene_ids": ("s1",), "title": "T"},
            ]
        ))


# ── ElearningAuthorOutput ─────────────────────────────────────────────────────


def _author_output(**overrides) -> dict:
    art = _artifact("artifact://ns/course.json", "application/json")
    base = {
        "course_json": art.model_dump(),
        "course_json_uri": art.uri,
        "assets": [],
        "slot_report": SlotPreservationReport.build((), []).model_dump(),
        "preview_html": None,
        "trace_uri": None,
    }
    base.update(overrides)
    return base


def test_author_output_valid():
    out = ElearningAuthorOutput.model_validate(_author_output())
    assert out.course_json_uri == out.course_json.uri


def test_author_output_uri_mismatch():
    with pytest.raises(Exception, match="must equal"):
        ElearningAuthorOutput.model_validate(
            _author_output(course_json_uri="artifact://other/path.json")
        )


# ── ManimVideoOutput ──────────────────────────────────────────────────────────


def test_manim_video_output_no_captions():
    video = _artifact("artifact://v/vid.mp4", "video/mp4")
    out = ManimVideoOutput(
        video=video, video_uri=video.uri,
        captions=None, captions_uri=None,
        poster=None, poster_uri=None,
        generated_source=None, render_log=None, trace_uri=None,
    )
    assert out.video_uri == video.uri


def test_manim_video_output_uri_mismatch():
    video = _artifact("artifact://v/vid.mp4", "video/mp4")
    with pytest.raises(Exception, match="video_uri must equal"):
        ManimVideoOutput(
            video=video, video_uri="artifact://other/vid.mp4",
            captions=None, captions_uri=None,
            poster=None, poster_uri=None,
            generated_source=None, render_log=None, trace_uri=None,
        )


def test_manim_video_captions_partial_raises():
    video = _artifact("artifact://v/vid.mp4", "video/mp4")
    captions = _artifact("artifact://v/vid.vtt", "text/vtt")
    with pytest.raises(Exception, match="captions_uri must equal"):
        ManimVideoOutput(
            video=video, video_uri=video.uri,
            captions=captions, captions_uri=None,
            poster=None, poster_uri=None,
            generated_source=None, render_log=None, trace_uri=None,
        )


# ── VideoInsertion ────────────────────────────────────────────────────────────


def test_video_insertion_valid():
    vi = VideoInsertion(
        slot_id="intro-video",
        source_scene_ids=("scene-1",),
        video_uri="artifact://v/vid.mp4",
    )
    assert vi.captions_uri is None


def test_video_insertion_unsupported_video_type():
    with pytest.raises(Exception, match="Unsupported video"):
        VideoInsertion(
            slot_id="s1",
            source_scene_ids=("sc1",),
            video_uri="artifact://v/vid.webm",
            video_media_type="video/webm",
        )


def test_video_insertion_captions_uri_without_media_type():
    with pytest.raises(Exception, match="both be set or both be None"):
        VideoInsertion(
            slot_id="s1",
            source_scene_ids=("sc1",),
            video_uri="artifact://v/vid.mp4",
            captions_uri="artifact://v/captions.vtt",
            captions_media_type=None,
        )


def test_video_insertion_empty_source_scene_ids():
    with pytest.raises(Exception, match="must not be empty"):
        VideoInsertion(
            slot_id="s1",
            source_scene_ids=(),
            video_uri="artifact://v/vid.mp4",
        )


def test_video_insertion_unsupported_caption_type():
    with pytest.raises(Exception, match="Unsupported caption"):
        VideoInsertion(
            slot_id="s1",
            source_scene_ids=("sc1",),
            video_uri="artifact://v/vid.mp4",
            captions_uri="artifact://v/caps.ass",
            captions_media_type="text/x-ssa",
        )


# ── ElearningBundleAssemblyInput ──────────────────────────────────────────────


def test_assembly_input_duplicate_insertion_slots():
    slot = {"kind": "video_slot", "screen_id": "sc-dup", "slot_id": "dup", "source_scene_ids": ("s1",), "title": "T", "required": True, "captions_required": True, "poster_required": False}
    insertion = {
        "slot_id": "dup", "source_scene_ids": ("s1",),
        "video_uri": "artifact://v/vid.mp4",
    }
    with pytest.raises(Exception, match="unique slot_ids"):
        ElearningBundleAssemblyInput(
            deliverable_id="d1",
            course_json_uri="artifact://ns/course.json",
            author_assets=(),
            required_slots=(slot,),
            video_insertions=(insertion, insertion),
        )


def test_assembly_input_duplicate_required_slots():
    slot = {"kind": "video_slot", "screen_id": "sc-dup", "slot_id": "dup", "source_scene_ids": ("s1",), "title": "T", "required": True, "captions_required": True, "poster_required": False}
    with pytest.raises(Exception, match="unique slot_ids"):
        ElearningBundleAssemblyInput(
            deliverable_id="d1",
            course_json_uri="artifact://ns/course.json",
            author_assets=(),
            required_slots=(slot, slot),
            video_insertions=(),
        )
