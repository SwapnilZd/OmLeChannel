import pytest
from pydantic import ValidationError

from learning_pipeline.contracts import (
    BuildPlan,
    ContentDepth,
    LearnerContext,
    LiteralInput,
    Modality,
    RLOContentSelection,
    TailoredRLORef,
    TaskOutputInput,
    TaskSpec,
    TopicProficiency,
)


def test_build_plan_is_immutable_and_rejects_unknown_fields() -> None:
    plan = BuildPlan(
        workflow_id="wf-1",
        source_plan_id="production-1",
        modality=Modality.VIDEO,
        tasks=(
            TaskSpec(
                id="audio",
                task_type="speech.synthesize",
                inputs={"script": LiteralInput(value="hello")},
                output_keys=("audio",),
            ),
        ),
        deliverable_task_ids=("audio",),
    )

    with pytest.raises(ValidationError):
        plan.workflow_id = "changed"

    with pytest.raises(ValidationError):
        BuildPlan.model_validate({**plan.model_dump(), "unexpected": True})


def test_task_output_binding_is_structured() -> None:
    binding = TaskOutputInput(task_id="audio", output_key="timestamps")
    assert binding.kind == "task_output"
    assert binding.task_id == "audio"


# --- New tests for seniority / proficiency / depth separation ---


def _make_tailored_ref(
    starting: TopicProficiency = TopicProficiency.BEGINNER,
    target: TopicProficiency = TopicProficiency.INTERMEDIATE,
    depth: ContentDepth = ContentDepth.WORKING,
) -> TailoredRLORef:
    return TailoredRLORef(
        rlo_id="rlo-1",
        rlo_version="1",
        order=1,
        selected_content=RLOContentSelection(),
        starting_proficiency=starting,
        target_proficiency=target,
        content_depth=depth,
        role_relevance="Needed for oversight",
        personalization_rationale="Working knowledge sufficient for management review",
        sequencing_rationale="First in sequence",
    )


def test_level_55_learner_can_have_beginner_proficiency() -> None:
    """Organizational level must not automatically determine topic proficiency."""
    learner = LearnerContext(
        role="Manager",
        deloitte_level=55,
        default_proficiency=TopicProficiency.BEGINNER,
        goals=("understand risk",),
    )
    assert learner.deloitte_level == 55
    assert learner.default_proficiency == TopicProficiency.BEGINNER


def test_level_65_learner_is_not_automatically_advanced() -> None:
    """Senior level must not force advanced proficiency."""
    learner = LearnerContext(
        role="Partner",
        deloitte_level=65,
        default_proficiency=TopicProficiency.INTERMEDIATE,
        goals=("review methodology",),
    )
    assert learner.default_proficiency == TopicProficiency.INTERMEDIATE


def test_topic_specific_proficiency_overrides_default() -> None:
    """A per-topic entry in topic_proficiencies shadows default_proficiency."""
    learner = LearnerContext(
        role="Analyst",
        deloitte_level=35,
        default_proficiency=TopicProficiency.INTERMEDIATE,
        topic_proficiencies={"rlo-risk": TopicProficiency.BEGINNER},
        goals=("learn risk",),
    )
    assert learner.topic_proficiencies["rlo-risk"] == TopicProficiency.BEGINNER
    assert learner.default_proficiency == TopicProficiency.INTERMEDIATE


def test_proficiency_and_depth_serialize_independently() -> None:
    """starting_proficiency, target_proficiency, and content_depth are separate fields."""
    ref = _make_tailored_ref(
        starting=TopicProficiency.BEGINNER,
        target=TopicProficiency.ADVANCED,
        depth=ContentDepth.SUMMARY,
    )
    data = ref.model_dump()
    assert data["starting_proficiency"] == "beginner"
    assert data["target_proficiency"] == "advanced"
    assert data["content_depth"] == "summary"


@pytest.mark.parametrize(
    "starting,target",
    [
        (TopicProficiency.BEGINNER, TopicProficiency.BEGINNER),
        (TopicProficiency.BEGINNER, TopicProficiency.INTERMEDIATE),
        (TopicProficiency.BEGINNER, TopicProficiency.ADVANCED),
        (TopicProficiency.INTERMEDIATE, TopicProficiency.INTERMEDIATE),
        (TopicProficiency.INTERMEDIATE, TopicProficiency.ADVANCED),
        (TopicProficiency.ADVANCED, TopicProficiency.ADVANCED),
    ],
)
def test_valid_proficiency_progression_is_accepted(
    starting: TopicProficiency, target: TopicProficiency
) -> None:
    ref = _make_tailored_ref(starting=starting, target=target)
    assert ref.starting_proficiency == starting
    assert ref.target_proficiency == target


@pytest.mark.parametrize(
    "starting,target",
    [
        (TopicProficiency.INTERMEDIATE, TopicProficiency.BEGINNER),
        (TopicProficiency.ADVANCED, TopicProficiency.INTERMEDIATE),
        (TopicProficiency.ADVANCED, TopicProficiency.BEGINNER),
    ],
)
def test_target_proficiency_below_starting_is_rejected(
    starting: TopicProficiency, target: TopicProficiency
) -> None:
    with pytest.raises(ValidationError, match="cannot be lower than"):
        _make_tailored_ref(starting=starting, target=target)


def test_unsupported_deloitte_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LearnerContext(
            role="Analyst",
            deloitte_level=99,  # not in {25, 35, 45, 55, 65}
            default_proficiency=TopicProficiency.BEGINNER,
            goals=("learn",),
        )


def test_personalization_rationale_is_required() -> None:
    with pytest.raises(ValidationError):
        TailoredRLORef(
            rlo_id="rlo-1",
            rlo_version="1",
            order=1,
            selected_content=RLOContentSelection(),
            starting_proficiency=TopicProficiency.BEGINNER,
            target_proficiency=TopicProficiency.INTERMEDIATE,
            role_relevance="oversight",
            sequencing_rationale="first",
            # personalization_rationale intentionally omitted
        )
