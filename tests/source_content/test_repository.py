from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace

import pytest

from src.source_authoring import repository as authoring_repository
from src.source_authoring import draft_repository
from tests.source_content.test_rlo_drafting import _workspace as drafting_workspace
from src.source_authoring import job_repository
from src.source_authoring.contracts import (
    LearningBrief,
    ObjectiveBloomLevel,
    ObjectiveContentType,
    ObjectiveDecision,
    ObjectiveDecisionStatus,
    ObjectiveScopeStatus,
    ObjectiveWorkspace,
    PractitionerLens,
)
from src.source_authoring.draft_contracts import (
    RLODraftRequest,
    RLODraftState,
)
from src.source_authoring.job_contracts import (
    ObjectiveJobStage,
    ObjectiveProcessingStatus,
    ObjectiveReviewKind,
)
from src.source_ingestion import repository


def _clean_source_tables(database_url):
    from sqlalchemy import create_engine

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_rlo_generation_prompt_runs CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_rlo_generation_checkpoints CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_rlo_generation_batches CASCADE")
        connection.exec_driver_sql(
            "DROP TABLE IF EXISTS source_objective_model_checkpoints CASCADE"
        )
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_objective_prompt_runs CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_objective_job_reviews CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_objective_job_events CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_objective_jobs CASCADE")
        connection.exec_driver_sql(
            "DROP TABLE IF EXISTS source_published_rlo_dependencies CASCADE"
        )
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_rlo_draft_reviews CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_rlo_draft_revisions CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_rlo_draft_jobs CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_objective_decisions CASCADE")
        connection.exec_driver_sql(
            "DROP TABLE IF EXISTS source_objective_workspace_revisions CASCADE"
        )
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_objective_workspaces CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_learning_briefs CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_map_artifacts CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_collection_members CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_collections CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_processing_runs CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_versions CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS source_documents CASCADE")
        connection.exec_driver_sql("DROP TABLE IF EXISTS _source_schema_migrations CASCADE")
    engine.dispose()


@pytest.fixture
def repo(monkeypatch):
    database_url = os.environ["SOURCE_POSTGRES_TEST_URL"]
    monkeypatch.setenv("SOURCE_INGESTION_DATABASE_URL", database_url)
    repository.reset_repository_for_tests()
    _clean_source_tables(database_url)
    yield repository
    repository.reset_repository_for_tests()


def create(repo, suffix="1"):
    return repo.create_job(
        job_id=f"job-{suffix}",
        source_id=f"source-{suffix}",
        original_filename=f"source-{suffix}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        checksum=suffix * 64,
        minio_object_path=f"sources/{suffix}/original.pdf",
    )


def test_source_version_and_first_run_are_created_atomically(repo):
    job = create(repo)

    assert job.source_version_id
    assert job.status == "queued"
    assert repo.find_by_checksum("1" * 64) == job


def test_new_edition_uses_same_logical_source_with_new_version(repo):
    first = create(repo)
    second = repo.create_job(
        job_id="job-2",
        source_id=first.source_id,
        original_filename="source-v2.pdf",
        content_type="application/pdf",
        size_bytes=12,
        checksum="2" * 64,
        minio_object_path="sources/1/v2/original.pdf",
    )

    assert second.source_id == first.source_id
    assert second.source_version_id != first.source_version_id


def test_claim_records_owner_and_expected_state_transition(repo):
    create(repo)

    claimed = repo.claim_next_queued_job(worker_id="worker-a", lease_seconds=30)
    ready = repo.update_job_status(
        claimed.job_id,
        "ready",
        expected_status="processing",
        artifact_manifest_object_key="source-content/manifest.json",
    )

    assert claimed.worker_id == "worker-a"
    assert ready.status == "ready"
    with pytest.raises(repo.InvalidStateTransition):
        repo.update_job_status(ready.job_id, "failed", expected_status="processing")


def test_retry_creates_a_new_attempt_without_overwriting_failure(repo):
    original = create(repo)
    repo.claim_next_queued_job()
    repo.update_job_status(
        original.job_id,
        "failed",
        expected_status="processing",
        retryable=True,
    )

    retry = repo.retry_job(original.job_id)

    assert retry.job_id != original.job_id
    assert retry.source_version_id == original.source_version_id
    assert retry.attempt == 2
    assert repo.get_job(original.job_id).status == "failed"


def test_non_retryable_failure_cannot_create_another_attempt(repo):
    original = create(repo)
    repo.claim_next_queued_job()
    repo.update_job_status(
        original.job_id,
        "failed",
        expected_status="processing",
        retryable=False,
    )

    with pytest.raises(repo.InvalidStateTransition, match="non-retryable"):
        repo.retry_job(original.job_id)


def test_expired_lease_is_requeued(repo):
    create(repo)
    repo.claim_next_queued_job(lease_seconds=1)

    recovered = repo.recover_stale_jobs(
        datetime.now(timezone.utc) + timedelta(seconds=2)
    )

    assert recovered == 1
    assert repo.claim_next_queued_job(worker_id="worker-b").worker_id == "worker-b"


def test_postgres_workers_do_not_double_claim(repo):
    create(repo, "9")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(repo.claim_next_queued_job, ["a", "b"]))

    assert sum(result is not None for result in results) == 1


def test_postgres_migrations_are_idempotent(repo):
    repo.init_db()
    repo.reset_repository_for_tests()
    repo.init_db()


def test_source_collection_preserves_member_order_and_authority_notes(repo):
    first = create(repo, "3")
    second = create(repo, "4")

    created = repo.create_source_collection(
        collection_id="collection-1",
        title="Primary materials",
        created_by="admin-1",
        members=[
            (second.source_version_id, "Controlling authority"),
            (first.source_version_id, None),
        ],
    )
    loaded = repo.get_source_collection(created.collection_id)

    assert [member.source_version_id for member in loaded.members] == [
        second.source_version_id,
        first.source_version_id,
    ]
    assert loaded.members[0].authority_note == "Controlling authority"


def test_source_collection_rejects_duplicate_members(repo):
    source = create(repo, "5")

    with pytest.raises(ValueError, match="duplicate source version"):
        repo.create_source_collection(
            collection_id="collection-duplicate",
            title="Invalid",
            members=[
                (source.source_version_id, None),
                (source.source_version_id, None),
            ],
        )


def test_source_map_artifacts_are_resumable_and_do_not_overwrite(repo):
    first = repo.save_source_map_artifact(
        map_id="map-1",
        scope_kind="section",
        scope_id="source-v1",
        hierarchy_key="segment-1",
        map_revision="source-map-v1",
        model_alias="source-section-mapping",
        prompt_template="Map the supplied nodes.",
        input_node_ids=["node-1"],
        token_usage={"input_tokens": 10},
        payload={"map_id": "map-1"},
    )
    resumed = repo.save_source_map_artifact(
        map_id="map-2",
        scope_kind="section",
        scope_id="source-v1",
        hierarchy_key="segment-1",
        map_revision="source-map-v1",
        model_alias="source-section-mapping",
        prompt_template="Changed prompt",
        input_node_ids=["node-2"],
        token_usage={},
        payload={"map_id": "map-2"},
    )

    loaded = repo.get_source_map_artifact(
        "section", "source-v1", "segment-1", "source-map-v1"
    )
    assert resumed.map_id == first.map_id == "map-1"
    assert loaded.payload == {"map_id": "map-1"}
    assert loaded.input_node_ids == ("node-1",)


def test_objective_workspace_revisions_and_admin_decisions_are_durable(repo):
    source = create(repo, "7")
    repo.create_source_collection(
        collection_id="objective-collection",
        title="Objective materials",
        members=[(source.source_version_id, None)],
    )
    brief = LearningBrief(
        brief_id="brief-1",
        collection_id="objective-collection",
        lenses=[
            PractitionerLens(
                lens_id="lens-1",
                title="Practitioner",
                practitioner_role="Consultant",
                relevant_tasks=["Apply the source"],
                rationale="The source supports the task.",
                inferred=True,
            )
        ],
        source_map_revision="source-map-v1",
        brief_revision="source-map-v1:default",
    )
    authoring_repository.save_learning_brief(brief)
    authoring_repository.create_objective_workspace(
        "workspace-1", "objective-collection", created_by="admin-1"
    )
    workspace = ObjectiveWorkspace(
        workspace_id="workspace-1",
        collection_id="objective-collection",
        revision=1,
        learning_brief=brief,
        candidates=[],
    )
    authoring_repository.save_workspace_revision(workspace, model_metadata={})
    authoring_repository.record_objective_decision(
        "workspace-1",
        1,
        ObjectiveDecision(
            candidate_id="candidate-1",
            status=ObjectiveDecisionStatus.REVISION_REQUESTED,
            note="Narrow the assessment boundary.",
            decided_by="admin-1",
        ),
    )

    loaded = authoring_repository.get_objective_workspace("workspace-1")
    assert loaded.revision == 1
    assert loaded.decisions[0].status == ObjectiveDecisionStatus.REVISION_REQUESTED
    assert loaded.decisions[0].note == "Narrow the assessment boundary."


def test_objective_job_moves_through_durable_review_workflow(repo):
    source = create(repo, "6")
    repo.update_job_status(source.job_id, "ready", expected_status="queued")
    repo.create_source_collection(
        collection_id="objective-job-collection",
        title="Objective job materials",
        members=[(source.source_version_id, None)],
    )
    job = job_repository.create_objective_job(
        source.job_id,
        "objective-job-collection",
        created_by="lds@example.com",
        job_id="objective-job-1",
    )

    job_repository.save_model_checkpoint(
        job.job_id,
        operation="classify-objective-1",
        model_alias="source-objective-proposal",
        prompt_sha256="a" * 64,
        input_sha256="b" * 64,
        output_schema="ObjectiveClassificationDraft:v1",
        output_payload={"candidate_id": "candidate-1"},
    )
    assert job_repository.load_model_checkpoint(
        job.job_id,
        operation="classify-objective-1",
        model_alias="source-objective-proposal",
        prompt_sha256="a" * 64,
        input_sha256="b" * 64,
        output_schema="ObjectiveClassificationDraft:v1",
    ) == {"candidate_id": "candidate-1"}
    job_repository.save_model_checkpoint(
        job.job_id,
        operation="classify-objective-1",
        model_alias="source-objective-proposal",
        prompt_sha256="a" * 64,
        input_sha256="c" * 64,
        output_schema="ObjectiveClassificationDraft:v1",
        output_payload={"candidate_id": "candidate-2"},
    )
    assert job_repository.load_model_checkpoint(
        job.job_id,
        operation="classify-objective-1",
        model_alias="source-objective-proposal",
        prompt_sha256="a" * 64,
        input_sha256="c" * 64,
        output_schema="ObjectiveClassificationDraft:v1",
    ) == {"candidate_id": "candidate-2"}

    assert job.workflow_stage == ObjectiveJobStage.DRAFT
    assert job.processing_status == ObjectiveProcessingStatus.QUEUED

    claimed = job_repository.claim_next_objective_job("worker-1")
    job_repository.update_objective_job_progress(
        claimed.job_id,
        operation="map-section",
        completed_operations=3,
        progress_detail={"preliminary_candidate_count": 2},
    )
    job_repository.update_objective_job_progress(
        claimed.job_id,
        operation="verify-objective",
        completed_operations=4,
        progress_detail={"state": "running"},
    )
    progressing = job_repository.get_objective_job(claimed.job_id)
    assert progressing.current_operation == "verify-objective"
    assert progressing.completed_operations == 4
    assert progressing.progress_detail == {
        "preliminary_candidate_count": 2,
        "state": "running",
    }
    reviewed = job_repository.complete_decomposition(
        claimed.job_id,
        workspace_id="workspace-1",
        workspace_revision=1,
        prompt_runs=[
            {
                "prompt_run_id": "prompt-run-1",
                "operation": "propose-objectives",
                "prompt_id": "source-objective-candidate-formation",
                "prompt_version": "v1",
                "prompt_sha256": "a" * 64,
                "prompt_filename": "candidate_formation.md",
                "prompt_snapshot": "Prompt snapshot v1",
                "model_alias": "source-objective-proposal",
                "input_sha256": "b" * 64,
                "input_snapshot": "{\"claims\":[]}",
                "output_schema": "ObjectiveProposalDraft",
            }
        ],
    )
    decision = job_repository.record_review(
        reviewed.job_id,
        candidate_id="candidate-1",
        review_kind=ObjectiveReviewKind.OBJECTIVE,
        status=ObjectiveDecisionStatus.APPROVED,
        decided_by="lds@example.com",
    )
    completed = job_repository.advance_objective_job(
        reviewed.job_id,
        expected_version=job_repository.get_objective_job(reviewed.job_id).version,
        actor="lds@example.com",
    )

    assert decision.status == ObjectiveDecisionStatus.APPROVED
    assert completed.workflow_stage == ObjectiveJobStage.COMPLETE
    assert job_repository.list_prompt_runs(job.job_id)[0].prompt_snapshot == "Prompt snapshot v1"
    assert job_repository.list_prompt_runs(job.job_id)[0].input_snapshot == '{"claims":[]}'
    assert job_repository.count_prompt_runs(job.job_id) == 1
    summary = job_repository.list_prompt_run_summaries(job.job_id)[0]
    assert summary["prompt_run_id"] == "prompt-run-1"
    assert "prompt_snapshot" not in summary
    assert "input_snapshot" not in summary
    assert job_repository.get_prompt_run(job.job_id, summary["prompt_run_id"]).input_snapshot == '{"claims":[]}'
    assert [event.event_type for event in job_repository.list_job_events(job.job_id)] == [
        "created",
        "processing_started",
        "decomposition_completed",
        "review_recorded",
        "stage_advanced",
    ]


def test_rlo_draft_jobs_are_idempotent_and_use_expected_state(repo):
    source = create(repo, "8")
    repo.create_source_collection(
        collection_id="draft-collection",
        title="Draft materials",
        members=[(source.source_version_id, None)],
    )
    brief = LearningBrief(
        brief_id="draft-brief",
        collection_id="draft-collection",
        lenses=[
            PractitionerLens(
                lens_id="lens-draft",
                title="Practitioner",
                practitioner_role="Consultant",
                relevant_tasks=["Apply the source"],
                rationale="The source supports the task.",
                inferred=True,
            )
        ],
        source_map_revision="source-map-v1",
        brief_revision="source-map-v1:draft",
    )
    authoring_repository.save_learning_brief(brief)
    authoring_repository.create_objective_workspace(
        "draft-workspace", "draft-collection", created_by="admin-1"
    )
    authoring_repository.save_workspace_revision(
        ObjectiveWorkspace(
            workspace_id="draft-workspace",
            collection_id="draft-collection",
            revision=1,
            learning_brief=brief,
            candidates=[
                drafting_workspace().candidates[0].model_copy(
                    update={"candidate_id": "candidate-1"}
                )
            ],
        ),
        model_metadata={},
    )
    request = RLODraftRequest(
        workspace_id="draft-workspace",
        workspace_revision=1,
        candidate_id="candidate-1",
        rlo_id="rlo-draft-1",
        rlo_version="0.1.0",
    )

    first = draft_repository.create_draft_job(request, created_by="admin-1")
    resumed = draft_repository.create_draft_job(request, created_by="admin-1")
    from tests.source_content.test_rlo_drafting import _rlo

    draft = _rlo(
        {
            "candidate": {"statement": "Prepare coffee using the available machine."},
            "sources": [
                {
                    "id": "src-01",
                    "title": "Source 8",
                    "reference": "source-8.pdf",
                    "authority": "primary",
                    "ingested_source_id": source.source_id,
                    "source_version_id": source.source_version_id,
                    "checksum": "8" * 64,
                    "canonical_locator": "source-8.pdf",
                }
            ],
            "evidence": [
                {
                    "id": "ev-brew",
                    "source_ref": "src-01",
                    "source_version_id": source.source_version_id,
                    "node_ids": ["node-brew"],
                    "locator": "page 1",
                    "role": "objective_defining",
                }
            ],
        },
        request.model_dump(mode="json"),
    )
    approved = first.model_copy(
        update={"state": RLODraftState.APPROVED, "draft": draft, "revision": 1}
    )
    draft_repository.save_draft_job(
        approved, expected_state=RLODraftState.QUEUED, save_revision=True
    )
    published = draft_repository.mark_published(
        first.job_id, rlo_id=draft.id, rlo_version=draft.version
    )

    assert resumed.job_id == first.job_id
    assert published.state == RLODraftState.PUBLISHED
    assert draft_repository.published_dependencies(source.source_version_id)[0][
        "rlo_id"
    ] == draft.id
    assert draft_repository.source_has_published_dependencies(source.source_id)
    with pytest.raises(draft_repository.DraftStateConflict):
        draft_repository.save_draft_job(
            approved, expected_state=RLODraftState.QUEUED
        )


def test_rlo_generation_batch_creates_restart_safe_child_jobs(repo):
    source = create(repo, "a")
    repo.create_source_collection(
        collection_id="generation-collection",
        title="Generation materials",
        members=[(source.source_version_id, None)],
    )
    objective_job = job_repository.create_objective_job(
        source.job_id,
        "generation-collection",
        created_by="admin-1",
        job_id="objective-generation-1",
    )
    brief = LearningBrief(
        brief_id="generation-brief",
        collection_id="generation-collection",
        lenses=[
            PractitionerLens(
                lens_id="generation-lens",
                title="Practitioner",
                practitioner_role="Consultant",
                relevant_tasks=["Apply the source"],
                rationale="The source supports the task.",
                inferred=True,
            )
        ],
        source_map_revision="generation-map-v1",
        brief_revision="generation-map-v1:default",
    )
    authoring_repository.save_learning_brief(brief)
    authoring_repository.create_objective_workspace(
        "workspace-generation-1", "generation-collection", created_by="admin-1"
    )
    base_candidate = drafting_workspace().candidates[0]
    outside_classification = base_candidate.classification.model_copy(
        update={
            "content_kind": base_candidate.classification.content_kind.model_copy(
                update={"value": ObjectiveContentType.PRINCIPLE}
            ),
            "bloom": base_candidate.classification.bloom.model_copy(
                update={"value": ObjectiveBloomLevel.ANALYZE}
            ),
        }
    )
    outside_candidate = base_candidate.model_copy(
        update={
            "candidate_id": "candidate-outside",
            "classification": outside_classification,
            "poc2_scope_status": ObjectiveScopeStatus.OUTSIDE_POC2_SCOPE,
            "poc2_scope_reason": "principle × analyze is outside POC2 scope.",
        }
    )
    authoring_repository.save_workspace_revision(
        ObjectiveWorkspace(
            workspace_id="workspace-generation-1",
            collection_id="generation-collection",
            revision=1,
            learning_brief=brief,
            candidates=[
                base_candidate.model_copy(
                    update={"candidate_id": candidate_id}
                )
                for candidate_id in ("candidate-one", "candidate-two")
            ]
            + [outside_candidate],
        ),
        model_metadata={},
    )
    first_package = SimpleNamespace(
        job_id=objective_job.job_id,
        workspace_id="workspace-generation-1",
        workspace_revision=1,
        collection_id="generation-collection",
        objectives=[
            drafting_workspace().candidates[0].model_copy(
                update={"candidate_id": "candidate-one"}
            )
        ],
    )
    expanded_package = SimpleNamespace(
        **{
            **first_package.__dict__,
            "objectives": [
                *first_package.objectives,
                drafting_workspace().candidates[0].model_copy(
                    update={"candidate_id": "candidate-two"}
                ),
                outside_candidate,
            ],
        }
    )

    batch = draft_repository.create_generation_batch(first_package, created_by="admin-1")
    resumed = draft_repository.create_generation_batch(
        expanded_package, created_by="admin-1"
    )
    claimed = draft_repository.claim_next_draft_job(lease_seconds=30)
    second_claimed = draft_repository.claim_next_draft_job(lease_seconds=30)
    draft_repository.save_generation_checkpoint(
        claimed.job_id,
        operation="target-classification",
        sequence=1,
        input_hash="a" * 64,
        payload={"cell": "procedure-apply"},
    )
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["SOURCE_POSTGRES_TEST_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE source_rlo_draft_jobs "
                "SET lease_expires_at = :expired WHERE job_id = :job_id"
            ),
            {
                "expired": datetime.now(timezone.utc) - timedelta(seconds=1),
                "job_id": claimed.job_id,
            },
        )
    engine.dispose()
    reclaimed = draft_repository.claim_next_draft_job(lease_seconds=30)
    draft_repository.save_draft_job(
        reclaimed.model_copy(update={"state": RLODraftState.IN_REVIEW}),
        expected_state=RLODraftState.PLANNING,
    )
    draft_repository.save_draft_job(
        second_claimed.model_copy(update={"state": RLODraftState.IN_REVIEW}),
        expected_state=RLODraftState.PLANNING,
    )
    finalized = draft_repository.create_generation_batch(
        expanded_package, created_by="admin-1", finalized=True
    )
    refreshed = draft_repository.refresh_generation_batch(finalized.batch_id)
    collection_claim = draft_repository.claim_next_collection_validation_batch()
    validated = draft_repository.complete_collection_validation(
        collection_claim.batch_id, []
    )
    failed = draft_repository.save_draft_job(
        draft_repository.get_draft_job(claimed.job_id).model_copy(
            update={"state": RLODraftState.FAILED, "retryable": False}
        ),
        expected_state=RLODraftState.IN_REVIEW,
    )
    retried = draft_repository.retry_draft_job(failed.job_id)

    assert resumed.batch_id == batch.batch_id
    assert len(batch.child_job_ids) == 1
    assert len(resumed.child_job_ids) == 3
    outside_job = next(
        draft_repository.get_draft_job(job_id)
        for job_id in resumed.child_job_ids
        if draft_repository.get_draft_job(job_id).request.candidate_id
        == "candidate-outside"
    )
    assert outside_job.state == RLODraftState.FAILED
    assert outside_job.retryable is False
    assert "outside POC2 authoring scope" in outside_job.error_message
    assert claimed.state == RLODraftState.PLANNING
    assert claimed.attempt == 1
    assert reclaimed.job_id == claimed.job_id
    assert reclaimed.attempt == 2
    assert draft_repository.list_generation_checkpoints(claimed.job_id)[0].payload == {
        "cell": "procedure-apply"
    }
    assert refreshed.state.value == "in_review"
    assert refreshed.finalized is True
    assert validated.collection_validated_at is not None
    assert retried.state == RLODraftState.QUEUED


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("SOURCE_INGESTION_DATABASE_URL", raising=False)
    repository.reset_repository_for_tests()

    with pytest.raises(RuntimeError, match="is required"):
        repository.init_db()


def test_non_postgres_database_is_rejected(monkeypatch):
    monkeypatch.setenv("SOURCE_INGESTION_DATABASE_URL", "sqlite:///source.db")
    repository.reset_repository_for_tests()

    with pytest.raises(RuntimeError, match="must use postgresql"):
        repository.init_db()

    repository.reset_repository_for_tests()
