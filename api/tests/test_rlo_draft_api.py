import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import app
from src.source_authoring.authoring_contracts import GuidanceAssessment
from src.source_authoring.draft_contracts import (
    RLODraftState,
    RLORevisionPlan,
    RLORevisionSubmission,
)
from src.source_authoring.methodology import get_methodology_profile
from src.source_drafts import (
    approve_and_publish_rlo,
    export_rlo_draft,
    export_rlo_review_metadata,
    publish_rlo_draft,
    queue_rlo_revision,
)


def test_review_metadata_export_summarizes_provenance(monkeypatch):
    profile = get_methodology_profile("procedure", "apply")
    authoring = SimpleNamespace(
        authoring_revision_id="authoring-revision-1",
        claims=[],
        parts=[],
        llm_knowledge_provenance=[],
        methodology_profile=profile,
        guidance_assessments=[
            GuidanceAssessment(
                guidance_id=profile.guidance[0].guidance_id,
                status="approximated",
                explanation="The interaction uses a lower-fidelity equivalent.",
            )
        ],
    )
    job = SimpleNamespace(
        job_id="job-1",
        request=SimpleNamespace(rlo_id="rlo-1", rlo_version="0.1.0"),
        authoring=authoring,
        state=RLODraftState.IN_REVIEW,
        reviews=[],
    )
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.get_draft_job", lambda _job_id: job
    )

    response = asyncio.run(export_rlo_review_metadata("job-1"))

    assert response.headers["content-disposition"] == (
        'attachment; filename="rlo-1-review-metadata.json"'
    )
    assert b'"schema_version":"source-rlo-review-metadata-v2"' in response.body
    assert b'"llm_domain_claims":0' in response.body
    assert b'"profile_id":"procedure-apply"' in response.body
    assert b'"status":"approximated"' in response.body
    assert profile.intent.encode() in response.body


def test_draft_export_downloads_catalog_ready_rlo(monkeypatch):
    draft = SimpleNamespace(
        model_dump_json=lambda **_kwargs: '{\n  "id": "rlo-EO-03"\n}'
    )
    job = SimpleNamespace(
        request=SimpleNamespace(rlo_id="rlo-EO-03", rlo_version="0.1.0"),
        draft=draft,
    )
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.get_draft_job", lambda _job_id: job
    )

    response = asyncio.run(export_rlo_draft("job-1"))

    assert response.headers["content-disposition"] == (
        'attachment; filename="rlo-EO-03-0.1.0.json"'
    )
    assert response.media_type == "application/json"
    assert response.body == b'{\n  "id": "rlo-EO-03"\n}'


def test_draft_export_rejects_job_without_catalog_ready_rlo(monkeypatch):
    job = SimpleNamespace(draft=None)
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.get_draft_job", lambda _job_id: job
    )

    with pytest.raises(HTTPException, match="catalog-ready RLO") as exc:
        asyncio.run(export_rlo_draft("job-1"))

    assert exc.value.status_code == 409


def test_publish_uses_existing_catalog_ingestion_boundary(monkeypatch):
    draft = SimpleNamespace(model_dump_json=lambda **_kwargs: '{"id":"rlo-1"}')
    approved = SimpleNamespace(state=RLODraftState.APPROVED, draft=draft)
    published = SimpleNamespace(state=RLODraftState.PUBLISHED)
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.get_draft_job", lambda _job_id: approved
    )
    monkeypatch.setattr(
        app,
        "_ingest",
        lambda body: SimpleNamespace(rlo_id="rlo-1", rlo_version="0.1.0"),
    )
    calls = []

    def mark(job_id, *, rlo_id, rlo_version):
        calls.append((job_id, rlo_id, rlo_version))
        return published

    monkeypatch.setattr("src.source_drafts.draft_repository.mark_published", mark)

    result = asyncio.run(publish_rlo_draft("job-1"))

    assert result.state == RLODraftState.PUBLISHED
    assert calls == [("job-1", "rlo-1", "0.1.0")]


def test_publish_rejects_unapproved_draft_before_catalog_ingestion(monkeypatch):
    draft = SimpleNamespace(model_dump_json=lambda **_kwargs: '{"id":"rlo-1"}')
    in_review = SimpleNamespace(state=RLODraftState.IN_REVIEW, draft=draft)
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.get_draft_job", lambda _job_id: in_review
    )
    ingested = []
    monkeypatch.setattr(app, "_ingest", lambda body: ingested.append(body))

    with pytest.raises(HTTPException, match="approved draft") as exc:
        asyncio.run(publish_rlo_draft("job-1"))

    assert exc.value.status_code == 409
    assert ingested == []


def test_approve_publish_can_resume_when_approval_already_succeeded(monkeypatch):
    draft = SimpleNamespace(model_dump_json=lambda **_kwargs: '{"id":"rlo-1"}')
    approved = SimpleNamespace(state=RLODraftState.APPROVED, draft=draft)
    published = SimpleNamespace(state=RLODraftState.PUBLISHED)
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.get_draft_job", lambda _job_id: approved
    )
    monkeypatch.setattr(
        app,
        "_ingest",
        lambda body: SimpleNamespace(rlo_id="rlo-1", rlo_version="0.1.0"),
    )
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.mark_published",
        lambda *_args, **_kwargs: published,
    )
    request = Request({"type": "http", "headers": []})

    result = asyncio.run(approve_and_publish_rlo("job-1", request))

    assert result.state == RLODraftState.PUBLISHED


def test_scoped_revision_submission_queues_confirmed_two_call_plan(monkeypatch):
    job = SimpleNamespace(state=RLODraftState.VALIDATION_FAILED)
    plan = RLORevisionPlan(
        action="repair_assessment",
        selected_finding_ids=["finding-123456789abc"],
        affected_parts=["check"],
        affected_element_ids=["check-01"],
        required_validator="pedagogy",
        reused_operations=["source-mapping-0001"],
        executable=True,
    )
    queued = SimpleNamespace(state=RLODraftState.QUEUED)
    captured = []
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.get_draft_job", lambda _job_id: job
    )
    monkeypatch.setattr("src.source_drafts.build_revision_plan", lambda *_args: plan)
    monkeypatch.setattr(
        "src.source_drafts.draft_repository.queue_scoped_revision",
        lambda job_id, pending: captured.append((job_id, pending)) or queued,
    )
    request = Request({"type": "http", "headers": []})
    payload = RLORevisionSubmission(
        action="repair_assessment",
        selected_finding_ids=["finding-123456789abc"],
        instruction="Clarify only the selected Check.",
        maximum_model_calls=2,
    )

    result = asyncio.run(queue_rlo_revision("job-1", payload, request))

    assert result.state == RLODraftState.QUEUED
    assert captured[0][0] == "job-1"
    pending = captured[0][1]
    assert pending.plan.maximum_model_calls == 2
    assert pending.instruction == "Clarify only the selected Check."
    assert pending.base_state == RLODraftState.VALIDATION_FAILED
