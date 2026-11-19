from datetime import UTC, datetime, timedelta

from learning_commissioning.contracts import CommissioningJobRecord, CommissioningJobState
from learning_commissioning.repository import InMemoryPreviewRepository


async def test_job_listing_is_newest_first_and_supports_cursor_boundary():
    repository = InMemoryPreviewRepository()
    now = datetime.now(UTC)
    for index in range(3):
        job = CommissioningJobRecord(
            job_id=f"job-{index}",
            preview_id=f"preview-{index}",
            request_id=f"request-{index}",
            state=CommissioningJobState.QUEUED_FOR_ASSEMBLY,
            created_at=now + timedelta(seconds=index),
            updated_at=now + timedelta(seconds=index),
        )
        repository._jobs[job.job_id] = job

    first_page = await repository.list_job_views(limit=2)
    second_page = await repository.list_job_views(
        limit=2,
        before_created_at=first_page[-1].created_at,
        before_job_id=first_page[-1].job_id,
    )

    assert [job.job_id for job in first_page] == ["job-2", "job-1"]
    assert [job.job_id for job in second_page] == ["job-0"]


async def test_failed_planning_job_can_be_requeued():
    repository = InMemoryPreviewRepository()
    now = datetime.now(UTC)
    repository._jobs["job-failed"] = CommissioningJobRecord(
        job_id="job-failed",
        preview_id="preview-failed",
        request_id="request-failed",
        state=CommissioningJobState.FAILED,
        error_code="PlanningError",
        error_summary="planner unavailable",
        created_at=now,
        updated_at=now,
    )

    await repository.rerun_failed_job("job-failed")

    job = await repository.get_job("job-failed")
    assert job is not None
    assert job.state == CommissioningJobState.QUEUED_FOR_ASSEMBLY
    assert job.error_code is None
    assert job.error_summary is None
