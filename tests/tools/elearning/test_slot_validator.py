"""Tests for CourseSlotValidator and SlotPreservationError."""
from __future__ import annotations

import pytest

from learning_pipeline.tools.elearning_bundle.slot_validator import (
    CourseSlotValidator,
    SlotPreservationError,
)


def _course(slot_ids: list[str], extra_screens: list[dict] | None = None) -> dict:
    screens = [
        {
            "type": "video_slot",
            "screen_id": f"screen-{sid}",
            "sequence": i + 1,
            "rlo_source_refs": ["rlo-1"],
            "slot_id": sid,
        }
        for i, sid in enumerate(slot_ids)
    ]
    if extra_screens:
        screens.extend(extra_screens)
    return {"screens": screens}


V = CourseSlotValidator()


# ── Happy path ────────────────────────────────────────────────────────────────


def test_all_required_slots_present():
    report = V.validate(_course(["a", "b"]), ("a", "b"))
    assert report.valid is True
    assert set(report.discovered_slot_ids) == {"a", "b"}
    assert report.missing_slot_ids == ()
    assert report.duplicate_slot_ids == ()


def test_no_required_slots_and_none_discovered():
    report = V.validate({"screens": []}, ())
    assert report.valid is True


def test_extra_slots_not_invalid():
    report = V.validate(_course(["a", "b"]), ("a",))
    assert report.valid is True
    assert "b" in report.unexpected_slot_ids


# ── Missing / duplicate ───────────────────────────────────────────────────────


def test_missing_required_slot():
    report = V.validate(_course(["a"]), ("a", "b"))
    assert report.valid is False
    assert "b" in report.missing_slot_ids


def test_duplicate_slot_id():
    course = _course(["a", "a"])
    report = V.validate(course, ("a",))
    assert report.valid is False
    assert "a" in report.duplicate_slot_ids


def test_both_missing_and_duplicate():
    course = _course(["x", "x"])
    report = V.validate(course, ("x", "missing"))
    assert report.valid is False
    assert "missing" in report.missing_slot_ids
    assert "x" in report.duplicate_slot_ids


# ── Non-slot screens are ignored ──────────────────────────────────────────────


def test_non_slot_screens_ignored():
    title_screen = {"type": "title", "screen_id": "screen-title", "sequence": 1, "rlo_source_refs": ["rlo-1"]}
    course = _course(["slot-a"], extra_screens=[title_screen])
    report = V.validate(course, ("slot-a",))
    assert report.valid is True
    assert len(report.discovered_slot_ids) == 1


# ── SlotPreservationError ─────────────────────────────────────────────────────


def test_slot_preservation_error_carries_report():
    from learning_pipeline.tools.elearning_bundle.contracts import SlotPreservationReport
    report = SlotPreservationReport.build(("a",), [])
    exc = SlotPreservationError(report)
    assert exc.report is report
    assert "missing" in str(exc).lower()


def test_validator_raises_when_invalid():
    course = _course([])
    report = V.validate(course, ("required-slot",))
    assert report.valid is False
    exc = SlotPreservationError(report)
    assert "required-slot" in str(exc)


# ── Malformed course dict ─────────────────────────────────────────────────────


def test_missing_screens_key_treated_as_empty():
    report = V.validate({}, ("a",))
    assert report.valid is False
    assert "a" in report.missing_slot_ids


def test_non_dict_screens_skipped():
    course = {"screens": ["not-a-dict", None, 42]}
    report = V.validate(course, ())
    assert report.valid is True
    assert report.discovered_slot_ids == ()
