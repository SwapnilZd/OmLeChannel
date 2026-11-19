"""FakeElearningCourseAuthorExecutor — no LLM, no network, deterministic output.

Validates ElearningAuthoringBrief (same contract as the future real executor),
writes a deterministic intermediate CourseContent JSON with:
- One TitleScreen
- One ObjectivesScreen
- One VideoSlotScreen per required slot
- One KeyTakeawaysScreen
- One CompletionScreen
- One generated image asset (1×1 transparent PNG)

Runs the real CourseSlotValidator and fails the task if required slots are missing.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from learning_pipeline.runtime.artifact_store import ArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.elearning_bundle.contracts import (
    BundleAssetRef,
    ElearningAuthoringBrief,
    ElearningAuthorOutput,
    VideoSlotRequirement,
    video_slot_requirements,
)
from learning_pipeline.tools.elearning_bundle.slot_validator import (
    CourseSlotValidator,
    SlotPreservationError,
)
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError

# 1×1 transparent PNG — 68 bytes, no external dependencies.
_FAKE_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

_FAKE_IMAGE_PATH = "assets/generated-course-image.png"


def _build_fake_course_dict(brief: ElearningAuthoringBrief) -> dict[str, Any]:
    """Build a deterministic intermediate CourseContent as a plain Python dict."""
    screens: list[dict[str, Any]] = []
    seq = 1

    screens.append({
        "type": "title",
        "screen_id": "screen-title",
        "sequence": seq,
        "rlo_source_refs": ["fake-rlo-001"],
        "course_title": f"{brief.deliverable_id} — E-Learning Course",
        "subtitle": "A structured learning experience",
        "hook": "Explore the key concepts through interactive slides.",
        "image_path": _FAKE_IMAGE_PATH,
        "metadata": {"duration": "15 min", "level": "Intermediate"},
    })
    seq += 1

    screens.append({
        "type": "objectives",
        "screen_id": "screen-objectives",
        "sequence": seq,
        "rlo_source_refs": ["fake-rlo-001"],
        "heading": "Learning Objectives",
        "objectives": [
            "Understand core concepts introduced in this module.",
            "Apply the learning to real-world scenarios.",
            "Demonstrate competency through interactive exercises.",
        ],
    })
    seq += 1

    for slot in video_slot_requirements(brief):
        screens.append({
            "type": "video_slot",
            "screen_id": slot.screen_id,
            "sequence": seq,
            "rlo_source_refs": list(slot.source_scene_ids) or ["fake-rlo-001"],
            "slot_id": slot.slot_id,
            "source_scene_ids": list(slot.source_scene_ids),
            "title": slot.title,
            "captions_required": slot.captions_required,
            "poster_required": slot.poster_required,
        })
        seq += 1

    screens.append({
        "type": "key_takeaways",
        "screen_id": "screen-takeaways",
        "sequence": seq,
        "rlo_source_refs": ["fake-rlo-001"],
        "heading": "Key Takeaways",
        "takeaways": [
            "This module introduced the core framework.",
            "Video segments reinforced the key concepts.",
            "Apply these principles in your daily work.",
        ],
    })
    seq += 1

    screens.append({
        "type": "completion",
        "screen_id": "screen-completion",
        "sequence": seq,
        "rlo_source_refs": ["fake-rlo-001"],
        "heading": "Module Complete",
        "message": "You have completed this learning module.",
        "skills_reinforced": ["Core concept application", "Video comprehension"],
    })

    return {
        "rlo_id": brief.deliverable_id,
        "rlo_version": "1.0",
        "generated_at": "2020-01-01T00:00:00+00:00",
        "theme_id": brief.theme,
        "screens": screens,
    }


class FakeElearningCourseAuthorExecutor:
    """Fake elearning.course.author executor.

    Validates ElearningAuthoringBrief, produces a deterministic intermediate
    CourseContent JSON with VideoSlotScreens, runs CourseSlotValidator, and
    returns a valid ElearningAuthorOutput.  No LLM or network calls.

    Parameters
    ----------
    artifact_store:
        Where to persist artifacts.  Required to generate artifact URIs.
    write_preview_html:
        If True, also renders a preview HTML (slots shown as placeholders).
    """

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        write_preview_html: bool = False,
    ) -> None:
        self._store = artifact_store
        self._write_preview = write_preview_html

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # 1. Validate input contract
        try:
            brief = ElearningAuthoringBrief.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid elearning.course.author input: {exc}"
            ) from exc

        wf_id = context.workflow_id
        ns = f"elearning/{wf_id}"

        # 2. Build deterministic course dict
        course_dict = _build_fake_course_dict(brief)
        course_bytes = json.dumps(course_dict, indent=2, ensure_ascii=False).encode("utf-8")

        # 3. Run slot validator
        required_ids = tuple(s.slot_id for s in video_slot_requirements(brief))
        validator = CourseSlotValidator()
        report = validator.validate(course_dict, required_ids)
        if not report.valid:
            raise SlotPreservationError(report)

        # 4. Publish artifacts
        assets_list = []
        preview_ref = None

        if self._store is not None:
            # Course JSON
            course_ref = await self._store.put_bytes(
                namespace=ns,
                name=f"{brief.deliverable_id}.course.json",
                data=course_bytes,
                media_type="application/json",
            )
            course_json_uri = course_ref.uri

            # Generated image asset
            img_ref = await self._store.put_bytes(
                namespace=ns,
                name="assets/generated-course-image.png",
                data=_FAKE_PNG_BYTES,
                media_type="image/png",
            )
            assets_list.append(
                BundleAssetRef(logical_path=_FAKE_IMAGE_PATH, artifact=img_ref)
            )

            # Optional preview HTML
            if self._write_preview:
                from learning_pipeline.tools.elearning_bundle._pipeline_bridge import (
                    CourseContent,
                    render_course_html,
                )
                course_obj = CourseContent.model_validate(course_dict)
                preview_html = render_course_html(course_obj, theme_id=brief.theme)
                preview_bytes = preview_html.encode("utf-8")
                preview_ref = await self._store.put_bytes(
                    namespace=ns,
                    name=f"{brief.deliverable_id}-preview.html",
                    data=preview_bytes,
                    media_type="text/html",
                )
        else:
            # No store — use fake:// URIs for unit tests that skip artifact persistence
            course_ref_uri = f"fake://elearning/{wf_id}/{brief.deliverable_id}.course.json"
            sha = hashlib.sha256(course_bytes).hexdigest()
            from learning_pipeline.runtime.artifact_store import ArtifactRef
            course_ref = ArtifactRef(
                uri=course_ref_uri,
                media_type="application/json",
                sha256=sha,
                size_bytes=len(course_bytes),
            )
            course_json_uri = course_ref_uri

            img_sha = hashlib.sha256(_FAKE_PNG_BYTES).hexdigest()
            img_ref = ArtifactRef(
                uri=f"fake://elearning/{wf_id}/assets/generated-course-image.png",
                media_type="image/png",
                sha256=img_sha,
                size_bytes=len(_FAKE_PNG_BYTES),
            )
            assets_list.append(
                BundleAssetRef(logical_path=_FAKE_IMAGE_PATH, artifact=img_ref)
            )

        # 5. Validate and return output
        try:
            output = ElearningAuthorOutput(
                course_json=course_ref,
                course_json_uri=course_json_uri,
                assets=tuple(assets_list),
                slot_report=report,
                preview_html=preview_ref,
                trace_uri=None,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{context.task_id}] ElearningAuthorOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()
