"""CourseSlotValidator — deterministic slot-preservation check.

Used at two points:
1. Immediately after elearning.course.author produces its CourseContent JSON.
2. Defensively inside elearning.bundle.assemble before any file is written.

Both callers fail hard when report.valid is False for any required slot.
"""
from __future__ import annotations

from learning_pipeline.tools.elearning_bundle.contracts import SlotPreservationReport


class CourseSlotValidator:
    """Validates that VideoSlotScreens in a CourseContent dict match a required set.

    Accepts a plain Python dict (the deserialized CourseContent) so that this
    validator does not import from pipeline/src at definition time.  The bridge
    module handles pipeline imports in the executor.
    """

    def validate(
        self,
        course_dict: dict,
        required_slot_ids: tuple[str, ...],
    ) -> SlotPreservationReport:
        """Scan course_dict.screens for VideoSlotScreens and compare to required_slot_ids.

        Parameters
        ----------
        course_dict:
            Deserialized CourseContent as a plain dict (e.g. from json.loads()).
        required_slot_ids:
            The stable slot IDs that must appear exactly once.

        Returns
        -------
        SlotPreservationReport
            A structured report.  Callers should fail the task when report.valid is False.
        """
        screens = course_dict.get("screens", [])
        discovered: list[str] = [
            s["slot_id"]
            for s in screens
            if isinstance(s, dict) and s.get("type") == "video_slot"
        ]
        return SlotPreservationReport.build(required_slot_ids, discovered)


class SlotPreservationError(RuntimeError):
    """Raised when a required slot is missing or duplicated in an authoring output."""

    def __init__(self, report: SlotPreservationReport) -> None:
        self.report = report
        parts: list[str] = []
        if report.missing_slot_ids:
            parts.append(f"missing slots: {sorted(report.missing_slot_ids)}")
        if report.duplicate_slot_ids:
            parts.append(f"duplicate slots: {sorted(report.duplicate_slot_ids)}")
        super().__init__(f"Slot preservation failed — {'; '.join(parts)}")
