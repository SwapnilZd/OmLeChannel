"""Tests for RealElearningBundleAssemblerExecutor.

All tests are deterministic and use fake executors to produce input artifacts.
No LLM, Manim, HeyGen, or TTS calls.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.elearning_bundle.executor_bundle import (
    AssemblyError,
    RealElearningBundleAssemblerExecutor,
    _build_deterministic_zip,
    _safe_bundle_name,
)
from learning_pipeline.tools.elearning_bundle.executor_fake_author import FakeElearningCourseAuthorExecutor
from learning_pipeline.tools.elearning_bundle.executor_fake_manim import (
    FakeManimVideoExecutor,
    _FAKE_MP4_BYTES,
)
from learning_pipeline.tools.errors import InvalidToolInputError
from learning_pipeline.tools._fake_media import fake_mp4_bytes


# ── Fixtures and helpers ──────────────────────────────────────────────────────


def _ctx(inputs: dict, wf_id: str = "wf-test", task_id: str = "task-1") -> ExecutionContext:
    return ExecutionContext(workflow_id=wf_id, task_id=task_id, attempt=1, inputs=inputs)


_SLOT_ID = "intro-video"
_SCENE_ID = "scene-introduction"


async def _run_fake_author(store: FileArtifactStore, slot_id: str = _SLOT_ID) -> dict:
    executor = FakeElearningCourseAuthorExecutor(artifact_store=store)
    ctx = _ctx(
        {
            "deliverable_id": "course-test",
            "source_plan_id": "plan-test",
            "resolved_context_uri": "fake://ctx/test.json",
            "resolved_context_sha256": "a" * 64,
            "screen_requirements": [
                {
                    "kind": "authored_screen",
                    "screen_id": "screen-title",
                    "screen_type": "title",
                    "source_scene_ids": (_SCENE_ID,),
                    "content_direction": "Write a title.",
                },
                {
                    "kind": "video_slot",
                    "screen_id": f"screen-{slot_id}",
                    "slot_id": slot_id,
                    "source_scene_ids": (_SCENE_ID,),
                    "title": "Introduction",
                },
                {
                    "kind": "authored_screen",
                    "screen_id": "screen-completion",
                    "screen_type": "completion",
                    "source_scene_ids": (_SCENE_ID,),
                    "content_direction": "Write a completion message.",
                },
            ],
            "theme": "deloitte-green",
            "brand_contract": {},
            "accessibility_requirements": [],
            "authoring_direction": "",
        },
        task_id="author-task",
    )
    return await executor.execute(ctx)


async def _run_fake_manim(store: FileArtifactStore, animation_id: str = _SLOT_ID) -> dict:
    executor = FakeManimVideoExecutor(artifact_store=store)
    ctx = _ctx(
        {
            "animation_id": animation_id,
            "source_scene_ids": (_SCENE_ID,),
            "learning_objective": "Test objective.",
            "teaching_purpose": "Test purpose.",
            "visual_direction": "Test visual.",
            "narration_script": "This is the synchronized test narration.",
            "resolved_context_uri": "fake://ctx/test.json",
            "resolved_context_sha256": "a" * 64,
        },
        task_id="manim-task",
    )
    return await executor.execute(ctx)


def _assemble_inputs(
    author_out: dict,
    manim_out: dict,
    slot_id: str = _SLOT_ID,
    deliverable_id: str = "course-test",
    captions_required: bool = False,
    include_captions: bool = False,
) -> dict:
    slot = {
        "kind": "video_slot",
        "screen_id": f"screen-{slot_id}",
        "slot_id": slot_id,
        "source_scene_ids": (_SCENE_ID,),
        "title": "Introduction",
        "required": True,
        "captions_required": captions_required,
        "poster_required": False,
    }
    insertion = {
        "slot_id": slot_id,
        "source_scene_ids": (_SCENE_ID,),
        "video_uri": manim_out["video_uri"],
        "video_media_type": "video/mp4",
        "title": "Introduction",
    }
    if include_captions:
        insertion["captions_uri"] = manim_out["captions_uri"]
        insertion["captions_media_type"] = manim_out["captions_media_type"]
    return {
        "deliverable_id": deliverable_id,
        "course_json_uri": author_out["course_json_uri"],
        "author_assets": author_out["assets"],
        "required_slots": [slot],
        "video_insertions": [insertion],
        "output_filename": "index.html",
    }


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assembler_produces_html_artifact(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    manim_out = await _run_fake_manim(store)

    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    result = await executor.execute(_ctx(_assemble_inputs(author_out, manim_out)))

    html_uri = result["entry_html"]["uri"]
    assert html_uri.startswith("artifact://")
    html_bytes = await store.get_bytes(html_uri)
    assert b"<html" in html_bytes or b"<!DOCTYPE html" in html_bytes
    assert b'<button type="button" class="video-cc-toggle"' not in html_bytes


@pytest.mark.asyncio
async def test_assembler_produces_zip_artifact(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    manim_out = await _run_fake_manim(store)

    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    result = await executor.execute(_ctx(_assemble_inputs(author_out, manim_out)))

    zip_uri = result["bundle_zip"]["uri"]
    zip_bytes = await store.get_bytes(zip_uri)
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert "index.html" in names


@pytest.mark.asyncio
async def test_assembler_includes_video_in_zip(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    manim_out = await _run_fake_manim(store)

    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    result = await executor.execute(_ctx(_assemble_inputs(author_out, manim_out)))

    zip_uri = result["bundle_zip"]["uri"]
    zip_bytes = await store.get_bytes(zip_uri)
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    video_entries = [n for n in names if n.endswith(".mp4")]
    assert len(video_entries) == 1


@pytest.mark.asyncio
async def test_assembler_reports_correct_counts(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    manim_out = await _run_fake_manim(store)

    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    result = await executor.execute(_ctx(_assemble_inputs(author_out, manim_out)))

    assert result["video_count"] == 1
    assert result["unresolved_slot_count"] == 0
    assert result["screen_count"] >= 3


@pytest.mark.asyncio
async def test_assembler_produces_asset_manifest(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    manim_out = await _run_fake_manim(store)

    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    result = await executor.execute(_ctx(_assemble_inputs(author_out, manim_out)))

    manifest_uri = result["asset_manifest"]["uri"]
    manifest_bytes = await store.get_bytes(manifest_uri)
    manifest = json.loads(manifest_bytes)
    assert "entry_html" in manifest
    assert "assets" in manifest


@pytest.mark.asyncio
async def test_assembler_converts_required_srt_and_includes_vtt_in_package(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    manim_out = await _run_fake_manim(store)
    srt_ref = await store.put_bytes(
        namespace="test",
        name="heygen-captions.srt",
        data=b"1\n00:00:00,000 --> 00:00:02,000\nCaption text.\n",
        media_type="text/srt",
    )
    manim_out["captions_uri"] = srt_ref.uri
    manim_out["captions_media_type"] = "text/srt"

    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    result = await executor.execute(
        _ctx(
            _assemble_inputs(
                author_out,
                manim_out,
                captions_required=True,
                include_captions=True,
            )
        )
    )

    zip_bytes = await store.get_bytes(result["bundle_zip"]["uri"])
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
        caption_names = [name for name in zf.namelist() if name.endswith(".vtt")]
        assert len(caption_names) == 1
        assert zf.read(caption_names[0]).startswith(b"WEBVTT")
        html = zf.read("index.html")
        assert b'class="video-cc-toggle"' in html
        assert b'aria-pressed="true"' in html
        assert b"toggleCaptions(this)" in html

    manifest = json.loads(await store.get_bytes(result["asset_manifest"]["uri"]))
    caption_assets = [a for a in manifest["assets"] if a["path"].endswith(".vtt")]
    assert len(caption_assets) == 1
    assert caption_assets[0]["media_type"] == "text/vtt"


@pytest.mark.asyncio
async def test_assembler_rejects_missing_required_captions(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    manim_out = await _run_fake_manim(store)
    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)

    with pytest.raises(AssemblyError, match="Required captions.*intro-video"):
        await executor.execute(
            _ctx(
                _assemble_inputs(
                    author_out,
                    manim_out,
                    captions_required=True,
                    include_captions=False,
                )
            )
        )


# ── Deterministic ZIP ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zip_is_deterministic(tmp_path):
    store1 = FileArtifactStore(tmp_path / "run1" / "artifacts")
    store2 = FileArtifactStore(tmp_path / "run2" / "artifacts")

    author_out1 = await _run_fake_author(store1)
    manim_out1 = await _run_fake_manim(store1)
    result1 = await RealElearningBundleAssemblerExecutor(artifact_store=store1).execute(
        _ctx(_assemble_inputs(author_out1, manim_out1), wf_id="wf-run1")
    )

    author_out2 = await _run_fake_author(store2)
    manim_out2 = await _run_fake_manim(store2)
    result2 = await RealElearningBundleAssemblerExecutor(artifact_store=store2).execute(
        _ctx(_assemble_inputs(author_out2, manim_out2), wf_id="wf-run2")
    )

    zip1 = await store1.get_bytes(result1["bundle_zip"]["uri"])
    zip2 = await store2.get_bytes(result2["bundle_zip"]["uri"])

    with zipfile.ZipFile(__import__("io").BytesIO(zip1)) as z1:
        names1 = sorted(z1.namelist())
        html1 = z1.read("index.html")
    with zipfile.ZipFile(__import__("io").BytesIO(zip2)) as z2:
        names2 = sorted(z2.namelist())
        html2 = z2.read("index.html")

    assert names1 == names2
    assert html1 == html2


# ── Slot validation errors ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_required_slot_raises(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store, slot_id="slot-a")
    manim_out = await _run_fake_manim(store)

    # Declare slot-b as required but don't provide it in course or insertion
    inputs = {
        "deliverable_id": "course-test",
        "course_json_uri": author_out["course_json_uri"],
        "author_assets": author_out["assets"],
        "required_slots": [
            {"kind": "video_slot", "screen_id": "screen-slot-b", "slot_id": "slot-b", "source_scene_ids": (_SCENE_ID,), "title": "Slot B", "required": True, "captions_required": False, "poster_required": False},
        ],
        "video_insertions": [],
        "output_filename": "index.html",
    }
    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    from learning_pipeline.tools.elearning_bundle.slot_validator import SlotPreservationError
    with pytest.raises(SlotPreservationError):
        await executor.execute(_ctx(inputs))


@pytest.mark.asyncio
async def test_insertion_targeting_missing_slot_raises(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store, slot_id="slot-a")
    manim_out = await _run_fake_manim(store)

    inputs = {
        "deliverable_id": "course-test",
        "course_json_uri": author_out["course_json_uri"],
        "author_assets": author_out["assets"],
        "required_slots": [
            {"kind": "video_slot", "screen_id": "screen-slot-a", "slot_id": "slot-a", "source_scene_ids": (_SCENE_ID,), "title": "Slot A", "required": True, "captions_required": False, "poster_required": False},
        ],
        "video_insertions": [
            {
                "slot_id": "nonexistent-slot",
                "source_scene_ids": (_SCENE_ID,),
                "video_uri": manim_out["video_uri"],
                "video_media_type": "video/mp4",
            }
        ],
        "output_filename": "index.html",
    }
    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    with pytest.raises(AssemblyError, match="nonexistent-slot"):
        await executor.execute(_ctx(inputs))


# ── MP4 header validation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_mp4_header_raises(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)

    bad_video_ref = await store.put_bytes(
        namespace="test", name="bad.mp4",
        data=b"not-an-mp4-file", media_type="video/mp4",
    )
    inputs = _assemble_inputs(
        author_out,
        {"video_uri": bad_video_ref.uri, "video": bad_video_ref.model_dump()},
    )
    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    with pytest.raises(AssemblyError, match="ftyp"):
        await executor.execute(_ctx(inputs))


@pytest.mark.asyncio
async def test_mismatched_video_dimensions_raise(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    author_out = await _run_fake_author(store)
    video_ref = await store.put_bytes(
        namespace="test",
        name="wrong-size.mp4",
        data=fake_mp4_bytes(1920, 1080),
        media_type="video/mp4",
    )
    inputs = _assemble_inputs(
        author_out,
        {"video_uri": video_ref.uri, "video": video_ref.model_dump()},
    )
    executor = RealElearningBundleAssemblerExecutor(artifact_store=store)
    with pytest.raises(AssemblyError, match="1920x1080.*1280x720"):
        await executor.execute(_ctx(inputs))


# ── Path safety helpers ───────────────────────────────────────────────────────


def test_safe_bundle_name_alphanum():
    assert _safe_bundle_name("intro-video", ".mp4") == "intro-video.mp4"


def test_safe_bundle_name_special_chars_replaced():
    name = _safe_bundle_name("bad slot!", ".mp4")
    assert "!" not in name
    assert " " not in name
    assert name.endswith(".mp4")


def test_safe_bundle_name_hyphens_preserved():
    assert _safe_bundle_name("my-slot_name", ".vtt") == "my-slot_name.vtt"


# ── _build_deterministic_zip ──────────────────────────────────────────────────


def test_deterministic_zip_consistent():
    files = [("b.html", b"<html/>"), ("a.txt", b"hello")]
    zip1 = _build_deterministic_zip(files)
    zip2 = _build_deterministic_zip(files)
    assert zip1 == zip2


def test_deterministic_zip_sorted_entries():
    files = [("z.txt", b"zzz"), ("a.txt", b"aaa")]
    zip_bytes = _build_deterministic_zip(files)
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert names == sorted(names)


def test_deterministic_zip_fixed_timestamps():
    files = [("test.txt", b"data")]
    zip_bytes = _build_deterministic_zip(files)
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
        info = zf.getinfo("test.txt")
    assert info.date_time == (2020, 1, 1, 0, 0, 0)
