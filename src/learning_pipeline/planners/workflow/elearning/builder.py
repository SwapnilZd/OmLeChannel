"""ElearningProductionPlanBuilder — Phase 14D.

Deterministically converts a validated ElearningProductionDraft into a
ModalityProductionPlan containing the e-learning DAG:

  elearning.course.author     ─┐
  video.avatar.render [×N]    ─┼──► elearning.bundle.assemble  (deliverable)
  video.manim.render  [×M]    ─┘

The author job and all media jobs run in parallel; the assembler job depends on
all of them.

LLM responsibilities (already done before the builder is called):
  - deciding which screens to author and their order;
  - choosing video slots and slot IDs;
  - selecting avatar / voice profiles and narration scripts;
  - writing animation directions.

Builder responsibilities (deterministic — no LLM):
  - assigning canonical job IDs;
  - constructing ElearningAuthoringBrief inputs for the author job;
  - constructing AvatarVideoRenderInput / AnimationBrief inputs per slot;
  - wiring TaskOutputInput / ListInput / ObjectInput bindings for the assembler;
  - returning the final ModalityProductionPlan.
"""
from __future__ import annotations

import json
import re

from learning_pipeline.media_validation import (
    ELEARNING_VIDEO_HEIGHT,
    ELEARNING_VIDEO_WIDTH,
)
from learning_pipeline.contracts import (
    LiteralInput,
    ListInput,
    Modality,
    ModalityPlan,
    ModalityProductionPlan,
    ObjectInput,
    ProductionJob,
    TaskOutputInput,
)
from learning_pipeline.contracts.planning import (
    AvatarMediaDirective,
    ElearningProductionDraft,
    ManimMediaDirective,
)
from learning_pipeline.tools.elearning_bundle.contracts import VideoSlotRequirement

# ── Job ID constants ───────────────────────────────────────────────────────────

AUTHOR_JOB_ID = "elearning-course-author"
ASSEMBLE_JOB_ID = "elearning-bundle-assemble"

# ── Capability IDs ─────────────────────────────────────────────────────────────

CAP_ELEARNING_AUTHOR = "elearning.course.author"
CAP_AVATAR_RENDER = "video.avatar.render"
CAP_MANIM_RENDER = "video.manim.render"
CAP_ELEARNING_ASSEMBLE = "elearning.bundle.assemble"

# ── Output keys per capability ─────────────────────────────────────────────────

_AUTHOR_OUTPUT_KEYS = ("course_json", "course_json_uri", "assets", "slot_report", "trace_uri")
_AVATAR_OUTPUT_KEYS = ("video_uri", "subtitle_uri", "subtitle_media_type", "cost_report_uri", "duration_seconds", "usage")
_MANIM_OUTPUT_KEYS = (
    "video", "video_uri", "captions", "captions_uri", "captions_media_type",
    "poster", "poster_uri", "generated_source", "render_log", "narration",
    "result_manifest", "trace_uri",
)
_ASSEMBLE_OUTPUT_KEYS = (
    "entry_html", "course_json", "asset_manifest", "bundle_zip",
    "screen_count", "video_count", "unresolved_slot_count",
)

# Default avatar render dimensions
_DEFAULT_WIDTH = ELEARNING_VIDEO_WIDTH
_DEFAULT_HEIGHT = ELEARNING_VIDEO_HEIGHT

_UNSAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9_\-]")


class ElearningProductionPlanBuilderError(ValueError):
    """Raised when the builder cannot produce a valid plan."""


def _normalize_slot_id(slot_id: str) -> str:
    """Convert a slot_id to a safe job ID suffix."""
    sanitized = _UNSAFE_CHARS_RE.sub("-", slot_id).strip("-").lower()
    if not sanitized:
        raise ElearningProductionPlanBuilderError(
            f"slot_id '{slot_id}' produces an empty job ID suffix after sanitization"
        )
    return sanitized


def _avatar_job_id(slot_id: str) -> str:
    return f"elearning-avatar-slot-{_normalize_slot_id(slot_id)}"


def _manim_job_id(slot_id: str) -> str:
    return f"elearning-manim-slot-{_normalize_slot_id(slot_id)}"


class ElearningProductionPlanBuilder:
    """Deterministic builder: ElearningProductionDraft → ModalityProductionPlan.

    The caller is responsible for validating the draft with
    ``validate_elearning_draft`` before calling ``build``.
    """

    def build(
        self,
        draft: ElearningProductionDraft,
        modality_plan: ModalityPlan | None = None,
        context_uri: str = "",
        context_hash: str = "",
    ) -> ModalityProductionPlan:
        """Convert *draft* to a ModalityProductionPlan.

        Parameters
        ----------
        draft:
            Validated ElearningProductionDraft from the planning LLM.
        modality_plan:
            ModalityPlan used to look up scene learning objectives for Manim
            briefs. May be None; the slot title is used as fallback.
        context_uri:
            Artifact URI for the resolved planning context (used in Manim briefs).
        context_hash:
            SHA-256 hash of the resolved planning context (used in Manim briefs).

        Raises:
            ElearningProductionPlanBuilderError: If any job ID collision occurs.
        """
        # Index slots by slot_id for directive lookup
        slot_by_id: dict[str, VideoSlotRequirement] = {
            r.slot_id: r for r in draft.video_slots
        }

        # Build scene objective lookup (optional)
        scene_objective: dict[str, str] = {}
        if modality_plan:
            scene_objective = {s.id: s.learning_objective for s in modality_plan.scenes}

        # Collect all source scene IDs for the plan
        all_source_ids: list[str] = []
        seen_source: set[str] = set()
        for req in draft.ordered_screens:
            for sid in req.source_scene_ids:
                if sid not in seen_source:
                    seen_source.add(sid)
                    all_source_ids.append(sid)

        # ── 1. Author job ──────────────────────────────────────────────────────
        author_job = self._build_author_job(draft, context_uri, context_hash)

        # ── 2. Media jobs ──────────────────────────────────────────────────────
        media_jobs: list[ProductionJob] = []
        media_job_ids: list[str] = []
        seen_job_ids: set[str] = set()

        for directive in (*draft.avatar_directives, *draft.manim_directives):
            slot = slot_by_id[directive.slot_id]

            if isinstance(directive, AvatarMediaDirective):
                job_id = _avatar_job_id(directive.slot_id)
                job = self._build_avatar_job(draft, directive, slot, job_id)
            else:
                assert isinstance(directive, ManimMediaDirective)
                job_id = _manim_job_id(directive.slot_id)
                learning_obj = self._resolve_learning_objective(
                    slot, scene_objective, directive
                )
                job = self._build_manim_job(
                    draft, directive, slot, job_id, learning_obj, context_uri, context_hash
                )

            if job_id in seen_job_ids:
                raise ElearningProductionPlanBuilderError(
                    f"Job ID collision: '{job_id}' produced by multiple directives"
                )
            seen_job_ids.add(job_id)
            media_jobs.append(job)
            media_job_ids.append(job_id)

        # ── 3. Assembler job ───────────────────────────────────────────────────
        video_slots = [slot_by_id[d.slot_id] for d in (*draft.avatar_directives, *draft.manim_directives)]
        assemble_job = self._build_assemble_job(
            draft, media_job_ids, video_slots
        )

        all_jobs = [author_job, *media_jobs, assemble_job]

        return ModalityProductionPlan(
            plan_id=f"pp-{draft.draft_id}",
            modality=Modality.ELEARNING,
            narrative=draft.narrative,
            jobs=tuple(all_jobs),
            deliverable_job_ids=(ASSEMBLE_JOB_ID,),
        )

    # ── Private builders ──────────────────────────────────────────────────────

    def _build_author_job(
        self,
        draft: ElearningProductionDraft,
        context_uri: str,
        context_hash: str,
    ) -> ProductionJob:
        reqs_value = [
            json.loads(req.model_dump_json()) for req in draft.ordered_screens
        ]
        return ProductionJob(
            id=AUTHOR_JOB_ID,
            source_scene_ids=tuple(
                sid
                for req in draft.ordered_screens
                for sid in req.source_scene_ids
            ),
            capability=CAP_ELEARNING_AUTHOR,
            depends_on=(),
            inputs={
                "deliverable_id": LiteralInput(value=draft.draft_id),
                "source_plan_id": LiteralInput(value=draft.source_modality_plan_id),
                "resolved_context_uri": LiteralInput(value=context_uri),
                "resolved_context_sha256": LiteralInput(value=context_hash),
                "screen_requirements": LiteralInput(value=reqs_value),
                "theme": LiteralInput(value=draft.theme or "deloitte-green"),
                "brand_contract": LiteralInput(value={}),
                "accessibility_requirements": LiteralInput(value=[]),
                "authoring_direction": LiteralInput(value=draft.course_authoring_direction),
            },
            output_keys=_AUTHOR_OUTPUT_KEYS,
        )

    def _build_avatar_job(
        self,
        draft: ElearningProductionDraft,
        directive: AvatarMediaDirective,
        slot: VideoSlotRequirement,
        job_id: str,
    ) -> ProductionJob:
        scene_value = {
            "scene_id": slot.slot_id,
            "source_scene_ids": list(slot.source_scene_ids),
            "title": slot.title,
            "script": directive.narration_script,
            "background": {"kind": "color", "color": "#1A1A2E"},
            "estimated_duration_seconds": float(directive.target_duration_seconds or 60),
        }
        return ProductionJob(
            id=job_id,
            source_scene_ids=slot.source_scene_ids,
            capability=CAP_AVATAR_RENDER,
            depends_on=(),
            inputs={
                "deliverable_id": LiteralInput(value=f"{draft.draft_id}-{_normalize_slot_id(slot.slot_id)}"),
                "scenes": LiteralInput(value=[scene_value]),
                "avatar": LiteralInput(value={"profile": directive.avatar_profile}),
                "voice": LiteralInput(value={"profile": directive.voice_profile, "speed": 1.0}),
                "dimensions": LiteralInput(value={"width": _DEFAULT_WIDTH, "height": _DEFAULT_HEIGHT}),
                "captions": LiteralInput(value=slot.captions_required),
            },
            output_keys=_AVATAR_OUTPUT_KEYS,
        )

    def _build_manim_job(
        self,
        draft: ElearningProductionDraft,
        directive: ManimMediaDirective,
        slot: VideoSlotRequirement,
        job_id: str,
        learning_objective: str,
        context_uri: str,
        context_hash: str,
    ) -> ProductionJob:
        return ProductionJob(
            id=job_id,
            source_scene_ids=slot.source_scene_ids,
            capability=CAP_MANIM_RENDER,
            depends_on=(),
            inputs={
                "animation_id": LiteralInput(value=slot.slot_id),
                "source_scene_ids": LiteralInput(value=list(slot.source_scene_ids)),
                "learning_objective": LiteralInput(value=learning_objective),
                "teaching_purpose": LiteralInput(value=directive.animation_direction),
                "visual_direction": LiteralInput(value=directive.animation_direction),
                "narration_script": LiteralInput(value=directive.narration_script),
                "voice_profile": LiteralInput(value=directive.voice_profile),
                "resolved_context_uri": LiteralInput(value=context_uri),
                "resolved_context_sha256": LiteralInput(value=context_hash),
                "target_duration_seconds": LiteralInput(value=directive.target_duration_seconds),
                "quality_profile": LiteralInput(value="standard"),
                "brand_contract": LiteralInput(value={}),
                "accessibility_requirements": LiteralInput(value=[]),
            },
            output_keys=_MANIM_OUTPUT_KEYS,
        )

    def _build_assemble_job(
        self,
        draft: ElearningProductionDraft,
        media_job_ids: list[str],
        video_slots: list[VideoSlotRequirement],
    ) -> ProductionJob:
        depends_on = (AUTHOR_JOB_ID, *media_job_ids)

        # Build required_slots and video_insertions together so directive type
        # drives both structures consistently.
        all_directives = (*draft.avatar_directives, *draft.manim_directives)
        required_slots_value = []
        insertion_objects = []
        for directive, slot, job_id in zip(all_directives, video_slots, media_job_ids):
            if isinstance(directive, AvatarMediaDirective):
                captions_uri = (
                    TaskOutputInput(task_id=job_id, output_key="subtitle_uri")
                    if slot.captions_required
                    else LiteralInput(value=None)
                )
                captions_media_type = (
                    TaskOutputInput(task_id=job_id, output_key="subtitle_media_type")
                    if slot.captions_required
                    else LiteralInput(value=None)
                )
                required_slots_value.append(json.loads(slot.model_dump_json()))
            else:
                assert isinstance(directive, ManimMediaDirective)
                # Both fields are driven by the task output so they stay
                # consistent at runtime (both set or both None).
                captions_uri = TaskOutputInput(task_id=job_id, output_key="captions_uri")
                captions_media_type = TaskOutputInput(
                    task_id=job_id, output_key="captions_media_type"
                )
                required_slots_value.append(json.loads(slot.model_dump_json()))

            insertion_objects.append(ObjectInput(fields={
                "slot_id": LiteralInput(value=slot.slot_id),
                "source_scene_ids": LiteralInput(value=list(slot.source_scene_ids)),
                "video_uri": TaskOutputInput(task_id=job_id, output_key="video_uri"),
                "video_media_type": LiteralInput(value="video/mp4"),
                "captions_uri": captions_uri,
                "captions_media_type": captions_media_type,
                "poster_uri": LiteralInput(value=None),
                "poster_media_type": LiteralInput(value=None),
                "title": LiteralInput(value=slot.title),
            }))

        return ProductionJob(
            id=ASSEMBLE_JOB_ID,
            source_scene_ids=(),
            capability=CAP_ELEARNING_ASSEMBLE,
            depends_on=depends_on,
            inputs={
                "deliverable_id": LiteralInput(value=draft.draft_id),
                "course_json_uri": TaskOutputInput(
                    task_id=AUTHOR_JOB_ID, output_key="course_json_uri"
                ),
                "author_assets": TaskOutputInput(
                    task_id=AUTHOR_JOB_ID, output_key="assets"
                ),
                "required_slots": LiteralInput(value=required_slots_value),
                "video_insertions": ListInput(items=tuple(insertion_objects)),
                "output_filename": LiteralInput(value="index.html"),
            },
            output_keys=_ASSEMBLE_OUTPUT_KEYS,
        )

    @staticmethod
    def _resolve_learning_objective(
        slot: VideoSlotRequirement,
        scene_objective: dict[str, str],
        directive: ManimMediaDirective,
    ) -> str:
        for sid in slot.source_scene_ids:
            obj = scene_objective.get(sid)
            if obj:
                return obj
        return slot.title
