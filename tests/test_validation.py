import pytest

from learning_pipeline.contracts import BuildPlan, Modality, TaskOutputInput, TaskSpec
from learning_pipeline.validation import PlanValidationError, canonical_plan_hash, validate_build_plan


def plan_with(tasks: tuple[TaskSpec, ...]) -> BuildPlan:
    return BuildPlan(
        workflow_id="wf-1",
        source_plan_id="source-1",
        modality=Modality.ELEARNING,
        tasks=tasks,
        deliverable_task_ids=(tasks[-1].id,),
    )


@pytest.mark.parametrize(
    "tasks,error_text",
    [
        ((TaskSpec(id="a", task_type="x", depends_on=("missing",), output_keys=("v",)),), "missing dependency"),
        ((TaskSpec(id="a", task_type="x", depends_on=("b",), output_keys=("v",)), TaskSpec(id="b", task_type="x", depends_on=("a",), output_keys=("v",))), "cycle"),
        ((TaskSpec(id="a", task_type="unknown", output_keys=("v",)),), "unsupported task type"),
    ],
)
def test_invalid_plans_are_rejected(tasks: tuple[TaskSpec, ...], error_text: str) -> None:
    with pytest.raises(PlanValidationError, match=error_text):
        validate_build_plan(plan_with(tasks), {"x"})


def test_binding_must_reference_a_declared_dependency_and_output() -> None:
    tasks = (
        TaskSpec(id="a", task_type="x", output_keys=("value",)),
        TaskSpec(
            id="b",
            task_type="x",
            inputs={"input": TaskOutputInput(task_id="a", output_key="missing")},
            output_keys=("value",),
        ),
    )
    with pytest.raises(PlanValidationError, match="declared dependency"):
        validate_build_plan(plan_with(tasks), {"x"})


def test_hash_is_stable_for_the_same_plan() -> None:
    plan = plan_with((TaskSpec(id="a", task_type="x", output_keys=("value",)),))
    assert canonical_plan_hash(plan) == canonical_plan_hash(plan)
