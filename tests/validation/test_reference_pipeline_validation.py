"""
End-to-end cross-contract validation of the complete Phase 2 reference pipeline.

Loads every fixture from examples/reference/podcast/ and runs each Phase 3
validator in order.  The complete pipeline must pass without errors.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from learning_pipeline.contracts import (
    BuildPlan,
    CourseBlueprint,
    ModalityPlan,
    ModalityProductionPlan,
    RLODocument,
)
from learning_pipeline.validation import (
    validate_build_plan,
    validate_course_blueprint,
    validate_modality_plan,
    validate_production_plan,
)

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_FIXTURE_DIR = _REPO_ROOT / "examples" / "reference" / "podcast"
_RLO_PATH = _REPO_ROOT / "course-definitions" / "rlos" / "rlo-adkar-01-name-and-sequence.json"


@pytest.fixture(scope="module")
def rlo() -> RLODocument:
    return RLODocument.model_validate(json.loads(_RLO_PATH.read_text()))


@pytest.fixture(scope="module")
def blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate(
        json.loads((_FIXTURE_DIR / "course_blueprint.json").read_text())
    )


@pytest.fixture(scope="module")
def modality_plan() -> ModalityPlan:
    return ModalityPlan.model_validate(
        json.loads((_FIXTURE_DIR / "modality_plan.json").read_text())
    )


@pytest.fixture(scope="module")
def production_plan() -> ModalityProductionPlan:
    return ModalityProductionPlan.model_validate(
        json.loads((_FIXTURE_DIR / "production_plan.json").read_text())
    )


@pytest.fixture(scope="module")
def build_plan() -> BuildPlan:
    return BuildPlan.model_validate(
        json.loads((_FIXTURE_DIR / "build_plan.json").read_text())
    )


def test_reference_pipeline_validates_completely(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_plan: ModalityPlan,
    production_plan: ModalityProductionPlan,
    build_plan: BuildPlan,
) -> None:
    """The complete Phase 2 reference pipeline passes all Phase 3 validators."""
    validate_course_blueprint(
        blueprint,
        (rlo,),
    )
    validate_modality_plan(
        modality_plan,
        blueprint,
        (rlo,),
        frozenset({"narration"}),
    )
    validate_production_plan(
        production_plan,
        modality_plan,
        frozenset({"narration", "audio_assembly"}),
    )
    validate_build_plan(
        build_plan,
        frozenset({"speech.synthesize", "audio.assemble"}),
    )


def test_course_blueprint_validates(rlo: RLODocument, blueprint: CourseBlueprint) -> None:
    validate_course_blueprint(blueprint, (rlo,))


def test_modality_plan_validates(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_plan: ModalityPlan,
) -> None:
    validate_modality_plan(
        modality_plan,
        blueprint,
        (rlo,),
        frozenset({"narration"}),
    )


def test_production_plan_validates(
    production_plan: ModalityProductionPlan,
    modality_plan: ModalityPlan,
) -> None:
    validate_production_plan(
        production_plan,
        modality_plan,
        frozenset({"narration", "audio_assembly"}),
    )


def test_build_plan_validates(build_plan: BuildPlan) -> None:
    validate_build_plan(
        build_plan,
        frozenset({"speech.synthesize", "audio.assemble"}),
    )
