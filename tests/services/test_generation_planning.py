from pathlib import Path

from learning_pipeline.config import build_elearning_reference_registry
from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
import pytest
from learning_pipeline.repository import FileRLORepository
from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.persistence import FileRunStateStore
from learning_pipeline.runtime.runner import DAGRunner
from learning_pipeline.services.generation_planning import GenerationPlanningService
from learning_pipeline.contracts.format_selection import SelectionBasis


_ROOT = Path(__file__).parents[2]


_HEYGEN_PROFILE_VARS = (
    "HEYGEN_AVATAR_PROFILE_DEFAULT_INSTRUCTOR_ID",
    "HEYGEN_VOICE_PROFILE_DEFAULT_INSTRUCTOR_ID",
    "HEYGEN_AVATAR_PROFILE_DEFAULT_NARRATOR_ID",
    "HEYGEN_VOICE_PROFILE_DEFAULT_NARRATOR_ID",
)


def _real_service(tmp_path) -> GenerationPlanningService:
    return GenerationPlanningService(
        FileRLORepository(_ROOT / "examples/reference/rlos"),
        trace_root=tmp_path / "traces",
        artifact_root=tmp_path / "artifacts",
        mode="real",
    )


def test_real_generation_excludes_avatar_without_heygen_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    service = _real_service(tmp_path)

    assert "video.avatar.render" not in service._available_capabilities
    assert "video.manim.render" in service._available_capabilities


def test_real_generation_excludes_avatar_without_configured_profiles(
    tmp_path, monkeypatch
):
    """A key alone is not enough — planning must not offer avatar scenes a
    deployment cannot resolve to an avatar+voice profile pair."""
    monkeypatch.setenv("HEYGEN_API_KEY", "test-key")
    for var in _HEYGEN_PROFILE_VARS:
        monkeypatch.delenv(var, raising=False)
    service = _real_service(tmp_path)

    assert "video.avatar.render" not in service._available_capabilities


def test_real_generation_includes_avatar_with_key_and_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("HEYGEN_API_KEY", "test-key")
    monkeypatch.setenv("HEYGEN_AVATAR_PROFILE_DEFAULT_INSTRUCTOR_ID", "avatar-1")
    monkeypatch.setenv("HEYGEN_VOICE_PROFILE_DEFAULT_INSTRUCTOR_ID", "voice-1")
    service = _real_service(tmp_path)

    assert "video.avatar.render" in service._available_capabilities


def test_real_elearning_planner_offers_only_configured_profiles(tmp_path, monkeypatch):
    """The workflow planner's approved avatar/voice profile sets must mirror
    the deployment's environment — never the planner's static defaults, which
    also list profiles (e.g. default_narrator) that may not be configured."""
    from types import SimpleNamespace

    monkeypatch.setenv("LITE_LLM_BASE_URL", "http://litellm.test:4000")
    monkeypatch.setenv("LITE_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("HEYGEN_API_KEY", "test-key")
    monkeypatch.setenv("HEYGEN_AVATAR_PROFILE_DEFAULT_INSTRUCTOR_ID", "avatar-1")
    monkeypatch.setenv("HEYGEN_VOICE_PROFILE_DEFAULT_INSTRUCTOR_ID", "voice-1")
    monkeypatch.delenv("HEYGEN_AVATAR_PROFILE_DEFAULT_NARRATOR_ID", raising=False)
    monkeypatch.delenv("HEYGEN_VOICE_PROFILE_DEFAULT_NARRATOR_ID", raising=False)
    service = _real_service(tmp_path)

    planner = service._build_workflow_planner(
        None, SimpleNamespace(modality=Modality.ELEARNING)
    )

    assert planner._approved_avatar_profiles == frozenset({"default_instructor"})
    assert planner._approved_voice_profiles == frozenset({"default_instructor"})


async def test_reference_generation_plans_and_executes_downloadable_course(tmp_path):
    blueprint = CourseBlueprint.model_validate_json(
        (_ROOT / "examples/reference/podcast/course_blueprint.json").read_text()
    )
    artifact_root = tmp_path / "artifacts"
    service = GenerationPlanningService(
        FileRLORepository(_ROOT / "examples/reference/rlos"),
        trace_root=tmp_path / "traces",
        artifact_root=artifact_root,
        mode="reference",
    )

    planned = await service.plan_generation(
        blueprint,
        request_id="planning-test",
        workflow_id="workflow-test",
    )

    assert planned.modality_planning.modality_plan.modality == (
        planned.format_selection.decision.selected_modality
    )
    assert planned.workflow_planning.build_plan.workflow_id == "workflow-test"
    assert {
        ref.rlo_id for ref in planned.modality_planning.modality_plan.scenes[0].source_content
    } <= {ref.rlo_id for ref in blueprint.ordered_rlo_refs}

    result = await DAGRunner(
        build_elearning_reference_registry(artifact_root),
        FileRunStateStore(tmp_path / "runs"),
    ).run(planned.workflow_planning.build_plan)
    zip_ref = result.deliverables[0].outputs["bundle_zip"]
    payload = await FileArtifactStore(artifact_root).get_bytes(zip_ref["uri"])
    assert zip_ref["media_type"] == "application/zip"
    assert payload.startswith(b"PK")


async def test_explicit_commissioning_modality_is_honored_when_feasible(tmp_path):
    blueprint = CourseBlueprint.model_validate_json(
        (_ROOT / "examples/reference/podcast/course_blueprint.json").read_text()
    )
    service = GenerationPlanningService(
        FileRLORepository(_ROOT / "examples/reference/rlos"),
        artifact_root=tmp_path / "artifacts",
        mode="reference",
    )

    result = await service.select_format(
        blueprint,
        request_id="explicit-elearning",
        requested_modality=Modality.ELEARNING,
    )

    assert result.decision.selected_modality == Modality.ELEARNING
    assert result.decision.basis == SelectionBasis.EXPLICIT


@pytest.mark.parametrize("modality", tuple(Modality))
async def test_reference_generation_builds_each_deployed_modality(tmp_path, modality):
    blueprint = CourseBlueprint.model_validate_json(
        (_ROOT / "examples/reference/podcast/course_blueprint.json").read_text()
    )
    service = GenerationPlanningService(
        FileRLORepository(_ROOT / "examples/reference/rlos"),
        trace_root=tmp_path / modality.value / "traces",
        artifact_root=tmp_path / modality.value / "artifacts",
    )

    modality_result = await service.plan_modality(
        blueprint, modality, request_id=f"planning-{modality.value}"
    )
    workflow_result = await service.plan_workflow(
        blueprint,
        modality_result.modality_plan,
        request_id=f"planning-{modality.value}",
        workflow_id=f"workflow-{modality.value}",
    )

    assert modality_result.modality_plan.modality == modality
    assert workflow_result.build_plan.modality == modality
    assert workflow_result.build_plan.tasks
