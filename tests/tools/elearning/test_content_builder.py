"""Tests for ElearningCourseContentBuilder — deterministic course assembly.

All tests use FrozenModel contracts and no LLM calls.
"""
from __future__ import annotations

import pytest

from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
)
from learning_pipeline.tools.elearning_bundle._content_builder import (
    CONTENT_BUILDER_VERSION,
    BuildError,
    ElearningCourseContentBuilder,
)
from learning_pipeline.tools.elearning_bundle._authoring_tools import AuthoringTools
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    FindingOwner,
    FindingRepairability,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
    VideoSlotRequirement,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _slot_req(slot_id: str = "intro-video") -> VideoSlotRequirement:
    return VideoSlotRequirement(
        screen_id=f"screen-{slot_id}",
        slot_id=slot_id,
        source_scene_ids=(f"scene-{slot_id}",),
        title=f"Slot {slot_id}",
    )


def _authored_entry(
    screen_id: str = "screen-title",
    source_scene_ids: tuple = ("scene-01",),
    screen_type: str = "title",
) -> AuthoredScreenRequirement:
    return AuthoredScreenRequirement(
        screen_id=screen_id,
        source_scene_ids=source_scene_ids,
        screen_type=screen_type,
        content_direction="Write a concise title and hook.",
    )


def _slot_entry(
    screen_id: str = "screen-intro-video",
    slot_id: str = "intro-video",
) -> VideoSlotRequirement:
    return VideoSlotRequirement(
        screen_id=screen_id,
        slot_id=slot_id,
        source_scene_ids=(f"scene-{slot_id}",),
        title=f"Slot {slot_id}",
    )


def _brief(screen_requirements: tuple) -> ElearningAuthoringBrief:
    """Build a minimal ElearningAuthoringBrief with screen_requirements."""
    return ElearningAuthoringBrief(
        deliverable_id="course-test-01",
        source_plan_id="plan-001",
        resolved_context_uri="fake://ctx/001.json",
        resolved_context_sha256="a" * 64,
        screen_requirements=screen_requirements,
    )


def _title_draft(screen_id: str = "screen-title") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="title",
        source_scene_ids=("scene-01",),
        content={
            "course_title": "Test Course",
            "subtitle": "A structured learning experience",
            "hook": "Explore key concepts.",
            "metadata": {"duration": "10 min"},
        },
    )


def _objectives_draft(screen_id: str = "screen-objectives") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="objectives",
        source_scene_ids=("scene-01",),
        content={
            "heading": "Learning Objectives",
            "objectives": ["Understand the framework.", "Apply concepts."],
        },
    )


def _completion_draft(screen_id: str = "screen-completion") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="completion",
        source_scene_ids=("scene-01",),
        content={
            "heading": "Module Complete",
            "message": "Congratulations on completing this module.",
            "skills_reinforced": ["Core concept application"],
        },
    )


def _full_draft(*screens: AuthoredScreenDraft) -> ElearningCourseAuthorDraft:
    return ElearningCourseAuthorDraft(
        draft_id="draft-001",
        title="Test Course",
        authored_screens=tuple(screens),
    )


# ── Basic happy-path tests ────────────────────────────────────────────────────


def test_builder_authored_only_course():
    """A course with no video slots builds successfully."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("screen-title", screen_type="title"),
            _authored_entry("screen-objectives", screen_type="objectives"),
            _authored_entry("screen-completion", screen_type="completion"),
        ),
    )
    draft = _full_draft(
        _title_draft("screen-title"),
        _objectives_draft("screen-objectives"),
        _completion_draft("screen-completion"),
    )
    builder = ElearningCourseContentBuilder()
    course_dict, report = builder.build(brief, draft)

    assert len(course_dict["screens"]) == 3
    assert course_dict["screens"][0]["type"] == "title"
    assert course_dict["screens"][1]["type"] == "objectives"
    assert course_dict["screens"][2]["type"] == "completion"
    title_metadata = course_dict["screens"][0]["metadata"]
    assert title_metadata["duration"] != "10 min"
    assert title_metadata["duration"].startswith("About ")
    assert isinstance(title_metadata["duration_minutes"], int)
    # Sequences are 1-indexed and consecutive
    assert [s["sequence"] for s in course_dict["screens"]] == [1, 2, 3]
    # No slots — report is trivially valid
    assert report.valid is True


def test_builder_splits_grouped_assessments_into_one_question_per_screen():
    brief = _brief(
        screen_requirements=(
            _authored_entry("screen-check", screen_type="knowledge_check"),
        )
    )
    draft = _full_draft(
        AuthoredScreenDraft(
            screen_id="screen-check",
            screen_type="knowledge_check",
            source_scene_ids=("scene-01",),
            content={
                "question_id": "recall-1",
                "stem": "Recall the approved response.",
                "question_type": "multiple_choice_single",
                "options": [
                    {
                        "id": "correct",
                        "text": "Approved response",
                        "correct": True,
                        "feedback": "Correct.",
                    },
                    {
                        "id": "incorrect",
                        "text": "Incorrect response",
                        "correct": False,
                        "feedback": "Review the material.",
                    },
                ],
                "questions": [
                    {
                        "question_id": "assessment-1",
                        "stem": "Choose one.",
                        "question_type": "multiple_choice_single",
                        "options": [
                            {"id": "a", "text": "A", "correct": True, "feedback": "Yes."},
                            {"id": "b", "text": "B", "correct": False, "feedback": "No."},
                        ],
                    },
                    {
                        "question_id": "assessment-2",
                        "stem": "Choose another.",
                        "question_type": "multiple_choice_single",
                        "options": [
                            {"id": "c", "text": "C", "correct": True, "feedback": "Yes."},
                            {"id": "d", "text": "D", "correct": False, "feedback": "No."},
                        ],
                    },
                ],
            },
        )
    )

    course, _ = ElearningCourseContentBuilder().build(brief, draft)

    checks = course["screens"]
    assert len(checks) == 2
    assert [check["question_id"] for check in checks] == [
        "assessment-1",
        "assessment-2",
    ]
    assert all(check["question_type"] == "multiple_choice_single" for check in checks)
    assert all(len(check["questions"]) == 1 for check in checks)
    assert [check["questions"][0]["question_id"] for check in checks] == [
        "assessment-1",
        "assessment-2",
    ]
    assert checks[0]["screen_id"] == "screen-check"
    assert checks[1]["screen_id"].startswith("screen-check-question-2-")
    assert [check["sequence"] for check in checks] == [1, 2]


def test_builder_inserts_video_slots_deterministically():
    """VideoSlotEntry requirements are inserted at the correct positions."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("screen-title", screen_type="title"),
            _slot_entry("screen-intro-video", "intro-video"),
            _authored_entry("screen-completion", screen_type="completion"),
        ),
    )
    draft = _full_draft(
        _title_draft("screen-title"),
        _completion_draft("screen-completion"),
    )
    builder = ElearningCourseContentBuilder()
    course_dict, report = builder.build(brief, draft)

    screens = course_dict["screens"]
    assert len(screens) == 3
    assert screens[0]["type"] == "title"
    assert screens[1]["type"] == "video_slot"
    assert screens[1]["slot_id"] == "intro-video"
    assert screens[2]["type"] == "completion"
    assert report.valid is True
    assert "intro-video" in report.discovered_slot_ids


def test_builder_preserves_requirement_order():
    """The sequence follows the requirement tuple order exactly."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-title", screen_type="title"),
            _authored_entry("s-objectives", screen_type="objectives"),
            _slot_entry("s-video", "main-video"),
            _authored_entry("s-completion", screen_type="completion"),
        ),
    )
    draft = _full_draft(
        _title_draft("s-title"),
        _objectives_draft("s-objectives"),
        _completion_draft("s-completion"),
    )
    builder = ElearningCourseContentBuilder()
    course_dict, report = builder.build(brief, draft)

    types = [s["type"] for s in course_dict["screens"]]
    assert types == ["title", "objectives", "video_slot", "completion"]


def test_builder_screen_ids_come_from_requirements():
    """screen_id in output comes from the requirement, not from the draft."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("authoritative-id", screen_type="title"),
        ),
    )
    draft = _full_draft(
        AuthoredScreenDraft(
            screen_id="authoritative-id",
            screen_type="title",
            source_scene_ids=("scene-01",),
            content={
                "course_title": "Test",
                "subtitle": "sub",
                "hook": "hook",
                "metadata": {},
            },
        )
    )
    builder = ElearningCourseContentBuilder()
    course_dict, _ = builder.build(brief, draft)
    assert course_dict["screens"][0]["screen_id"] == "authoritative-id"


def test_builder_source_scene_ids_come_from_requirements():
    """rlo_source_refs in output comes from the requirement."""
    brief = _brief(
        screen_requirements=(
            AuthoredScreenRequirement(
                screen_id="s1",
                source_scene_ids=("canonical-scene",),
                screen_type="title",
                content_direction="d",
            ),
        ),
    )
    draft = _full_draft(
        AuthoredScreenDraft(
            screen_id="s1",
            screen_type="title",
            source_scene_ids=("canonical-scene",),
            content={"course_title": "T", "subtitle": "S", "hook": "H", "metadata": {}},
        )
    )
    builder = ElearningCourseContentBuilder()
    course_dict, _ = builder.build(brief, draft)
    assert course_dict["screens"][0]["rlo_source_refs"] == ["canonical-scene"]


def test_identical_builds_produce_identical_output():
    """Same brief + draft → identical CourseContent dict."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("screen-title", screen_type="title"),
            _slot_entry("screen-video", "v1"),
        ),
    )
    draft = _full_draft(_title_draft("screen-title"))
    builder = ElearningCourseContentBuilder()
    result1, _ = builder.build(brief, draft)
    result2, _ = builder.build(brief, draft)
    assert result1 == result2


# ── Error cases ───────────────────────────────────────────────────────────────


def test_missing_authored_screen_fails():
    """Builder raises BuildError when a required screen has no draft."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-title", screen_type="title"),
            _authored_entry("s-objectives", screen_type="objectives"),
        ),
    )
    # Only one screen in the draft
    draft = _full_draft(_title_draft("s-title"))
    builder = ElearningCourseContentBuilder()
    with pytest.raises(BuildError, match="missing required authored screens"):
        builder.build(brief, draft)


def test_unexpected_authored_screen_fails():
    """Builder raises BuildError when the draft has extra screens."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-title", screen_type="title"),
        ),
    )
    draft = _full_draft(
        _title_draft("s-title"),
        _completion_draft("s-completion-extra"),  # not in requirements
    )
    builder = ElearningCourseContentBuilder()
    with pytest.raises(BuildError, match="unexpected authored screens"):
        builder.build(brief, draft)


def test_duplicate_draft_screen_ids_fails():
    """Builder raises BuildError when draft has duplicate screen_ids."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-title", screen_type="title"),
        ),
    )
    # Manually construct a draft with duplicate IDs (bypass model validator)
    d1 = _title_draft("s-title")
    # Craft draft dict and validate raw — this should fail at the draft model level
    with pytest.raises(Exception):
        ElearningCourseAuthorDraft(
            draft_id="d",
            title="T",
            authored_screens=(d1, d1),  # same object, same screen_id
        )


def test_disallowed_screen_type_fails():
    """Builder raises BuildError when draft uses a different type than required."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-title", screen_type="objectives"),  # requires objectives
        ),
    )
    # Draft uses "title" which doesn't match required "objectives"
    draft = _full_draft(_title_draft("s-title"))
    builder = ElearningCourseContentBuilder()
    with pytest.raises(BuildError, match="screen_type"):
        builder.build(brief, draft)


def test_reserved_screen_type_in_draft_fails():
    """Builder raises BuildError when draft tries to use video_slot type."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-slot-attempt", screen_type="title"),
        ),
    )
    # AuthoredScreenDraft validator should reject video_slot at construction
    with pytest.raises(Exception, match="reserved"):
        AuthoredScreenDraft(
            screen_id="s-slot-attempt",
            screen_type="video_slot",
            source_scene_ids=("scene-01",),
            content={},
        )


def test_invalid_schema_content_fails():
    """Missing required content fields raise ValidationError at parse time, not in the builder.

    The error now fires in AuthoredScreenDraft._validate_required_content_fields so the
    authoring client's retry loop can surface it to the LLM with repair feedback before the
    builder is ever reached.
    """
    from pydantic import ValidationError

    # objectives requires 'heading' AND 'objectives' list.  Omitting 'objectives' must fail
    # at AuthoredScreenDraft construction, not at builder time.
    with pytest.raises(ValidationError, match="missing required content fields"):
        AuthoredScreenDraft(
            screen_id="s-objectives",
            screen_type="objectives",
            source_scene_ids=("scene-01",),
            content={"heading": "Only a heading, no objectives list"},
        )


# ── Idempotency hash ──────────────────────────────────────────────────────────


def test_input_hash_is_deterministic():
    """Same inputs produce the same hash."""
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-title", screen_type="title"),
        ),
    )
    builder = ElearningCourseContentBuilder()
    h1 = builder.compute_input_hash(brief, "v1", "policy-v1")
    h2 = builder.compute_input_hash(brief, "v1", "policy-v1")
    assert h1 == h2


def test_different_prompt_version_gives_different_hash():
    brief = _brief(
        screen_requirements=(
            _authored_entry("s-title", screen_type="title"),
        ),
    )
    builder = ElearningCourseContentBuilder()
    h1 = builder.compute_input_hash(brief, "course_author_v1", "policy-v1")
    h2 = builder.compute_input_hash(brief, "course_author_v2", "policy-v1")
    assert h1 != h2


def test_different_brief_gives_different_hash():
    b1 = _brief(screen_requirements=(_authored_entry("s-title", screen_type="title"),))
    b2 = _brief(screen_requirements=(_authored_entry("s-objectives", screen_type="objectives"),))
    builder = ElearningCourseContentBuilder()
    h1 = builder.compute_input_hash(b1, "v1", "p1")
    h2 = builder.compute_input_hash(b2, "v1", "p1")
    assert h1 != h2


# ── CONTENT_BUILDER_VERSION sanity ────────────────────────────────────────────


def test_builder_version_is_string():
    assert isinstance(CONTENT_BUILDER_VERSION, str)
    assert CONTENT_BUILDER_VERSION.strip()


# ── scenario_branch: full builder path ───────────────────────────────────────


def _scenario_branch_brief() -> "ElearningAuthoringBrief":
    """Brief with scenario_setup, one scenario_branch, and scenario_resolution."""
    return _brief(
        screen_requirements=(
            _authored_entry("s-setup", screen_type="scenario_setup"),
            _authored_entry("s-branch-a", screen_type="scenario_branch"),
            _authored_entry("s-resolution", screen_type="scenario_resolution"),
        ),
    )


def _scenario_setup_draft() -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id="s-setup",
        screen_type="scenario_setup",
        source_scene_ids=("scene-01",),
        content={
            "title": "A Difficult Decision",
            "setup_text": "You are reviewing a vendor contract with a personal connection.",
            "prompt": "What do you do?",
            "branches": [{"id": "choice-a", "label": "Disclose the relationship"}],
        },
    )


def _scenario_branch_draft(resolution_id: str = "s-resolution") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id="s-branch-a",
        screen_type="scenario_branch",
        source_scene_ids=("scene-01",),
        content={
            "branch_id": "choice-a",
            "outcome_type": "correct",
            "feedback_title": "Good Choice",
            "feedback_body": "Disclosing the relationship was the right action.",
            "resolution_screen_id": resolution_id,
        },
    )


def _scenario_resolution_draft() -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id="s-resolution",
        screen_type="scenario_resolution",
        source_scene_ids=("scene-01",),
        content={
            "title": "Resolution",
            "body": "Disclosing conflicts protects the integrity of the process.",
        },
    )


def test_scenario_branch_builds_with_all_required_fields():
    """scenario_branch with all required fields passes builder validation end-to-end."""
    brief = _scenario_branch_brief()
    draft = _full_draft(
        _scenario_setup_draft(),
        _scenario_branch_draft(),
        _scenario_resolution_draft(),
    )
    builder = ElearningCourseContentBuilder()
    course_dict, report = builder.build(brief, draft)

    branch_screens = [s for s in course_dict["screens"] if s.get("type") == "scenario_branch"]
    assert len(branch_screens) == 1
    s = branch_screens[0]
    assert s["branch_id"] == "choice-a"
    assert s["outcome_type"] == "correct"
    assert s["resolution_screen_id"] == "s-resolution"
    assert report.valid is True


def test_scenario_branch_invalid_resolution_screen_id_fails():
    """Builder raises BuildError when resolution_screen_id points to a non-existent screen."""
    brief = _scenario_branch_brief()
    draft = _full_draft(
        _scenario_setup_draft(),
        _scenario_branch_draft(resolution_id="nonexistent-screen"),
        _scenario_resolution_draft(),
    )
    builder = ElearningCourseContentBuilder()
    with pytest.raises(BuildError, match="resolution_screen_id") as error:
        builder.build(brief, draft)
    assert error.value.screen_id == "s-branch-a"


def test_scenario_branch_cannot_resolve_to_itself():
    brief = _scenario_branch_brief()
    draft = _full_draft(
        _scenario_setup_draft(),
        _scenario_branch_draft(resolution_id="s-branch-a"),
        _scenario_resolution_draft(),
    )

    with pytest.raises(BuildError, match="must reference a scenario_resolution"):
        ElearningCourseContentBuilder().build(brief, draft)


def test_authoring_tools_assign_scenario_navigation_from_screen_sequence():
    brief = _scenario_branch_brief()
    draft = _full_draft(
        _scenario_setup_draft(),
        _scenario_branch_draft(resolution_id="s-branch-a"),
        _scenario_resolution_draft(),
    )

    hydrated = AuthoringTools(
        ElearningCourseContentBuilder()
    ).hydrate_scenario_navigation(brief, draft)

    branch = next(
        screen for screen in hydrated.authored_screens
        if screen.screen_id == "s-branch-a"
    )
    assert branch.content.resolution_screen_id == "s-resolution"
    course, report = ElearningCourseContentBuilder().build(brief, hydrated)
    assert report.valid is True
    assert next(
        screen for screen in course["screens"]
        if screen["screen_id"] == "s-branch-a"
    )["resolution_screen_id"] == "s-resolution"


def test_validation_finding_preserves_offending_screen_id():
    brief = _scenario_branch_brief()
    draft = _full_draft(
        _scenario_setup_draft(),
        _scenario_branch_draft(resolution_id="nonexistent-screen"),
        _scenario_resolution_draft(),
    )

    course, report, findings = AuthoringTools(
        ElearningCourseContentBuilder()
    ).validate_draft(brief, draft, {})

    assert course is None
    assert report is None
    assert len(findings) == 1
    assert findings[0].screen_id == "s-branch-a"
    assert findings[0].owner == FindingOwner.BUILDER
    assert findings[0].repairability == FindingRepairability.AUTOMATIC


# ── Builder does not drop required structural fields ─────────────────────────


def test_builder_preserves_all_scenario_branch_required_fields():
    """The builder must not drop any required structural fields for scenario_branch."""
    brief = _scenario_branch_brief()
    draft = _full_draft(
        _scenario_setup_draft(),
        _scenario_branch_draft(),
        _scenario_resolution_draft(),
    )
    builder = ElearningCourseContentBuilder()
    course_dict, _ = builder.build(brief, draft)

    branch = next(s for s in course_dict["screens"] if s["type"] == "scenario_branch")
    for field in ("branch_id", "outcome_type", "feedback_title", "feedback_body", "resolution_screen_id"):
        assert field in branch, f"Builder dropped required field {field!r} from scenario_branch screen"
