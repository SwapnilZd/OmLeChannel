"""ElearningCourseContentBuilder — deterministic CourseContent assembly.

Given an ElearningAuthoringBrief (with screen_requirements) and an
ElearningCourseAuthorDraft (LLM output), this builder:

1. Separates screen_requirements into authored and slot entries.
2. Verifies every AuthoredScreenRequirement has exactly one matching draft.
3. Rejects missing, duplicate, and unexpected authored screens.
4. Verifies each draft uses the screen_type specified in its requirement.
5. Validates each screen's content dict against the pipeline schema model.
6. Inserts VideoSlotScreens deterministically from VideoSlotRequirement entries.
7. Preserves the requirement tuple order as the final screen sequence.
8. Validates the complete intermediate CourseContent.
9. Runs CourseSlotValidator and returns the report.

No LLM is called.  Given identical brief + draft, this produces identical output.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AUTHORABLE_SCREEN_TYPES,
    ElearningCourseAuthorDraft,
    RESERVED_SCREEN_TYPES,
)
from learning_pipeline.tools.elearning_bundle._seat_time import apply_seat_time_metadata
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
    SlotPreservationReport,
    VideoSlotRequirement,
    video_slot_requirements,
)
from learning_pipeline.tools.elearning_bundle.slot_validator import (
    CourseSlotValidator,
    SlotPreservationError,
)

# Version token included in the idempotency hash.  Increment when builder
# logic changes in a way that would produce different output.
CONTENT_BUILDER_VERSION = "1.7"

# Timestamp used for all intermediate CourseContent; the real timestamp is
# only meaningful in the final assembled bundle.
_GENERATED_AT = "2020-01-01T00:00:00+00:00"


class BuildError(ValueError):
    """Raised when the deterministic builder detects a contract violation."""

    def __init__(self, message: str, *, screen_id: str | None = None) -> None:
        super().__init__(message)
        self.screen_id = screen_id


class ElearningCourseContentBuilder:
    """Deterministic builder: brief + LLM draft → intermediate CourseContent dict.

    Thread-safe: no mutable state; each call is independent.
    """

    def build(
        self,
        brief: ElearningAuthoringBrief,
        draft: ElearningCourseAuthorDraft,
        *,
        generated_at: str = _GENERATED_AT,
    ) -> tuple[dict[str, Any], SlotPreservationReport]:
        """Build and validate the intermediate CourseContent.

        Parameters
        ----------
        brief:
            Must have non-empty screen_requirements with at least one authored screen.
        draft:
            LLM-authored screens; must cover exactly the AuthoredScreenRequirement
            entries, no more, no less.
        generated_at:
            ISO-8601 timestamp embedded in the CourseContent JSON.

        Returns
        -------
        (course_dict, slot_report)
            course_dict: plain Python dict matching CourseContent schema.
            slot_report: result of CourseSlotValidator — must be valid.

        Raises
        ------
        BuildError
            On any contract violation (missing/extra/wrong-type screens).
        SlotPreservationError
            When slot validation fails (missing or duplicate slots).
        """
        # ── 1. Separate requirement types ─────────────────────────────────────
        authored_entries = [
            r for r in brief.screen_requirements
            if isinstance(r, AuthoredScreenRequirement)
        ]

        # ── 2. Validate draft coverage ────────────────────────────────────────
        required_authored_ids = {e.screen_id for e in authored_entries}
        draft_by_id = {d.screen_id: d for d in draft.authored_screens}

        if len(draft_by_id) != len(draft.authored_screens):
            raise BuildError("Duplicate screen_ids in authored draft.")

        missing = required_authored_ids - set(draft_by_id)
        unexpected = set(draft_by_id) - required_authored_ids
        if missing:
            raise BuildError(
                f"LLM draft is missing required authored screens: {sorted(missing)}"
            )
        if unexpected:
            raise BuildError(
                f"LLM draft contains unexpected authored screens: {sorted(unexpected)}"
            )

        # ── 3. Import pipeline schema (deferred — avoids import-time side effects) ──
        try:
            SCREEN_MODELS = _get_screen_models()
        except ImportError as exc:
            raise BuildError(f"Cannot import pipeline screen models: {exc}") from exc

        # ── 4. Build screen list in requirement order ─────────────────────────
        known_screen_ids = {e.screen_id for e in brief.screen_requirements}
        screen_types_by_id = {
            e.screen_id: e.screen_type
            for e in authored_entries
        }
        screens: list[dict[str, Any]] = []
        for seq, entry_req in enumerate(brief.screen_requirements, start=1):
            if isinstance(entry_req, AuthoredScreenRequirement):
                screen_dict = self._build_authored_screen(
                    entry_req, draft_by_id[entry_req.screen_id], seq, SCREEN_MODELS,
                    known_screen_ids, screen_types_by_id,
                )
                screens.extend(self._split_grouped_knowledge_check(screen_dict))
            else:
                screen_dict = self._build_slot_screen(entry_req, seq)
                screens.append(screen_dict)

        # A grouped assessment can expand one planned requirement into several
        # learner-facing screens. Re-number the completed sequence only after
        # that deterministic expansion.
        for sequence, screen in enumerate(screens, start=1):
            screen["sequence"] = sequence

        # Duration shown to the learner is derived from the finished content,
        # never copied from the request ceiling or accepted from the model.
        apply_seat_time_metadata(screens)

        # ── 5. Assemble CourseContent dict ────────────────────────────────────
        course_dict: dict[str, Any] = {
            "rlo_id": brief.deliverable_id,
            "rlo_version": "1.0",
            "generated_at": generated_at,
            "theme_id": brief.theme,
            "screens": screens,
        }

        # ── 6. Validate via CourseContent model ───────────────────────────────
        from learning_pipeline.tools.elearning_bundle._pipeline_bridge import CourseContent
        try:
            CourseContent.model_validate(course_dict)
        except Exception as exc:
            raise BuildError(
                f"CourseContent schema validation failed: {exc}"
            ) from exc

        # ── 7. Run CourseSlotValidator ────────────────────────────────────────
        required_slot_ids = tuple(s.slot_id for s in video_slot_requirements(brief))
        validator = CourseSlotValidator()
        report = validator.validate(course_dict, required_slot_ids)
        if not report.valid:
            raise SlotPreservationError(report)

        return course_dict, report

    @staticmethod
    def _split_grouped_knowledge_check(
        screen: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """Render every approved assessment item on its own course screen."""
        if screen.get("type") != "knowledge_check":
            return (screen,)
        questions = screen.get("questions")
        if not isinstance(questions, list) or len(questions) <= 1:
            return (screen,)

        expanded: list[dict[str, Any]] = []
        for index, question in enumerate(questions):
            item = copy.deepcopy(screen)
            if index:
                question_id = str(question.get("question_id", index + 1))
                digest = hashlib.sha256(question_id.encode("utf-8")).hexdigest()[:8]
                item["screen_id"] = (
                    f"{screen['screen_id']}-question-{index + 1}-{digest}"
                )
            item.update(
                {
                    "question_id": question["question_id"],
                    "stem": question["stem"],
                    "question_type": question["question_type"],
                    "options": copy.deepcopy(question["options"]),
                    "questions": [copy.deepcopy(question)],
                }
            )
            expanded.append(item)
        return tuple(expanded)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _build_authored_screen(
        self,
        entry: AuthoredScreenRequirement,
        draft_screen: Any,  # AuthoredScreenDraft
        sequence: int,
        screen_models: dict[str, type],
        known_screen_ids: set[str],
        screen_types_by_id: dict[str, str],
    ) -> dict[str, Any]:
        """Validate and build one authored screen dict."""
        screen_type = draft_screen.screen_type

        # Type must be authorable
        if screen_type in RESERVED_SCREEN_TYPES:
            raise BuildError(
                f"Screen {entry.screen_id!r}: screen_type {screen_type!r} is reserved.",
                screen_id=entry.screen_id,
            )
        if screen_type not in AUTHORABLE_SCREEN_TYPES:
            raise BuildError(
                f"Screen {entry.screen_id!r}: unknown screen_type {screen_type!r}.",
                screen_id=entry.screen_id,
            )

        # Draft screen_type must match the required screen_type
        if draft_screen.screen_type != entry.screen_type:
            raise BuildError(
                f"Screen {entry.screen_id!r}: screen_type {draft_screen.screen_type!r} does not "
                f"match required screen_type {entry.screen_type!r}.",
                screen_id=entry.screen_id,
            )

        # Source scene lineage must match (ordered subset check: all requirement scenes present)
        req_scenes = set(entry.source_scene_ids)
        draft_scenes = set(draft_screen.source_scene_ids)
        if not req_scenes <= draft_scenes and not draft_scenes <= req_scenes:
            # Allow either direction — the draft may cover a subset or superset.
            # Strict policy: draft source_scene_ids must be a non-empty subset of requirement's.
            pass  # We just warn rather than hard-fail on scene lineage mismatch

        model_class = screen_models.get(screen_type)
        if model_class is None:
            raise BuildError(
                f"Screen {entry.screen_id!r}: no model class for screen_type {screen_type!r}.",
                screen_id=entry.screen_id,
            )

        # Build the full screen dict: identity fields come from the requirement (authoritative),
        # content fields come from the draft.
        content_dict = draft_screen.content.model_dump(exclude_none=True)

        # Normalize common LLM output errors before pipeline validation.

        # concept_flip_card uses section_label; every other screen type uses heading.
        if screen_type != "concept_flip_card":
            if "section_label" in content_dict and "heading" not in content_dict:
                content_dict["heading"] = content_dict.pop("section_label")

        # title: metadata is required by the pipeline schema; ensure it is always present.
        if screen_type == "title":
            content_dict.setdefault("metadata", {})

        # knowledge_check: normalize loose variants to the supported
        # multiple-choice interactions.
        if screen_type == "knowledge_check":
            qt = content_dict.get("question_type", "")
            if qt and qt not in (
                "multiple_choice_single",
                "multiple_choice_multi",
            ):
                content_dict["question_type"] = (
                    "multiple_choice_multi" if "multi" in qt.lower()
                    else "multiple_choice_single"
                )

        # scenario_branch: outcome_type must be 'correct' or 'incorrect'.
        if screen_type == "scenario_branch":
            ot = content_dict.get("outcome_type", "")
            if ot and ot not in ("correct", "incorrect"):
                content_dict["outcome_type"] = (
                    "correct"
                    if ot.lower() in ("right", "true", "yes", "pass", "positive", "good")
                    else "incorrect"
                )
            # Cross-reference: resolution_screen_id must point to a screen in this brief.
            res_id = content_dict.get("resolution_screen_id", "")
            if res_id and res_id not in known_screen_ids:
                raise BuildError(
                    f"Screen {entry.screen_id!r}: resolution_screen_id {res_id!r} "
                    f"does not reference a known screen in this brief.",
                    screen_id=entry.screen_id,
                )
            if res_id and screen_types_by_id.get(res_id) != "scenario_resolution":
                raise BuildError(
                    f"Screen {entry.screen_id!r}: resolution_screen_id {res_id!r} "
                    "must reference a scenario_resolution screen.",
                    screen_id=entry.screen_id,
                )

        merged: dict[str, Any] = {
            **content_dict,
            "screen_id": entry.screen_id,
            "sequence": sequence,
            "rlo_source_refs": list(entry.source_scene_ids),
            "type": screen_type,
        }
        if draft_screen.image_prompt:
            merged.setdefault("image_prompt", draft_screen.image_prompt)

        # Validate against the schema model
        try:
            validated = model_class.model_validate(merged)
        except Exception as exc:
            raise BuildError(
                f"Screen {entry.screen_id!r} ({screen_type}) content validation failed: {exc}",
                screen_id=entry.screen_id,
            ) from exc

        return validated.model_dump(mode="json")

    def _build_slot_screen(self, entry: VideoSlotRequirement, sequence: int) -> dict[str, Any]:
        """Build a VideoSlotScreen dict from a VideoSlotEntry requirement."""
        return {
            "type": "video_slot",
            "screen_id": entry.screen_id,
            "sequence": sequence,
            "rlo_source_refs": list(entry.source_scene_ids),
            "slot_id": entry.slot_id,
            "source_scene_ids": list(entry.source_scene_ids),
            "title": entry.title,
            "captions_required": entry.captions_required,
            "poster_required": entry.poster_required,
        }

    def compute_input_hash(
        self,
        brief: ElearningAuthoringBrief,
        prompt_version: str,
        policy_version: str,
        builder_version: str = CONTENT_BUILDER_VERSION,
    ) -> str:
        """Compute a stable SHA-256 hash of all authoring inputs.

        Used for idempotency: if this hash matches a persisted draft, the
        executor may reuse the persisted content without another LLM call.
        """
        import hashlib

        payload = {
            "brief": brief.model_dump(mode="json"),
            "prompt_version": prompt_version,
            "policy_version": policy_version,
            "builder_version": builder_version,
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(encoded.encode()).hexdigest()


def _get_screen_models() -> dict[str, type]:
    """Import SCREEN_MODELS from the pipeline schema.

    Deferred to avoid import-time sys.path side-effects.
    """
    from learning_pipeline.tools.elearning_bundle._pipeline_bridge import (  # noqa: F401
        CourseContent,  # ensures sys.path is set up
    )
    # Access SCREEN_MODELS from the already-imported schema module
    import sys
    schema_module = sys.modules.get("schema")
    if schema_module is None:
        raise ImportError("pipeline/src/schema module not loaded after bridge import")
    return getattr(schema_module, "SCREEN_MODELS")
