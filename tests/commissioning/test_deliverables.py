from learning_commissioning.api.app import _artifact_candidates
from learning_pipeline.contracts import TaskResult, WorkflowResult


def test_deliverable_discovery_prioritizes_bundle_and_uses_opaque_ids():
    result = WorkflowResult(
        workflow_id="workflow-1",
        plan_hash="hash",
        task_results={},
        deliverables=(
            TaskResult(
                task_id="assemble-course",
                attempts=1,
                outputs={
                    "entry_html": {
                        "uri": "artifact://course/index.html",
                        "media_type": "text/html",
                        "sha256": "a" * 64,
                        "size_bytes": 10,
                    },
                    "bundle_zip": {
                        "uri": "artifact://course/course.zip",
                        "media_type": "application/zip",
                        "sha256": "b" * 64,
                        "size_bytes": 20,
                    },
                },
            ),
        ),
    )

    entries = _artifact_candidates("job-1", result)

    assert entries[0][0].primary is True
    assert entries[0][0].filename == "course.zip"
    assert entries[0][0].media_type == "application/zip"
    assert "artifact://" not in entries[0][0].download_url
    assert entries[0][1] == "artifact://course/course.zip"
    other_job_entries = _artifact_candidates("job-2", result)
    assert other_job_entries[0][0].deliverable_id != entries[0][0].deliverable_id
