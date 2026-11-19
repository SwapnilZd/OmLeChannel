"""
Tests for ProductionToolCatalog.

Verifies registration, duplicate rejection, modality filtering, deterministic
ordering, planner safety, and compiler (task_type_for) interface.
"""
from __future__ import annotations

import pytest

from learning_pipeline.contracts.common import Modality
from learning_pipeline.tools.catalog import ProductionToolCatalog
from learning_pipeline.tools.errors import (
    DuplicateCapabilityError,
    DuplicateTaskTypeError,
    UnsupportedCapabilityError,
)
from learning_pipeline.tools.speech.definition import (
    audio_assembly_tool_definition,
    speech_tool_definition,
)
from learning_pipeline.config import build_tool_catalog


# ── Registration ──────────────────────────────────────────────────────────────


def test_register_speech_tool() -> None:
    catalog = ProductionToolCatalog()
    catalog.register(speech_tool_definition())
    assert "speech.synthesize" in catalog.capabilities


def test_register_duplicate_capability_raises() -> None:
    catalog = ProductionToolCatalog()
    catalog.register(speech_tool_definition())
    with pytest.raises(DuplicateCapabilityError):
        catalog.register(speech_tool_definition())


def test_register_duplicate_task_type_raises() -> None:
    """A different capability name claiming the same task_type must be rejected."""
    from learning_pipeline.tools.manifest import ProductionToolDefinition, ToolManifest
    from learning_pipeline.tools.speech.contracts import SpeechSynthesisInput, SpeechSynthesisOutput

    catalog = ProductionToolCatalog()
    catalog.register(speech_tool_definition())

    # Create a definition with a different capability name but the SAME task_type
    dupe_manifest = ToolManifest(
        capability="speech.synthesize.v2",
        contract_version="1.0",
        task_type="speech.synthesize",  # same task type — conflict
        description="duplicate",
        supported_modalities=(Modality.PODCAST,),
        input_schema=SpeechSynthesisInput.model_json_schema(),
        output_schema=SpeechSynthesisOutput.model_json_schema(),
    )
    dupe = ProductionToolDefinition(
        manifest=dupe_manifest,
        input_model=SpeechSynthesisInput,
        output_model=SpeechSynthesisOutput,
    )
    with pytest.raises(DuplicateTaskTypeError):
        catalog.register(dupe)


# ── Resolution ────────────────────────────────────────────────────────────────


def test_resolve_unknown_capability_raises() -> None:
    catalog = ProductionToolCatalog()
    with pytest.raises(UnsupportedCapabilityError):
        catalog.resolve_capability("does.not.exist")


def test_task_type_for_speech() -> None:
    catalog = ProductionToolCatalog()
    catalog.register(speech_tool_definition())
    assert catalog.task_type_for("speech.synthesize") == "speech.synthesize"


def test_task_type_for_unknown_raises() -> None:
    catalog = ProductionToolCatalog()
    with pytest.raises(UnsupportedCapabilityError):
        catalog.task_type_for("does.not.exist")


def test_manifest_for_speech() -> None:
    catalog = ProductionToolCatalog()
    catalog.register(speech_tool_definition())
    manifest = catalog.manifest_for("speech.synthesize")
    assert manifest.capability == "speech.synthesize"


# ── Modality filtering ────────────────────────────────────────────────────────


def test_manifests_for_podcast_modality() -> None:
    catalog = build_tool_catalog()
    manifests = catalog.manifests_for_modality(Modality.PODCAST)
    caps = {m.capability for m in manifests}
    assert "speech.synthesize" in caps
    assert "audio.assemble" in caps


def test_manifests_for_elearning_modality_excludes_assembly() -> None:
    """audio.assemble only supports PODCAST; it must not appear for ELEARNING."""
    catalog = build_tool_catalog()
    manifests = catalog.manifests_for_modality(Modality.ELEARNING)
    caps = {m.capability for m in manifests}
    assert "speech.synthesize" in caps
    assert "audio.assemble" not in caps


def test_planner_view_is_deterministic() -> None:
    catalog = build_tool_catalog()
    view1 = catalog.planner_view(Modality.PODCAST)
    view2 = catalog.planner_view(Modality.PODCAST)
    assert [m.capability for m in view1] == [m.capability for m in view2]


def test_planner_view_is_lexicographically_ordered() -> None:
    catalog = build_tool_catalog()
    names = [m.capability for m in catalog.planner_view(Modality.PODCAST)]
    assert names == sorted(names)


# ── Planner safety ────────────────────────────────────────────────────────────


def test_planner_view_contains_only_manifests() -> None:
    catalog = build_tool_catalog()
    for manifest in catalog.planner_view(Modality.PODCAST):
        # Must be a ToolManifest — no executor, no credentials
        from learning_pipeline.tools.manifest import ToolManifest
        assert isinstance(manifest, ToolManifest)


# ── Compiler interface ────────────────────────────────────────────────────────


def test_compiler_resolves_speech_capability_through_catalog() -> None:
    """ProductionCompiler using ProductionToolCatalog must map capability to task_type."""
    from learning_pipeline.contracts import LiteralInput, Modality, ModalityProductionPlan, ProductionJob
    from learning_pipeline.production import ProductionCompiler

    catalog = build_tool_catalog()
    plan = ModalityProductionPlan(
        plan_id="pp-test",
        modality=Modality.PODCAST,
        narrative="test",
        jobs=(
            ProductionJob(
                id="seg-1",
                capability="speech.synthesize",
                inputs={"text": LiteralInput(value="Hello")},
                output_keys=("audio_uri",),
            ),
        ),
        deliverable_job_ids=("seg-1",),
    )
    compiler = ProductionCompiler(catalog)
    build_plan = compiler.compile("wf-test", plan)
    assert build_plan.tasks[0].task_type == "speech.synthesize"


# ── Task types introspection ──────────────────────────────────────────────────


def test_catalog_task_types_match_registered_definitions() -> None:
    catalog = build_tool_catalog()
    assert "speech.synthesize" in catalog.task_types
    assert "audio.assemble" in catalog.task_types
