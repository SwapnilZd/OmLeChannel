"""
PodcastProductionPlanBuilder — Phase 9.

Deterministically converts a validated PodcastProductionDraft into a
ModalityProductionPlan.

LLM responsibilities (already done before this builder is called):
  - deciding what each segment says;
  - choosing speakers;
  - mapping scenes to segments;
  - setting pause durations.

Builder responsibilities (deterministic — no LLM):
  - assigning job IDs derived from segment IDs;
  - creating one speech.synthesize ProductionJob per segment;
  - creating exactly one audio.assemble ProductionJob;
  - wiring assembly dependencies on every speech job;
  - constructing ListInput / ObjectInput bindings for the assembly fan-in;
  - ordering assembly segments to match draft narrative order;
  - returning the final ModalityProductionPlan.

Given the same validated draft the builder ALWAYS produces the same plan.
"""
from __future__ import annotations

import re

from learning_pipeline.contracts import (
    LiteralInput,
    ListInput,
    Modality,
    ModalityProductionPlan,
    ObjectInput,
    ProductionJob,
    TaskOutputInput,
)
from learning_pipeline.contracts.planning import PodcastProductionDraft

_UNSAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9_\-]")

ASSEMBLY_JOB_ID = "assemble-podcast"


class PodcastPlanBuilderError(ValueError):
    """Raised when the builder cannot produce a valid plan."""


def _sanitize_job_id(segment_id: str) -> str:
    """Convert a segment_id to a safe job ID (lowercase, hyphens for spaces/underscores)."""
    sanitized = _UNSAFE_CHARS_RE.sub("-", segment_id).strip("-").lower()
    if not sanitized:
        raise PodcastPlanBuilderError(
            f"segment_id '{segment_id}' produces an empty job ID after sanitization"
        )
    return sanitized


class PodcastProductionPlanBuilder:
    """Deterministic builder: PodcastProductionDraft → ModalityProductionPlan.

    The caller is responsible for validating the draft with
    ``validate_podcast_draft`` before calling ``build``.
    """

    def build(
        self,
        draft: PodcastProductionDraft,
    ) -> ModalityProductionPlan:
        """Convert *draft* to a ModalityProductionPlan.

        Raises:
            PodcastPlanBuilderError: If segment IDs produce colliding job IDs
                after sanitization.
        """
        # 1. Derive deterministic job IDs for each speech segment
        job_ids: list[str] = []
        seen_job_ids: set[str] = set()
        for seg in draft.segments:
            job_id = _sanitize_job_id(seg.segment_id)
            if job_id in seen_job_ids:
                raise PodcastPlanBuilderError(
                    f"Segment IDs '{seg.segment_id}' and another segment produce "
                    f"the same job ID '{job_id}' after sanitization.  "
                    "Ensure segment_ids are distinct after lowercasing and "
                    "replacing non-alphanumeric characters with hyphens."
                )
            seen_job_ids.add(job_id)
            job_ids.append(job_id)

        # 2. Create one speech.synthesize ProductionJob per segment
        speech_jobs: list[ProductionJob] = []
        for seg, job_id in zip(draft.segments, job_ids):
            speech_jobs.append(ProductionJob(
                id=job_id,
                source_scene_ids=seg.source_scene_ids,
                capability="speech.synthesize",
                depends_on=(),
                inputs={
                    "text": LiteralInput(value=seg.text),
                    "speaker": LiteralInput(value=seg.speaker),
                    "line_id": LiteralInput(value=job_id),
                    "pause_after_seconds": LiteralInput(value=seg.pause_after_seconds),
                },
                output_keys=("audio_uri", "usage"),
            ))

        # 3. Build the assembly fan-in using ListInput of ObjectInput bindings
        #    (Phase 8 recursive bindings — preserves draft narrative order)
        segment_bindings = tuple(
            ObjectInput(fields={
                "segment_id": LiteralInput(value=job_id),
                "audio_uri": TaskOutputInput(task_id=job_id, output_key="audio_uri"),
                "speaker": LiteralInput(value=seg.speaker),
                "pause_after_seconds": LiteralInput(value=seg.pause_after_seconds),
                "usage": TaskOutputInput(task_id=job_id, output_key="usage"),
            })
            for seg, job_id in zip(draft.segments, job_ids)
        )

        assembly_inputs: dict = {
            "deliverable_id": LiteralInput(value=draft.draft_id),
            "segments": ListInput(items=segment_bindings),
            "default_gap_seconds": LiteralInput(value=draft.default_gap_seconds),
        }
        if draft.output_filename:
            assembly_inputs["output_filename"] = LiteralInput(
                value=draft.output_filename
            )

        # 4. Create the single assembly job (depends on ALL speech jobs)
        assembly_job = ProductionJob(
            id=ASSEMBLY_JOB_ID,
            source_scene_ids=(),
            capability="audio.assemble",
            depends_on=tuple(job_ids),
            inputs=assembly_inputs,
            output_keys=("audio_uri", "costs_uri"),
        )

        return ModalityProductionPlan(
            plan_id=f"pp-{draft.draft_id}",
            modality=Modality.PODCAST,
            narrative=draft.narrative_summary,
            jobs=(*speech_jobs, assembly_job),
            deliverable_job_ids=(ASSEMBLY_JOB_ID,),
        )
