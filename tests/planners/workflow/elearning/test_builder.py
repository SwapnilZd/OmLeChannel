"""Tests for ElearningProductionPlanBuilder — Phase 14D.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  1.  Authored-only draft → 2 jobs (author + assemble).
  2.  Plan modality is ELEARNING.
  3.  Author job has capability elearning.course.author.
  4.  Assembler job has capability elearning.bundle.assemble.
  5.  Assembler depends on author job.
  6.  Draft with one avatar slot → 3 jobs (author + avatar + assemble).
  7.  Avatar job has capability video.avatar.render.
  8.  Assembler depends on avatar job.
  9.  Draft with one Manim slot → 3 jobs (author + manim + assemble).
  10. Manim job has capability video.manim.render.
  11. Assembler depends on Manim job.
  12. Multiple media slots → correct job count.
  13. Avatar job ID is deterministic from slot_id.
  14. Manim job ID is deterministic from slot_id.
  15. Author job ID is canonical (elearning-course-author).
  16. Assemble job ID is canonical (elearning-bundle-assemble).
  17. Deliverable job is the assembler.
  18. Author job output_keys correct.
  19. Avatar job output_keys correct.
  20. Manim job output_keys correct.
  21. Assembler output_keys correct.
  22. Author job inputs include screen_requirements.
  23. Avatar job inputs include scenes with correct script.
  24. Manim job inputs include animation_id = slot_id.
  25. Assembler inputs course_json_uri is TaskOutputInput.
  26. Assembler inputs video_insertions is ListInput.
  27. Avatar captions binding uses TaskOutputInput when captions_required.
  28. Avatar captions binding is None LiteralInput when captions not required.
  29. Manim captions binding uses TaskOutputInput when captions_required.
  30. Manim captions binding is None LiteralInput when captions not required.
  31. Slot data not declared twice (slot_id source of truth is VideoSlotRequirement).
  32. Same validated draft always produces the same plan (determinism).
  33. Plan has correct plan_id prefix.
  34. Plan narrative matches draft.
  35. context_uri and context_hash passed to author job inputs.
"""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import (
    LiteralInput,
    ListInput,
    Modality,
    ModalityPlan,
    TaskOutputInput,
)
from learning_pipeline.contracts.planning import (
    AvatarMediaDirective,
    ElearningProductionDraft,
    ManimMediaDirective,
)
from learning_pipeline.planners.workflow.elearning.builder import (
    ASSEMBLE_JOB_ID,
    AUTHOR_JOB_ID,
    ElearningProductionPlanBuilder,
    _avatar_job_id,
    _manim_job_id,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    VideoSlotRequirement,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

_ELEARNING_PLAN_JSON = """{
  "plan_id": "mp-el-build-test",
  "modality": "elearning",
  "narrative": "Builder test plan.",
  "scenes": [
    {
      "id": "scene-intro",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Understand the intro.",
      "teaching_pattern": "direct_instruction",
      "preferred_capability": "elearning.static_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "intro"
    },
    {
      "id": "scene-apply",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Apply the concept.",
      "teaching_pattern": "worked_example",
      "preferred_capability": "elearning.avatar_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "example"
    }
  ]
}"""


def _plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_ELEARNING_PLAN_JSON)


def _authored(
    screen_id: str,
    scene_ids: tuple[str, ...],
    screen_type: str = "title",
) -> AuthoredScreenRequirement:
    return AuthoredScreenRequirement(
        screen_id=screen_id,
        screen_type=screen_type,
        source_scene_ids=scene_ids,
        content_direction="Write clearly.",
    )


def _slot(
    screen_id: str,
    slot_id: str,
    scene_ids: tuple[str, ...],
    captions_required: bool = True,
) -> VideoSlotRequirement:
    return VideoSlotRequirement(
        screen_id=screen_id,
        slot_id=slot_id,
        source_scene_ids=scene_ids,
        title=f"Video: {slot_id}",
        required=True,
        captions_required=captions_required,
    )


def _avatar_directive(slot_id: str) -> AvatarMediaDirective:
    return AvatarMediaDirective(
        slot_id=slot_id,
        narration_script=f"Narration for {slot_id}.",
        avatar_profile="default_instructor",
        voice_profile="default_narrator",
        visual_direction="Dark background.",
    )


def _manim_directive(slot_id: str) -> ManimMediaDirective:
    return ManimMediaDirective(
        slot_id=slot_id,
        narration_script=f"Animation narration for {slot_id}.",
        animation_direction="Show a flow diagram.",
        voice_profile="default_narrator",
    )


def _draft_authored_only() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="draft-build-1",
        source_modality_plan_id="mp-el-build-test",
        narrative="Test narrative.",
        authored_screens=(
            _authored("screen-intro", ("scene-intro",)),
            _authored("screen-apply", ("scene-apply",)),
        ),
        video_slots=(),
        screen_order=("screen-intro", "screen-apply"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Write clear content.",
    )


def _draft_with_avatar() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="draft-build-avatar",
        source_modality_plan_id="mp-el-build-test",
        narrative="Test with avatar.",
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-avatar", ("scene-apply",), captions_required=True),),
        screen_order=("screen-intro", "screen-video"),
        avatar_directives=(_avatar_directive("slot-avatar"),), manim_directives=(),
        course_authoring_direction="Use warm, encouraging tone.",
    )


def _draft_with_manim() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="draft-build-manim",
        source_modality_plan_id="mp-el-build-test",
        narrative="Test with Manim.",
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-manim", "slot-manim", ("scene-apply",), captions_required=True),),
        screen_order=("screen-intro", "screen-manim"),
        avatar_directives=(), manim_directives=(_manim_directive("slot-manim"),),
        course_authoring_direction="Keep it technical.",
    )


def _draft_with_both() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="draft-build-both",
        source_modality_plan_id="mp-el-build-test",
        narrative="Test with both.",
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(
            _slot("screen-avatar", "slot-avatar", ("scene-intro",)),
            _slot("screen-manim", "slot-manim", ("scene-apply",)),
        ),
        screen_order=("screen-intro", "screen-avatar", "screen-manim"),
        avatar_directives=(_avatar_directive("slot-avatar"),),
        manim_directives=(_manim_directive("slot-manim"),),
        course_authoring_direction="Mixed media course.",
    )


_BUILDER = ElearningProductionPlanBuilder()


# ── 1: Authored-only → 2 jobs ──────────────────────────────────────────────────

def test_authored_only_has_two_jobs():
    plan = _BUILDER.build(_draft_authored_only())
    assert len(plan.jobs) == 2  # author + assemble


# ── 2: Plan modality is ELEARNING ─────────────────────────────────────────────

def test_plan_modality_is_elearning():
    plan = _BUILDER.build(_draft_authored_only())
    assert plan.modality == Modality.ELEARNING


# ── 3: Author job capability ──────────────────────────────────────────────────

def test_author_job_capability():
    plan = _BUILDER.build(_draft_authored_only())
    author = next(j for j in plan.jobs if j.id == AUTHOR_JOB_ID)
    assert author.capability == "elearning.course.author"


# ── 4: Assembler job capability ───────────────────────────────────────────────

def test_assemble_job_capability():
    plan = _BUILDER.build(_draft_authored_only())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    assert assemble.capability == "elearning.bundle.assemble"


# ── 5: Assembler depends on author ────────────────────────────────────────────

def test_assemble_depends_on_author():
    plan = _BUILDER.build(_draft_authored_only())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    assert AUTHOR_JOB_ID in assemble.depends_on


# ── 6: Avatar draft → 3 jobs ──────────────────────────────────────────────────

def test_avatar_draft_has_three_jobs():
    plan = _BUILDER.build(_draft_with_avatar())
    assert len(plan.jobs) == 3


# ── 7: Avatar job capability ──────────────────────────────────────────────────

def test_avatar_job_capability():
    plan = _BUILDER.build(_draft_with_avatar())
    avatar_id = _avatar_job_id("slot-avatar")
    avatar_job = next((j for j in plan.jobs if j.id == avatar_id), None)
    assert avatar_job is not None
    assert avatar_job.capability == "video.avatar.render"


# ── 8: Assembler depends on avatar job ────────────────────────────────────────

def test_assemble_depends_on_avatar_job():
    plan = _BUILDER.build(_draft_with_avatar())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    avatar_id = _avatar_job_id("slot-avatar")
    assert avatar_id in assemble.depends_on


# ── 9: Manim draft → 3 jobs ───────────────────────────────────────────────────

def test_manim_draft_has_three_jobs():
    plan = _BUILDER.build(_draft_with_manim())
    assert len(plan.jobs) == 3


# ── 10: Manim job capability ──────────────────────────────────────────────────

def test_manim_job_capability():
    plan = _BUILDER.build(_draft_with_manim())
    manim_id = _manim_job_id("slot-manim")
    manim_job = next((j for j in plan.jobs if j.id == manim_id), None)
    assert manim_job is not None
    assert manim_job.capability == "video.manim.render"


# ── 11: Assembler depends on Manim job ────────────────────────────────────────

def test_assemble_depends_on_manim_job():
    plan = _BUILDER.build(_draft_with_manim())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    manim_id = _manim_job_id("slot-manim")
    assert manim_id in assemble.depends_on


# ── 12: Both media slots → 4 jobs ─────────────────────────────────────────────

def test_both_media_slots_has_four_jobs():
    plan = _BUILDER.build(_draft_with_both())
    assert len(plan.jobs) == 4  # author + avatar + manim + assemble


# ── 13: Avatar job ID is deterministic ────────────────────────────────────────

def test_avatar_job_id_deterministic():
    plan_a = _BUILDER.build(_draft_with_avatar())
    plan_b = _BUILDER.build(_draft_with_avatar())
    ids_a = {j.id for j in plan_a.jobs}
    ids_b = {j.id for j in plan_b.jobs}
    assert ids_a == ids_b


# ── 14: Manim job ID is deterministic ────────────────────────────────────────

def test_manim_job_id_deterministic():
    plan_a = _BUILDER.build(_draft_with_manim())
    plan_b = _BUILDER.build(_draft_with_manim())
    ids_a = {j.id for j in plan_a.jobs}
    ids_b = {j.id for j in plan_b.jobs}
    assert ids_a == ids_b


# ── 15: Author job ID is canonical ────────────────────────────────────────────

def test_author_job_id_is_canonical():
    plan = _BUILDER.build(_draft_authored_only())
    assert any(j.id == "elearning-course-author" for j in plan.jobs)


# ── 16: Assemble job ID is canonical ─────────────────────────────────────────

def test_assemble_job_id_is_canonical():
    plan = _BUILDER.build(_draft_authored_only())
    assert any(j.id == "elearning-bundle-assemble" for j in plan.jobs)


# ── 17: Deliverable is the assembler ─────────────────────────────────────────

def test_deliverable_is_assembler():
    plan = _BUILDER.build(_draft_authored_only())
    assert plan.deliverable_job_ids == (ASSEMBLE_JOB_ID,)


# ── 18: Author job output_keys ────────────────────────────────────────────────

def test_author_job_output_keys():
    plan = _BUILDER.build(_draft_authored_only())
    author = next(j for j in plan.jobs if j.id == AUTHOR_JOB_ID)
    assert "course_json_uri" in author.output_keys
    assert "assets" in author.output_keys


# ── 19: Avatar job output_keys ────────────────────────────────────────────────

def test_avatar_job_output_keys():
    plan = _BUILDER.build(_draft_with_avatar())
    avatar_id = _avatar_job_id("slot-avatar")
    job = next(j for j in plan.jobs if j.id == avatar_id)
    assert "video_uri" in job.output_keys
    assert "subtitle_uri" in job.output_keys


# ── 20: Manim job output_keys ─────────────────────────────────────────────────

def test_manim_job_output_keys():
    plan = _BUILDER.build(_draft_with_manim())
    manim_id = _manim_job_id("slot-manim")
    job = next(j for j in plan.jobs if j.id == manim_id)
    assert "video_uri" in job.output_keys
    assert "captions_uri" in job.output_keys


# ── 21: Assembler output_keys ─────────────────────────────────────────────────

def test_assemble_job_output_keys():
    plan = _BUILDER.build(_draft_authored_only())
    job = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    assert "bundle_zip" in job.output_keys
    assert "entry_html" in job.output_keys


# ── 22: Author job inputs contain screen_requirements ─────────────────────────

def test_author_job_inputs_contain_screen_requirements():
    plan = _BUILDER.build(_draft_authored_only())
    author = next(j for j in plan.jobs if j.id == AUTHOR_JOB_ID)
    assert "screen_requirements" in author.inputs
    inp = author.inputs["screen_requirements"]
    assert isinstance(inp, LiteralInput)
    assert len(inp.value) == 2


# ── 23: Avatar job scenes contain correct script ──────────────────────────────

def test_avatar_job_scenes_contain_narration_script():
    plan = _BUILDER.build(_draft_with_avatar())
    avatar_id = _avatar_job_id("slot-avatar")
    job = next(j for j in plan.jobs if j.id == avatar_id)
    scenes_input = job.inputs["scenes"]
    assert isinstance(scenes_input, LiteralInput)
    scenes = scenes_input.value
    assert len(scenes) == 1
    assert scenes[0]["script"] == "Narration for slot-avatar."


def test_avatar_job_matches_1280x720_slide_canvas():
    plan = _BUILDER.build(_draft_with_avatar())
    job = next(j for j in plan.jobs if j.id == _avatar_job_id("slot-avatar"))
    dimensions = job.inputs["dimensions"]
    assert isinstance(dimensions, LiteralInput)
    assert dimensions.value == {"width": 1280, "height": 720}


# ── 24: Manim job inputs include animation_id = slot_id ──────────────────────

def test_manim_job_animation_id_equals_slot_id():
    plan = _BUILDER.build(_draft_with_manim())
    manim_id = _manim_job_id("slot-manim")
    job = next(j for j in plan.jobs if j.id == manim_id)
    anim_input = job.inputs["animation_id"]
    assert isinstance(anim_input, LiteralInput)
    assert anim_input.value == "slot-manim"


def test_manim_job_matches_720p_slide_canvas_profile():
    plan = _BUILDER.build(_draft_with_manim())
    job = next(j for j in plan.jobs if j.id == _manim_job_id("slot-manim"))
    quality = job.inputs["quality_profile"]
    assert isinstance(quality, LiteralInput)
    assert quality.value == "standard"


# ── 25: Assembler course_json_uri is TaskOutputInput ─────────────────────────

def test_assembler_course_json_uri_is_task_output_input():
    plan = _BUILDER.build(_draft_authored_only())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    inp = assemble.inputs["course_json_uri"]
    assert isinstance(inp, TaskOutputInput)
    assert inp.task_id == AUTHOR_JOB_ID
    assert inp.output_key == "course_json_uri"


# ── 26: Assembler video_insertions is ListInput ───────────────────────────────

def test_assembler_video_insertions_is_list_input():
    plan = _BUILDER.build(_draft_with_avatar())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    inp = assemble.inputs["video_insertions"]
    assert isinstance(inp, ListInput)
    assert len(inp.items) == 1


# ── 27: Avatar captions binding uses TaskOutputInput when captions_required ───

def test_avatar_captions_binding_task_output_when_required():
    plan = _BUILDER.build(_draft_with_avatar())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    video_insertions = assemble.inputs["video_insertions"]
    assert isinstance(video_insertions, ListInput)
    insertion_obj = video_insertions.items[0]
    captions_uri_binding = insertion_obj.fields["captions_uri"]
    assert isinstance(captions_uri_binding, TaskOutputInput)
    assert captions_uri_binding.output_key == "subtitle_uri"


# ── 28: Avatar captions binding is None LiteralInput when not required ─────────

def test_avatar_captions_binding_none_when_not_required():
    draft = ElearningProductionDraft(
        draft_id="draft-no-captions",
        source_modality_plan_id="mp-el-build-test",
        narrative="Test.",
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-no-cap", ("scene-apply",), captions_required=False),),
        screen_order=("screen-intro", "screen-video"),
        avatar_directives=(
            AvatarMediaDirective(
                slot_id="slot-no-cap",
                narration_script="No captions needed.",
                avatar_profile="default_instructor",
                voice_profile="default_narrator",
                visual_direction="Dark.",
            ),
        ),
        manim_directives=(),
        course_authoring_direction="direction",
    )
    plan = _BUILDER.build(draft)
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    insertion_obj = assemble.inputs["video_insertions"].items[0]
    captions_uri = insertion_obj.fields["captions_uri"]
    assert isinstance(captions_uri, LiteralInput)
    assert captions_uri.value is None


# ── 29: Manim captions binding uses TaskOutputInput when captions_required ────

def test_manim_captions_binding_task_output_when_required():
    plan = _BUILDER.build(_draft_with_manim())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    insertion_obj = assemble.inputs["video_insertions"].items[0]
    captions_uri = insertion_obj.fields["captions_uri"]
    assert isinstance(captions_uri, TaskOutputInput)
    assert captions_uri.output_key == "captions_uri"


# ── 29b: Manim slots keep captions_required in the assembler's required_slots ─

def test_manim_slot_captions_required_preserved_for_assembler():
    # The container now exports captions, so the builder no longer downgrades
    # captions_required for Manim slots — the assembler enforces it as planned.
    plan = _BUILDER.build(_draft_with_manim())
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    required_slots = assemble.inputs["required_slots"].value
    assert required_slots[0]["captions_required"] is True


# ── 30: Manim captions binding is always dynamic (TaskOutputInput) ────────────

def test_manim_captions_binding_none_when_not_required():
    # Manim slots always bind captions_uri and captions_media_type via TaskOutputInput
    # so that the assembler receives consistent values at runtime (both None or both set).
    # The actual None-ness is determined by the executor, not the builder.
    draft = ElearningProductionDraft(
        draft_id="draft-manim-no-cap",
        source_modality_plan_id="mp-el-build-test",
        narrative="Test.",
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-manim", "slot-manim", ("scene-apply",), captions_required=False),),
        screen_order=("screen-intro", "screen-manim"),
        avatar_directives=(),
        manim_directives=(
            ManimMediaDirective(
                slot_id="slot-manim",
                narration_script="Animation without captions.",
                animation_direction="Show a diagram.",
            ),
        ),
        course_authoring_direction="direction",
    )
    plan = _BUILDER.build(draft)
    assemble = next(j for j in plan.jobs if j.id == ASSEMBLE_JOB_ID)
    insertion_obj = assemble.inputs["video_insertions"].items[0]
    captions_uri = insertion_obj.fields["captions_uri"]
    captions_media_type = insertion_obj.fields["captions_media_type"]
    assert isinstance(captions_uri, TaskOutputInput)
    assert captions_uri.output_key == "captions_uri"
    assert isinstance(captions_media_type, TaskOutputInput)
    assert captions_media_type.output_key == "captions_media_type"


# ── 31: Slot data not declared twice ──────────────────────────────────────────

def test_slot_data_not_in_directive():
    plan = _BUILDER.build(_draft_with_avatar())
    avatar_id = _avatar_job_id("slot-avatar")
    avatar_job = next(j for j in plan.jobs if j.id == avatar_id)
    # The slot_id should appear in the scenes list, not duplicated in directive fields
    scenes_val = avatar_job.inputs["scenes"].value
    assert scenes_val[0]["scene_id"] == "slot-avatar"
    # captions flag comes from slot.captions_required, not re-declared in directive
    captions_binding = avatar_job.inputs["captions"]
    assert isinstance(captions_binding, LiteralInput)
    assert captions_binding.value is True  # from slot.captions_required


# ── 32: Same draft always produces same plan ──────────────────────────────────

def test_build_is_deterministic():
    draft = _draft_with_avatar()
    plan_a = _BUILDER.build(draft)
    plan_b = _BUILDER.build(draft)
    # Compare job IDs and capabilities
    for ja, jb in zip(plan_a.jobs, plan_b.jobs):
        assert ja.id == jb.id
        assert ja.capability == jb.capability


# ── 33: Plan ID has correct prefix ───────────────────────────────────────────

def test_plan_id_has_pp_prefix():
    plan = _BUILDER.build(_draft_authored_only())
    assert plan.plan_id.startswith("pp-")
    assert "draft-build-1" in plan.plan_id


# ── 34: Plan narrative matches draft ─────────────────────────────────────────

def test_plan_narrative_matches_draft():
    draft = _draft_authored_only()
    plan = _BUILDER.build(draft)
    assert plan.narrative == draft.narrative


# ── 35: context_uri passed to author job ─────────────────────────────────────

def test_context_uri_passed_to_author_job():
    plan = _BUILDER.build(
        _draft_authored_only(),
        context_uri="memory://planning-context/abc123",
        context_hash="a" * 64,
    )
    author = next(j for j in plan.jobs if j.id == AUTHOR_JOB_ID)
    ctx_uri_inp = author.inputs["resolved_context_uri"]
    assert isinstance(ctx_uri_inp, LiteralInput)
    assert ctx_uri_inp.value == "memory://planning-context/abc123"


# ── 36: modality_plan scene objectives used in Manim job ─────────────────────

def test_manim_job_uses_scene_learning_objective():
    plan = _BUILDER.build(_draft_with_manim(), modality_plan=_plan())
    manim_id = _manim_job_id("slot-manim")
    job = next(j for j in plan.jobs if j.id == manim_id)
    obj_input = job.inputs["learning_objective"]
    assert isinstance(obj_input, LiteralInput)
    assert obj_input.value == "Apply the concept."
