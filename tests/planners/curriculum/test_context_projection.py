"""Assembly context projection tests — Phase 12."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.context import (
    ContextBudgetExceededError,
    build_assembly_context,
    check_context_budget,
    serialized_context_size,
)

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def test_required_fields_are_present():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    assert ctx.rlo_id == rlo.id
    assert ctx.rlo_version == rlo.version
    assert ctx.title == rlo.title
    assert ctx.topic == rlo.topic
    assert ctx.domain == rlo.domain
    assert ctx.governance_status == rlo.governance.status


def test_exact_content_ids_preserved():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    assert {c.id for c in ctx.concepts} == {c.id for c in rlo.concepts}
    assert {c.id for c in ctx.components} == {c.id for c in rlo.components}
    assert {a.id for a in ctx.assessment_items} == {a.id for a in rlo.assessment_items}


def test_projection_does_not_modify_rlo():
    rlo = _load_rlo()
    original_id = rlo.id
    build_assembly_context(rlo)
    assert rlo.id == original_id


def test_context_ordering_is_deterministic():
    rlo = _load_rlo()
    ctx1 = build_assembly_context(rlo)
    ctx2 = build_assembly_context(rlo)
    assert ctx1 == ctx2


def test_context_size_is_nonzero():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    size = serialized_context_size((ctx,))
    assert size > 100


def test_oversize_context_fails_without_truncation():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    with pytest.raises(ContextBudgetExceededError) as exc_info:
        check_context_budget((ctx,), budget_chars=10)
    assert exc_info.value.calculated_size > 10
    assert exc_info.value.budget == 10


def test_within_budget_passes():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    check_context_budget((ctx,), budget_chars=10_000_000)


def test_source_ids_present():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    assert isinstance(ctx.source_ids, tuple)


def test_role_tags_preserved():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    assert ctx.role_tags == rlo.role_tags


def test_prerequisites_preserved():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    assert ctx.prerequisites == rlo.prerequisites
    assert ctx.corequisites == rlo.corequisites
    assert ctx.follow_ons == rlo.follow_ons
