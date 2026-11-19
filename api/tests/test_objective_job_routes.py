import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import openpyxl
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import objective_jobs
from src.objective_jobs import (
    CreateObjectiveJobRequest,
    CurriculumDomainReviewRequest,
    ReviewRequest,
    router,
)
from src.source_authoring.contracts import (
    CandidateCoverageAssignment,
    CurriculumCoverageReport,
    CurriculumDomain,
    CurriculumDomainCoverage,
    CurriculumGapDiscoveryRecord,
    CurriculumGapTarget,
    CurriculumGapTargetDiscoveryRecord,
    DocumentCurriculumBlueprint,
    GapTargetAlignment,
    ObjectiveDecisionStatus,
    ObjectiveWorkspace,
)

from tests.source_content.test_rlo_drafting import _workspace
from tests.source_content.test_objective_pipeline import (
    ObjectiveResponses,
    WorkspaceStore,
    _collection_map,
    _document,
    _proposal,
)
from src.source_authoring.objectives import ObjectiveDiscoveryService


def test_objective_job_workflow_routes_are_registered():
    routes = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }

    expected = {
        ("/api/objective-jobs", "POST"),
        ("/api/objective-jobs/{job_id}/candidates", "GET"),
        ("/api/objective-jobs/{job_id}/coverage", "GET"),
        ("/api/objective-jobs/{job_id}/coverage/domains/{domain_id}", "PATCH"),
        ("/api/objective-jobs/{job_id}/candidates", "POST"),
        ("/api/objective-jobs/{job_id}/candidates/{candidate_id}", "PATCH"),
        (
            "/api/objective-jobs/{job_id}/candidates/{candidate_id}/reclassify",
            "POST",
        ),
        ("/api/objective-jobs/{job_id}/candidates/{candidate_id}/split", "POST"),
        ("/api/objective-jobs/{job_id}/candidates/merge", "POST"),
        ("/api/objective-jobs/{job_id}/source-features", "GET"),
        ("/api/objective-jobs/{job_id}/candidates/{candidate_id}/evidence", "GET"),
        ("/api/objective-jobs/{job_id}/candidates/{candidate_id}/reviews", "POST"),
        ("/api/objective-jobs/{job_id}/advance", "POST"),
        ("/api/objective-jobs/{job_id}/prompts/{prompt_run_id}", "GET"),
        ("/api/objective-jobs/{job_id}/package", "GET"),
        ("/api/objective-jobs/{job_id}/export.xlsx", "GET"),
    }

    assert expected <= routes


def test_gap_candidate_lookup_preserves_target_and_alignment():
    target = CurriculumGapTarget(
        target_id="target-1",
        domain_id="domain-1",
        performance="Select an appropriate supported response.",
        rationale="The performance advances the curriculum purpose.",
        claim_ids=["claim-1"],
        evidence_sufficiency="sufficient",
        sufficiency_rationale="The claim defines the decision boundary.",
        search_warranted=True,
    )
    alignment = GapTargetAlignment(
        target_id=target.target_id,
        candidate_id="candidate-1",
        alignment="direct",
        rationale="The objective directly teaches the missing performance.",
        claim_ids_used=["claim-1"],
    )
    target_record = CurriculumGapTargetDiscoveryRecord(
        target=target,
        selected_for_discovery=True,
        prompt_run_ids=["prompt-1"],
        proposed_candidate_ids=["candidate-1"],
        alignments=[alignment],
        direct_candidate_ids=["candidate-1"],
        no_candidate_found=False,
    )
    domain_record = CurriculumGapDiscoveryRecord(
        domain_id="domain-1",
        initial_state="partial",
        warranted=True,
        selected_for_discovery=True,
        eligibility_rationale="One target warranted focused discovery.",
        prompt_run_ids=["prompt-1"],
        proposed_candidate_ids=["candidate-1"],
        accepted_candidate_ids=["candidate-1"],
        target_records=[target_record],
        no_candidate_found=False,
    )
    coverage = CurriculumCoverageReport(
        report_id="coverage-1",
        blueprint_id="blueprint-1",
        workspace_revision=1,
        domain_coverage=[
            CurriculumDomainCoverage(
                domain_id="domain-1",
                state="partial",
                rationale="One performance remains unresolved.",
                missing_performances=[target.performance],
                gap_targets=[target],
                gap_discovery_warranted=True,
                gap_discovery_rationale="One target warrants focused discovery.",
            )
        ],
        gap_candidate_ids=["candidate-1"],
        gap_discovery_records=[domain_record],
    )

    value = objective_jobs._gap_records_by_candidate(coverage)["candidate-1"]

    assert value["domain_record"] == domain_record
    assert value["target_record"] == target_record
    assert value["alignment"] == alignment


def test_load_workspace_marks_incompatible_results_for_regeneration(monkeypatch):
    def load_incompatible_workspace(*_args):
        ObjectiveWorkspace.model_validate({})

    monkeypatch.setattr(
        objective_jobs.workspace_repository,
        "get_objective_workspace",
        load_incompatible_workspace,
    )

    workspace, error = objective_jobs._load_workspace(
        SimpleNamespace(workspace_id="workspace-1", workspace_revision=1)
    )

    assert workspace is None
    assert error == "Objective results use an older format and must be regenerated."


def test_objective_export_keeps_review_sheet_concise(monkeypatch):
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        gap_proposals=[_proposal("gap-brew")],
        force_partial_coverage=True,
    )
    workspace = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    ).discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )
    job = SimpleNamespace(job_id="job-1")
    monkeypatch.setattr(
        objective_jobs.job_repository, "get_objective_job", lambda _id: job
    )
    monkeypatch.setattr(objective_jobs, "_workspace_for", lambda _job: workspace)
    monkeypatch.setattr(
        objective_jobs.job_repository, "list_latest_reviews", lambda _id: []
    )
    monkeypatch.setattr(
        objective_jobs, "_evidence_details", lambda *_args, **_kwargs: []
    )

    response = asyncio.run(objective_jobs.export_candidates(job.job_id))
    workbook = openpyxl.load_workbook(BytesIO(response.body), data_only=True)
    objective_rows = list(workbook["Proposed objectives"].values)
    assert objective_rows[0] == (
        "Proposed learning objective",
        "Discovery basis",
        "Source support",
        "What the source contributes",
        "Knowledge still needed",
        "Anticipated model contribution",
        "Suggested Bloom level",
        "Suggested content kind",
        "Combined classification confidence",
        "Plausible alternatives",
        "Practitioner relevance",
        "Source location",
        "Review status",
        "Learning team feedback",
    )
    coverage_headers = list(workbook["Curriculum coverage"].values)[3]
    assert "Initial gap discovery warranted" in coverage_headers
    assert "Initial target discovery outcomes" in coverage_headers


def test_curriculum_domain_review_records_lds_adjustment(monkeypatch):
    base = _workspace()
    candidate_id = base.candidates[0].candidate_id
    blueprint = DocumentCurriculumBlueprint(
        blueprint_id="blueprint-1",
        collection_id=base.collection_id,
        source_map_revision=base.learning_brief.source_map_revision,
        central_purpose="Teach a repeatable coffee preparation process.",
        central_claim_ids=["claim-brew"],
        intended_use="Support reliable coffee preparation.",
        domains=[
            CurriculumDomain(
                domain_id="domain-brew",
                title="Coffee preparation",
                description="Operate the available machine.",
                ordinal=1,
                importance="core",
                rationale="This is the source's main procedure.",
                claim_ids=["claim-brew"],
            )
        ],
    )
    coverage = CurriculumCoverageReport(
        report_id="coverage-1",
        blueprint_id=blueprint.blueprint_id,
        workspace_revision=base.revision,
        assignments=[
            CandidateCoverageAssignment(
                candidate_id=candidate_id,
                domain_ids=["domain-brew"],
                role="primary",
                contribution="Teaches the core machine operation.",
            )
        ],
        domain_coverage=[
            CurriculumDomainCoverage(
                domain_id="domain-brew",
                state="adequate",
                candidate_ids=[candidate_id],
                rationale="The objective covers the core procedure.",
            )
        ],
    )
    workspace = ObjectiveWorkspace.model_validate(
        {
            **base.model_dump(mode="json"),
            "curriculum_blueprint": blueprint.model_dump(mode="json"),
            "curriculum_coverage": coverage.model_dump(mode="json"),
        }
    )
    job = SimpleNamespace(
        job_id="objective-job-1",
        version=3,
        workflow_stage=objective_jobs.ObjectiveJobStage.OBJECTIVE_REVIEW,
    )
    saved = []
    monkeypatch.setattr(
        objective_jobs.job_repository, "get_objective_job", lambda _id: job
    )
    monkeypatch.setattr(objective_jobs, "_workspace_for", lambda _job: workspace)
    monkeypatch.setattr(
        objective_jobs.workspace_repository,
        "save_workspace_revision",
        lambda value, **_kwargs: saved.append(value),
    )
    monkeypatch.setattr(
        objective_jobs.job_repository,
        "update_job_workspace_revision",
        lambda *_args, **_kwargs: SimpleNamespace(job_id=job.job_id, version=4),
    )
    monkeypatch.setattr(
        objective_jobs, "_job_summary", lambda updated: {"version": updated.version}
    )
    monkeypatch.setattr(objective_jobs, "_actor", lambda _request: "lds-1")

    result = asyncio.run(
        objective_jobs.review_curriculum_domain(
            job.job_id,
            "domain-brew",
            CurriculumDomainReviewRequest(
                importance="supporting",
                acknowledged=True,
                expected_job_version=3,
            ),
            Request({"type": "http", "headers": []}),
        )
    )

    assert result == {"version": 4}
    assert saved[0].curriculum_blueprint.domains[0].importance == "supporting"
    assert saved[0].curriculum_coverage.acknowledged_domain_ids == ["domain-brew"]
    assert saved[0].curriculum_coverage.workspace_revision == workspace.revision


def test_part_availability_always_returns_seven_ordered_source_results(monkeypatch):
    features = [
        SimpleNamespace(
            feature_id="feature-teach",
            feature_type="core_substance",
            status="observed",
            title="Lifecycle explanation",
        ),
        SimpleNamespace(
            feature_id="feature-check",
            feature_type="assessment",
            status="uncertain",
            title="Knowledge check",
        ),
    ]
    monkeypatch.setattr(
        objective_jobs,
        "_evidence_details",
        lambda _job, feature, _bundles: [{"node_id": feature.feature_id}],
    )

    candidate = SimpleNamespace(feature_id="candidate", evidence=[])
    parts = objective_jobs._part_availability(
        SimpleNamespace(), candidate, features, {}
    )

    assert [part["part"] for part in parts] == [
        "cover",
        "setup",
        "teach",
        "show",
        "practice",
        "check",
        "sendoff",
    ]
    assert parts[2]["status"] == "found"
    assert parts[2]["evidence_count"] == 1
    assert parts[5]["status"] == "possible"
    assert parts[0]["status"] == "found"
    assert "source provenance" in parts[0]["summary"]


def test_repeated_source_job_reuses_its_existing_automatic_collection(monkeypatch):
    source = SimpleNamespace(
        status="ready",
        source_version_id="source-version-1",
        run_id="source-run-1",
        original_filename="source.pdf",
    )
    collection = SimpleNamespace(collection_id="objective-source-source-version-1")
    create_collection = Mock()
    created_job = SimpleNamespace(job_id="objective-job-2")
    monkeypatch.setattr(objective_jobs, "get_job", lambda _source_run_id: source)
    monkeypatch.setattr(
        objective_jobs,
        "get_source_collection",
        lambda collection_id: collection
        if collection_id == collection.collection_id
        else None,
    )
    monkeypatch.setattr(objective_jobs, "create_source_collection", create_collection)
    monkeypatch.setattr(
        objective_jobs.job_repository,
        "create_objective_job",
        lambda *_args, **_kwargs: created_job,
    )
    monkeypatch.setattr(
        objective_jobs, "_job_summary", lambda job: {"job_id": job.job_id}
    )
    request = Request({"type": "http", "headers": []})

    result = asyncio.run(
        objective_jobs.create_job(
            CreateObjectiveJobRequest(source_run_id="source-run-1"), request
        )
    )

    assert result == {"job_id": "objective-job-2"}
    create_collection.assert_not_called()


def test_completed_package_contains_only_approved_objectives(monkeypatch):
    workspace = _workspace()
    candidate = workspace.candidates[0]
    monkeypatch.setattr(
        objective_jobs.job_repository,
        "list_latest_reviews",
        lambda *_args: [
            SimpleNamespace(
                candidate_id=candidate.candidate_id,
                status=ObjectiveDecisionStatus.APPROVED,
            )
        ],
    )

    package = objective_jobs._completed_package(
        SimpleNamespace(job_id="objective-job-1"), workspace
    )

    assert package.job_id == "objective-job-1"
    assert [item.candidate_id for item in package.objectives] == [
        candidate.candidate_id
    ]


def test_approving_objective_immediately_creates_its_rlo_job(monkeypatch):
    workspace = _workspace()
    candidate = workspace.candidates[0]
    job = SimpleNamespace(job_id="objective-job-1")
    decision = SimpleNamespace(status=ObjectiveDecisionStatus.APPROVED)
    package = SimpleNamespace(job_id=job.job_id, objectives=[candidate])
    created = []
    monkeypatch.setattr(
        objective_jobs.job_repository, "get_objective_job", lambda _id: job
    )
    monkeypatch.setattr(objective_jobs, "_workspace_for", lambda _job: workspace)
    monkeypatch.setattr(
        objective_jobs.draft_repository,
        "get_generation_job_for_candidate",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        objective_jobs.job_repository,
        "record_review",
        lambda *_args, **_kwargs: decision,
    )
    monkeypatch.setattr(objective_jobs, "_completed_package", lambda *_args: package)
    monkeypatch.setattr(
        objective_jobs.draft_repository,
        "create_generation_batch",
        lambda value, **_kwargs: created.append(value),
    )

    result = asyncio.run(
        objective_jobs.review_candidate(
            job.job_id,
            candidate.candidate_id,
            ReviewRequest(review_kind="objective", status="approved"),
            Request({"type": "http", "headers": []}),
        )
    )

    assert result is decision
    assert created == [package]


def test_outside_scope_objective_cannot_be_approved_or_recorded(monkeypatch):
    workspace = _workspace()
    candidate = workspace.candidates[0].model_copy(
        update={
            "poc2_scope_status": "outside_poc2_scope",
            "poc2_scope_reason": "Concept × Analyze is outside POC2 scope.",
        }
    )
    workspace = workspace.model_copy(update={"candidates": [candidate]})
    job = SimpleNamespace(job_id="objective-job-1")
    recorded = []
    monkeypatch.setattr(
        objective_jobs.job_repository, "get_objective_job", lambda _id: job
    )
    monkeypatch.setattr(objective_jobs, "_workspace_for", lambda _job: workspace)
    monkeypatch.setattr(
        objective_jobs.draft_repository,
        "get_generation_job_for_candidate",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        objective_jobs.job_repository,
        "record_review",
        lambda *_args, **_kwargs: recorded.append(True),
    )

    with pytest.raises(HTTPException, match="outside POC2") as exc:
        asyncio.run(
            objective_jobs.review_candidate(
                job.job_id,
                candidate.candidate_id,
                ReviewRequest(review_kind="objective", status="approved"),
                Request({"type": "http", "headers": []}),
            )
        )

    assert exc.value.status_code == 409
    assert recorded == []
