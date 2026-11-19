from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint, RLODocument
from learning_pipeline.contracts.assembly import RLOContentSelection
from learning_pipeline.planners.modality.context import ModalityContextResolver
from learning_pipeline.repository import InMemoryRLORepository


_ROOT = Path(__file__).parents[3]
_RLO_PATH = (
    _ROOT / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)
_BLUEPRINT_PATH = (
    _ROOT / "examples" / "reference" / "podcast" / "course_blueprint.json"
)


def _rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _blueprint(selection: RLOContentSelection) -> CourseBlueprint:
    blueprint = CourseBlueprint.model_validate_json(
        _BLUEPRINT_PATH.read_text(encoding="utf-8")
    )
    ref = blueprint.ordered_rlo_refs[0].model_copy(
        update={"selected_content": selection}
    )
    return blueprint.model_copy(update={"ordered_rlo_refs": (ref,)})


@pytest.mark.asyncio
async def test_partial_selection_does_not_expand_empty_categories() -> None:
    rlo = _rlo()
    component_id = rlo.components[0].id
    context = await ModalityContextResolver(
        InMemoryRLORepository([rlo])
    ).resolve(
        _blueprint(RLOContentSelection(component_ids=(component_id,)))
    )

    resolved = context.rlo_contexts[0]
    assert resolved.selected_objective_ids == ()
    assert resolved.selected_concept_ids == ()
    assert resolved.selected_component_ids == (component_id,)
    assert resolved.selected_assessment_ids == ()
    assert resolved.enabling_objectives == ()
    assert resolved.concepts == ()
    assert [item.content_id for item in resolved.components] == [component_id]
    assert resolved.assessment_items == ()


@pytest.mark.asyncio
async def test_all_empty_selection_still_selects_full_rlo() -> None:
    rlo = _rlo()
    context = await ModalityContextResolver(
        InMemoryRLORepository([rlo])
    ).resolve(_blueprint(RLOContentSelection()))

    resolved = context.rlo_contexts[0]
    assert resolved.selected_objective_ids == (rlo.enabling_objective.id,)
    assert resolved.selected_concept_ids == tuple(item.id for item in rlo.concepts)
    assert resolved.selected_component_ids == tuple(item.id for item in rlo.components)
    assert resolved.selected_assessment_ids == tuple(
        item.id for item in rlo.assessment_items
    )
