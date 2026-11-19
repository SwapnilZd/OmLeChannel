"""
VideoProductionPlanBuilder — Phase 13B.

Deterministically converts a validated VideoProductionDraft into a
ModalityProductionPlan.

LLM responsibilities (already done before this builder is called):
  - writing the final spoken narration for every render scene;
  - selecting approved logical avatar and voice profiles;
  - choosing background treatments;
  - allocating scene timing;
  - mapping modality scenes to render scenes.

Builder responsibilities (deterministic — no LLM):
  - creating one video.avatar.render ProductionJob;
  - generating a deterministic job ID;
  - collecting all source-scene IDs into the job;
  - assembling AvatarVideoScene dicts from draft scenes;
  - resolving ExistingAssetBackgroundDraft asset IDs to artifact URIs;
  - wrapping every input in a LiteralInput binding;
  - assigning the standard output keys from the capability manifest;
  - marking the job as the deliverable.

Given the same validated draft and asset catalog, the builder ALWAYS produces
the same ModalityProductionPlan.
"""
from __future__ import annotations

from learning_pipeline.contracts import (
    LiteralInput,
    Modality,
    ModalityProductionPlan,
    ProductionJob,
)
from learning_pipeline.contracts.planning import (
    VideoBackgroundDraft,
    VideoProductionDraft,
)

RENDER_JOB_ID = "render-avatar-video"
RENDER_CAPABILITY = "video.avatar.render"
OUTPUT_KEYS = ("video_uri", "subtitle_uri", "cost_report_uri", "duration_seconds", "usage")


class VideoProductionPlanBuilderError(ValueError):
    """Raised when the builder cannot produce a valid plan."""


class VideoProductionPlanBuilder:
    """Deterministic builder: VideoProductionDraft → ModalityProductionPlan.

    The caller is responsible for validating the draft with
    ``validate_video_draft`` before calling ``build``.

    Parameters
    ----------
    asset_catalog:
        Mapping of logical asset IDs to artifact URIs.  Required only when
        the draft includes ExistingAssetBackgroundDraft backgrounds.
        For Phase 13B (solid-colour backgrounds only) this may be empty.
    """

    def __init__(
        self,
        asset_catalog: dict[str, str] | None = None,
    ) -> None:
        self._asset_catalog: dict[str, str] = asset_catalog or {}

    def build(self, draft: VideoProductionDraft) -> ModalityProductionPlan:
        """Convert *draft* to a ModalityProductionPlan.

        Raises:
            VideoProductionPlanBuilderError: If an asset ID cannot be resolved.
        """
        scenes_value = self._build_scenes_value(draft)

        # Collect unique source-scene IDs in order of appearance
        source_ids: list[str] = []
        seen: set[str] = set()
        for s in draft.scenes:
            for sid in s.source_scene_ids:
                if sid not in seen:
                    seen.add(sid)
                    source_ids.append(sid)

        render_job = ProductionJob(
            id=RENDER_JOB_ID,
            source_scene_ids=tuple(source_ids),
            capability=RENDER_CAPABILITY,
            depends_on=(),
            inputs={
                "deliverable_id": LiteralInput(value=draft.draft_id),
                "scenes": LiteralInput(value=scenes_value),
                "avatar": LiteralInput(value={"profile": draft.avatar_profile}),
                "voice": LiteralInput(
                    value={"profile": draft.voice_profile, "speed": 1.0}
                ),
                "dimensions": LiteralInput(
                    value={"width": draft.width, "height": draft.height}
                ),
                "captions": LiteralInput(value=draft.captions),
            },
            output_keys=OUTPUT_KEYS,
        )

        return ModalityProductionPlan(
            plan_id=f"pp-{draft.draft_id}",
            modality=Modality.VIDEO,
            narrative=draft.narrative_summary,
            jobs=(render_job,),
            deliverable_job_ids=(RENDER_JOB_ID,),
        )

    def _build_scenes_value(self, draft: VideoProductionDraft) -> list[dict]:
        """Convert AvatarVideoSceneDraft objects to serialisable dicts."""
        result: list[dict] = []
        for scene in draft.scenes:
            background = self._resolve_background(scene)
            result.append({
                "scene_id": scene.scene_id,
                "source_scene_ids": list(scene.source_scene_ids),
                "title": scene.title,
                "script": scene.script,
                "background": background,
                "estimated_duration_seconds": scene.estimated_duration_seconds,
            })
        return result

    def _resolve_background(self, scene) -> dict:
        bg = scene.background
        if bg.kind == "color":
            return {"kind": "color", "color": bg.color}
        if bg.kind == "existing_asset":
            artifact_uri = self._asset_catalog.get(bg.asset_id)
            if artifact_uri is None:
                raise VideoProductionPlanBuilderError(
                    f"Asset '{bg.asset_id}' in scene '{scene.scene_id}' is not "
                    "in the asset catalog; cannot resolve to an artifact URI"
                )
            return {"kind": "image", "artifact_uri": artifact_uri}
        raise VideoProductionPlanBuilderError(
            f"Unknown background kind: '{bg.kind}'"
        )
