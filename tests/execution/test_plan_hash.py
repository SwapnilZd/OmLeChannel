from learning_pipeline.contracts import BuildPlan, LiteralInput, Modality, TaskSpec
from learning_pipeline.validation import canonical_plan_hash


def _plan(**overrides) -> BuildPlan:
    defaults: dict = {
        "workflow_id": "wf-hash-test",
        "source_plan_id": "sp-1",
        "modality": Modality.PODCAST,
        "tasks": (
            TaskSpec(
                id="speech-1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="scene-intro")},
                output_keys=("audio_file",),
            ),
        ),
        "deliverable_task_ids": ("speech-1",),
    }
    defaults.update(overrides)
    return BuildPlan(**defaults)


def test_identical_plans_produce_identical_hashes():
    assert canonical_plan_hash(_plan()) == canonical_plan_hash(_plan())


def test_hash_is_a_64_character_hex_string():
    h = canonical_plan_hash(_plan())
    assert isinstance(h, str)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_changed_literal_input_changes_hash():
    plan_a = _plan(
        tasks=(
            TaskSpec(
                id="speech-1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="scene-intro")},
                output_keys=("audio_file",),
            ),
        )
    )
    plan_b = _plan(
        tasks=(
            TaskSpec(
                id="speech-1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="scene-two")},
                output_keys=("audio_file",),
            ),
        )
    )
    assert canonical_plan_hash(plan_a) != canonical_plan_hash(plan_b)


def test_added_dependency_changes_hash():
    plan_a = _plan(
        tasks=(
            TaskSpec(
                id="s1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s")},
                output_keys=("audio_file",),
            ),
            TaskSpec(
                id="assemble",
                task_type="audio.assemble",
                depends_on=("s1",),
                output_keys=("podcast_file",),
            ),
        ),
        deliverable_task_ids=("assemble",),
    )
    plan_b = _plan(
        tasks=(
            TaskSpec(
                id="s1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s")},
                output_keys=("audio_file",),
            ),
            TaskSpec(
                id="assemble",
                task_type="audio.assemble",
                output_keys=("podcast_file",),
            ),
        ),
        deliverable_task_ids=("assemble",),
    )
    assert canonical_plan_hash(plan_a) != canonical_plan_hash(plan_b)


def test_changed_workflow_id_changes_hash():
    assert canonical_plan_hash(_plan(workflow_id="wf-a")) != canonical_plan_hash(
        _plan(workflow_id="wf-b")
    )


def test_plan_is_not_mutated_during_hashing():
    plan = _plan()
    original_tasks = plan.tasks
    canonical_plan_hash(plan)
    assert plan.tasks == original_tasks
