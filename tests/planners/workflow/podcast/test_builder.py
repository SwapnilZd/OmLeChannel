"""Tests for PodcastProductionPlanBuilder — Phase 9."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import (
    LiteralInput,
    ListInput,
    Modality,
    ObjectInput,
    TaskOutputInput,
)
from learning_pipeline.contracts.planning import (
    PodcastProductionDraft,
    PodcastSpeechSegmentDraft,
)
from learning_pipeline.planners.workflow.podcast.builder import (
    ASSEMBLY_JOB_ID,
    PodcastPlanBuilderError,
    PodcastProductionPlanBuilder,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _seg(
    segment_id: str,
    source_scene_ids: tuple = ("scene-a",),
    speaker: str = "Host",
    text: str = "Hello world.",
    pause: float = 0.0,
) -> PodcastSpeechSegmentDraft:
    return PodcastSpeechSegmentDraft(
        segment_id=segment_id,
        source_scene_ids=source_scene_ids,
        speaker=speaker,
        text=text,
        learning_purpose="test",
        pause_after_seconds=pause,
    )


def _draft(
    segments: tuple[PodcastSpeechSegmentDraft, ...] = (),
    draft_id: str = "test-draft",
    default_gap: float = 0.35,
    output_filename: str | None = None,
) -> PodcastProductionDraft:
    if not segments:
        segments = (_seg("seg-01"),)
    return PodcastProductionDraft(
        draft_id=draft_id,
        title="Test Episode",
        narrative_summary="A test.",
        segments=segments,
        default_gap_seconds=default_gap,
        output_filename=output_filename,
    )


_builder = PodcastProductionPlanBuilder()


# ── Plan structure ─────────────────────────────────────────────────────────────


def test_returns_podcast_modality() -> None:
    plan = _builder.build(_draft())
    assert plan.modality == Modality.PODCAST


def test_plan_id_derived_from_draft_id() -> None:
    plan = _builder.build(_draft(draft_id="my-draft"))
    assert plan.plan_id == "pp-my-draft"


def test_narrative_matches_draft() -> None:
    d = _draft()
    plan = _builder.build(d)
    assert plan.narrative == d.narrative_summary


def test_single_segment_produces_two_jobs() -> None:
    plan = _builder.build(_draft(segments=(_seg("seg-01"),)))
    assert len(plan.jobs) == 2


def test_two_segments_produce_three_jobs() -> None:
    plan = _builder.build(_draft(segments=(
        _seg("seg-01"),
        _seg("seg-02", speaker="Expert"),
    )))
    assert len(plan.jobs) == 3


def test_speech_jobs_have_correct_capability() -> None:
    plan = _builder.build(_draft(segments=(
        _seg("seg-01"),
        _seg("seg-02", speaker="Expert"),
    )))
    speech_jobs = [j for j in plan.jobs if j.capability == "speech.synthesize"]
    assert len(speech_jobs) == 2


def test_exactly_one_assembly_job() -> None:
    plan = _builder.build(_draft())
    assembly_jobs = [j for j in plan.jobs if j.capability == "audio.assemble"]
    assert len(assembly_jobs) == 1
    assert assembly_jobs[0].id == ASSEMBLY_JOB_ID


def test_assembly_is_sole_deliverable() -> None:
    plan = _builder.build(_draft())
    assert plan.deliverable_job_ids == (ASSEMBLY_JOB_ID,)


# ── Speech job inputs ──────────────────────────────────────────────────────────


def test_speech_job_inputs_contain_text() -> None:
    plan = _builder.build(_draft(segments=(_seg("seg-01", text="Hello world."),)))
    speech = next(j for j in plan.jobs if j.capability == "speech.synthesize")
    assert isinstance(speech.inputs["text"], LiteralInput)
    assert speech.inputs["text"].value == "Hello world."


def test_speech_job_inputs_contain_speaker() -> None:
    plan = _builder.build(_draft(segments=(_seg("seg-01", speaker="Expert"),)))
    speech = next(j for j in plan.jobs if j.capability == "speech.synthesize")
    assert isinstance(speech.inputs["speaker"], LiteralInput)
    assert speech.inputs["speaker"].value == "Expert"


def test_speech_job_inputs_contain_pause() -> None:
    plan = _builder.build(_draft(segments=(_seg("seg-01", pause=0.8),)))
    speech = next(j for j in plan.jobs if j.capability == "speech.synthesize")
    assert isinstance(speech.inputs["pause_after_seconds"], LiteralInput)
    assert speech.inputs["pause_after_seconds"].value == pytest.approx(0.8)


def test_speech_job_has_no_dependencies() -> None:
    plan = _builder.build(_draft())
    speech = next(j for j in plan.jobs if j.capability == "speech.synthesize")
    assert speech.depends_on == ()


def test_speech_job_output_keys() -> None:
    plan = _builder.build(_draft())
    speech = next(j for j in plan.jobs if j.capability == "speech.synthesize")
    assert "audio_uri" in speech.output_keys
    assert "usage" in speech.output_keys


# ── Assembly job inputs ────────────────────────────────────────────────────────


def test_assembly_depends_on_all_speech_jobs() -> None:
    plan = _builder.build(_draft(segments=(
        _seg("seg-01"),
        _seg("seg-02", speaker="Expert"),
    )))
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    speech_ids = {j.id for j in plan.jobs if j.capability == "speech.synthesize"}
    assert set(assembly.depends_on) == speech_ids


def test_assembly_segments_input_is_list_input() -> None:
    plan = _builder.build(_draft())
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    assert isinstance(assembly.inputs["segments"], ListInput)


def test_assembly_segments_contain_object_inputs() -> None:
    plan = _builder.build(_draft(segments=(
        _seg("seg-01"),
        _seg("seg-02", speaker="Expert"),
    )))
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    items = assembly.inputs["segments"].items
    assert len(items) == 2
    assert all(isinstance(item, ObjectInput) for item in items)


def test_assembly_segment_audio_uri_is_task_output_binding() -> None:
    plan = _builder.build(_draft(segments=(_seg("seg-01"),)))
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    item = assembly.inputs["segments"].items[0]
    audio_binding = item.fields["audio_uri"]
    assert isinstance(audio_binding, TaskOutputInput)
    assert audio_binding.output_key == "audio_uri"


def test_assembly_default_gap_in_inputs() -> None:
    plan = _builder.build(_draft(default_gap=0.5))
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    assert isinstance(assembly.inputs["default_gap_seconds"], LiteralInput)
    assert assembly.inputs["default_gap_seconds"].value == pytest.approx(0.5)


def test_assembly_output_filename_when_set() -> None:
    plan = _builder.build(_draft(output_filename="ep-01.wav"))
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    assert isinstance(assembly.inputs["output_filename"], LiteralInput)
    assert assembly.inputs["output_filename"].value == "ep-01.wav"


def test_assembly_output_filename_absent_when_not_set() -> None:
    plan = _builder.build(_draft(output_filename=None))
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    assert "output_filename" not in assembly.inputs


def test_assembly_output_keys() -> None:
    plan = _builder.build(_draft())
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    assert "audio_uri" in assembly.output_keys
    assert "costs_uri" in assembly.output_keys


# ── Segment ordering ───────────────────────────────────────────────────────────


def test_segment_order_preserved_in_assembly() -> None:
    segs = tuple(_seg(f"seg-{i:02d}") for i in range(5))
    plan = _builder.build(_draft(segments=segs))
    assembly = next(j for j in plan.jobs if j.capability == "audio.assemble")
    binding_ids = [
        item.fields["segment_id"].value
        for item in assembly.inputs["segments"].items
    ]
    expected_order = [_sanitize(s.segment_id) for s in segs]
    assert binding_ids == expected_order


def _sanitize(segment_id: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_\-]", "-", segment_id).strip("-").lower()


# ── Determinism ────────────────────────────────────────────────────────────────


def test_same_draft_produces_same_plan() -> None:
    d = _draft(segments=(
        _seg("seg-01", text="First line."),
        _seg("seg-02", text="Second line.", speaker="Expert"),
    ))
    plan_a = _builder.build(d)
    plan_b = _builder.build(d)
    assert plan_a.model_dump_json() == plan_b.model_dump_json()


# ── Error cases ────────────────────────────────────────────────────────────────


def test_colliding_job_ids_after_sanitization_raises() -> None:
    # "seg 01" and "seg-01" both sanitize to "seg-01"
    segs = (
        _seg("seg 01"),
        _seg("seg-01", source_scene_ids=("scene-a",), speaker="Expert"),
    )
    with pytest.raises(PodcastPlanBuilderError, match="same job ID"):
        _builder.build(_draft(segments=segs))
