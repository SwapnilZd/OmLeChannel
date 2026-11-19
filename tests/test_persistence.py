from learning_pipeline.contracts import BuildPlan, Modality, TaskResult, TaskSpec
from learning_pipeline.runtime.persistence import FilePlanStore, FileRunStateStore, RunSnapshot, TaskStatus


def test_plan_and_state_round_trip(tmp_path) -> None:
    plan = BuildPlan(
        workflow_id="wf-1",
        source_plan_id="source-1",
        modality=Modality.PODCAST,
        tasks=(TaskSpec(id="audio", task_type="speech", output_keys=("audio",)),),
        deliverable_task_ids=("audio",),
    )
    plan_store = FilePlanStore(tmp_path)
    plan_store.save(plan)
    assert plan_store.load("wf-1") == plan

    snapshot = RunSnapshot(
        workflow_id="wf-1",
        plan_hash="abc",
        statuses={"audio": TaskStatus.SUCCEEDED},
        results={"audio": TaskResult(task_id="audio", outputs={"audio": "a.wav"}, attempts=1)},
    )
    state_store = FileRunStateStore(tmp_path)
    state_store.save(snapshot)
    assert state_store.load("wf-1") == snapshot
