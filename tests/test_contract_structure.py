"""
Smoke tests: verify public import surfaces for contracts and validation packages.

These tests catch regressions caused by accidental symbol removal or broken
re-exports without relying on any runtime behaviour.
"""

from __future__ import annotations

import importlib


# ── Test 1: all public contracts symbols are importable ───────────────────────

def test_contracts_public_symbols_are_importable() -> None:
    contracts = importlib.import_module("learning_pipeline.contracts")
    expected = [
        # common
        "FrozenModel",
        "Modality",
        "TopicProficiency",
        "ContentDepth",
        "PROFICIENCY_ORDER",
        "LiteralInput",
        "TaskOutputInput",
        "InputBinding",
        # rlo
        "Source",
        "Misconception",
        "EnablingObjective",
        "Concept",
        "InstructionalComponent",
        "AssessmentOption",
        "AssessmentItem",
        "DesignBrief",
        "GagneEventMapping",
        "ContentTypeRecommendation",
        "Governance",
        "Accessibility",
        "RLODocument",
        # learner
        "LearnerContext",
        # assembly
        "RLOContentSelection",
        "TailoredRLORef",
        "CourseBlueprint",
        # modality
        "PresentationCapability",
        "RLOContentRef",
        "ModalityScene",
        "ModalityPlan",
        # production
        "ProductionJob",
        "ModalityProductionPlan",
        # execution
        "TaskSpec",
        "BuildPlan",
        "TaskResult",
        "WorkflowResult",
    ]
    missing = [name for name in expected if not hasattr(contracts, name)]
    assert missing == [], f"Missing from learning_pipeline.contracts: {missing}"


# ── Test 2: __all__ in contracts matches importable names ─────────────────────

def test_contracts_all_matches_expected_symbols() -> None:
    contracts = importlib.import_module("learning_pipeline.contracts")
    for name in contracts.__all__:
        assert hasattr(contracts, name), f"__all__ lists '{name}' but it is not importable"


# ── Test 3: all public validation symbols are importable ─────────────────────

def test_validation_public_symbols_are_importable() -> None:
    validation = importlib.import_module("learning_pipeline.validation")
    expected = [
        # errors
        "CrossContractValidationError",
        # graph
        "validate_dag",
        # rlo_references
        "InvalidRLOContentReferenceError",
        "validate_rlo_selection",
        "validate_content_selection",
        "validate_modality_plan_scene_refs",
        # course_blueprint
        "validate_course_blueprint",
        # modality_plan
        "PlanValidationError",
        "validate_build_plan",
        "canonical_plan_hash",
        "ModalityPlanValidationError",
        "validate_modality_plan",
        # production_plan
        "ProductionSceneRefError",
        "validate_production_plan",
        "validate_production_scene_refs",
    ]
    missing = [name for name in expected if not hasattr(validation, name)]
    assert missing == [], f"Missing from learning_pipeline.validation: {missing}"


# ── Test 4: __all__ in validation matches importable names ────────────────────

def test_validation_all_matches_expected_symbols() -> None:
    validation = importlib.import_module("learning_pipeline.validation")
    for name in validation.__all__:
        assert hasattr(validation, name), f"__all__ lists '{name}' but it is not importable"


# ── Test 5: contracts sub-modules exist and are independently importable ──────

def test_contracts_sub_modules_are_importable() -> None:
    sub_modules = [
        "learning_pipeline.contracts.common",
        "learning_pipeline.contracts.rlo",
        "learning_pipeline.contracts.learner",
        "learning_pipeline.contracts.assembly",
        "learning_pipeline.contracts.modality",
        "learning_pipeline.contracts.production",
        "learning_pipeline.contracts.execution",
    ]
    for mod_path in sub_modules:
        mod = importlib.import_module(mod_path)
        assert mod is not None, f"Could not import {mod_path}"


# ── Test 6: validation sub-modules exist and are independently importable ─────

def test_validation_sub_modules_are_importable() -> None:
    sub_modules = [
        "learning_pipeline.validation.errors",
        "learning_pipeline.validation.graph",
        "learning_pipeline.validation.rlo_references",
        "learning_pipeline.validation.course_blueprint",
        "learning_pipeline.validation.modality_plan",
        "learning_pipeline.validation.production_plan",
        "learning_pipeline.validation.build_plan",
    ]
    for mod_path in sub_modules:
        mod = importlib.import_module(mod_path)
        assert mod is not None, f"Could not import {mod_path}"


# ── Test 7: no circular imports across the full pipeline ──────────────────────

def test_no_circular_imports() -> None:
    all_modules = [
        "learning_pipeline.contracts",
        "learning_pipeline.contracts.common",
        "learning_pipeline.contracts.rlo",
        "learning_pipeline.contracts.learner",
        "learning_pipeline.contracts.assembly",
        "learning_pipeline.contracts.modality",
        "learning_pipeline.contracts.production",
        "learning_pipeline.contracts.execution",
        "learning_pipeline.validation",
        "learning_pipeline.validation.errors",
        "learning_pipeline.validation.graph",
        "learning_pipeline.validation.rlo_references",
        "learning_pipeline.validation.course_blueprint",
        "learning_pipeline.validation.modality_plan",
        "learning_pipeline.validation.production_plan",
        "learning_pipeline.validation.build_plan",
        "learning_pipeline.production",
    ]
    for mod_path in all_modules:
        mod = importlib.import_module(mod_path)
        assert mod is not None, f"Circular import or missing module: {mod_path}"


# ── Test 8: exact public-contract smoke test from the spec ────────────────────

def test_public_contract_imports() -> None:
    from learning_pipeline.contracts import (
        BuildPlan,
        CourseBlueprint,
        LearnerContext,
        ModalityPlan,
        ModalityProductionPlan,
        RLODocument,
        WorkflowResult,
    )

    assert RLODocument is not None
    assert LearnerContext is not None
    assert CourseBlueprint is not None
    assert ModalityPlan is not None
    assert ModalityProductionPlan is not None
    assert BuildPlan is not None
    assert WorkflowResult is not None
