"""Authenticated APIs for objective extraction and LDS review jobs."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from poc_auth import require_authenticated_request
from pydantic import BaseModel, Field, ValidationError, model_validator

from .source_authoring import (
    draft_repository,
    job_repository,
    repository as workspace_repository,
)
from .source_authoring.cell_scope import candidate_scope_error
from .source_authoring.contracts import (
    CompletedObjectivePackage,
    CurriculumImportance,
    ObjectiveCandidate,
    ObjectiveDecisionStatus,
    ObjectiveOrigin,
    ObjectiveScopeStatus,
    PractitionerInstructions,
)
from .source_authoring.job_contracts import (
    ObjectiveJobStage,
    ObjectiveReviewKind,
)
from .source_authoring.objectives import ObjectiveDiscoveryService
from .source_ingestion.repository import (
    InvalidStateTransition,
    create_source_collection,
    get_job,
    get_latest_job_for_source_version,
    get_source_collection,
)


router = APIRouter(
    prefix="/api/objective-jobs",
    tags=["objective-jobs"],
    dependencies=[Depends(require_authenticated_request)],
)


class CreateObjectiveJobRequest(BaseModel):
    source_run_id: str | None = Field(default=None, min_length=1)
    collection_id: str | None = Field(default=None, min_length=1)
    roles: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    service_line: str | None = None
    industry: str | None = None
    additional_context: str | None = None

    @model_validator(mode="after")
    def identifies_source(self):
        if not self.source_run_id and not self.collection_id:
            raise ValueError("source_run_id or collection_id is required")
        return self


class ReviewRequest(BaseModel):
    review_kind: ObjectiveReviewKind
    status: ObjectiveDecisionStatus
    note: str | None = None


class CandidateEditRequest(BaseModel):
    statement: str | None = Field(default=None, min_length=1)
    observable_behavior: str | None = Field(default=None, min_length=1)
    performance_context: str | None = Field(default=None, min_length=1)
    practitioner_relevance: str | None = Field(default=None, min_length=1)
    bloom_level: str | None = None
    scope: str | None = Field(default=None, min_length=1)
    prerequisites: list[str] | None = None
    expected_effort_minutes: int | None = Field(default=None, ge=1)
    source_feature_ids: list[str] | None = None
    expected_job_version: int = Field(ge=1)

    @model_validator(mode="after")
    def includes_edit(self):
        if not self.model_dump(exclude={"expected_job_version"}, exclude_none=True):
            raise ValueError("at least one candidate field is required")
        return self


class AddCandidateRequest(BaseModel):
    statement: str = Field(min_length=1)
    based_on_candidate_id: str = Field(min_length=1)
    expected_job_version: int = Field(ge=1)


class SplitCandidateRequest(BaseModel):
    statements: list[str] = Field(min_length=2)
    expected_job_version: int = Field(ge=1)


class MergeCandidatesRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=2)
    statement: str = Field(min_length=1)
    expected_job_version: int = Field(ge=1)


class AdvanceRequest(BaseModel):
    expected_job_version: int = Field(ge=1)
    note: str | None = None


class ReclassifyCandidateRequest(BaseModel):
    expected_job_version: int = Field(ge=1)


class CurriculumDomainReviewRequest(BaseModel):
    importance: CurriculumImportance | None = None
    acknowledged: bool | None = None
    expected_job_version: int = Field(ge=1)

    @model_validator(mode="after")
    def includes_review(self):
        if self.importance is None and self.acknowledged is None:
            raise ValueError("importance or acknowledged is required")
        return self


def _actor(request: Request) -> str:
    return require_authenticated_request(request) or "learning-admin"


def _instructions(payload: CreateObjectiveJobRequest) -> PractitionerInstructions | None:
    values = payload.model_dump(exclude={"source_run_id", "collection_id"})
    if not any(value for value in values.values()):
        return None
    return PractitionerInstructions(**values)


def _load_workspace(job):
    if not job.workspace_id or not job.workspace_revision:
        return None, None
    try:
        return (
            workspace_repository.get_objective_workspace(
                job.workspace_id, job.workspace_revision
            ),
            None,
        )
    except ValidationError:
        return None, "Objective results use an older format and must be regenerated."


def _job_summary(job) -> dict:
    source = get_job(job.source_run_id)
    collection = get_source_collection(job.collection_id)
    workspace, workspace_error = _load_workspace(job)
    reviews = job_repository.list_latest_reviews(job.job_id)
    prompt_count = job_repository.count_prompt_runs(job.job_id)
    rlo_batch = draft_repository.get_generation_batch_for_objective_job(job.job_id)
    if rlo_batch:
        rlo_batch = draft_repository.refresh_generation_batch(rlo_batch.batch_id)
    counts = Counter(str(review.status) for review in reviews)
    current_operation = job.current_operation
    if current_operation is None and str(job.processing_status) == "queued":
        current_operation = "Waiting for a worker"
    return {
        **job.model_dump(mode="json"),
        "source_filename": source.original_filename if source else "Unknown source",
        "source_collection_title": collection.title if collection else "Unknown collection",
        "source_count": len(collection.members) if collection else 0,
        "candidate_count": len(workspace.candidates) if workspace else 0,
        "source_feature_count": len(workspace.source_features) if workspace else 0,
        "workspace_error": workspace_error,
        "review_counts": dict(counts),
        "retryable": job.attempt < 3
        if str(job.processing_status) == "failed"
        else job.retryable,
        "completed_model_operations": job.completed_operations,
        "persisted_prompt_runs": prompt_count,
        "current_operation": current_operation,
        "rlo_generation_batch": rlo_batch.model_dump(mode="json") if rlo_batch else None,
    }


@router.post("", status_code=202)
async def create_job(payload: CreateObjectiveJobRequest, request: Request):
    source = get_job(payload.source_run_id) if payload.source_run_id else None
    collection = get_source_collection(payload.collection_id) if payload.collection_id else None
    if collection and source is None:
        source = get_latest_job_for_source_version(collection.members[0].source_version_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source job not found.")
    if source.status != "ready":
        raise HTTPException(status_code=409, detail="Source extraction is not ready.")
    if collection:
        member_jobs = [
            get_latest_job_for_source_version(member.source_version_id)
            for member in collection.members
        ]
        if any(member_job is None or member_job.status != "ready" for member_job in member_jobs):
            raise HTTPException(
                status_code=409,
                detail="Every source in the collection must be extracted and ready.",
            )
    collection_id = collection.collection_id if collection else f"objective-source-{source.source_version_id}"
    if collection is None and get_source_collection(collection_id) is None:
        create_source_collection(
            collection_id,
            f"Objective source: {source.original_filename}",
            [(source.source_version_id, "Uploaded primary source")],
            created_by=_actor(request),
        )
    job = job_repository.create_objective_job(
        source.run_id if hasattr(source, "run_id") else source.job_id,
        collection_id,
        instructions=_instructions(payload),
        created_by=_actor(request),
    )
    return _job_summary(job)


@router.get("")
async def list_jobs():
    return [_job_summary(job) for job in job_repository.list_objective_jobs()]


@router.get("/{job_id}")
async def get_objective_job(job_id: str):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    result = _job_summary(job)
    result["events"] = [
        event.model_dump(mode="json")
        for event in job_repository.list_job_events(job_id)
    ]
    result["reviews"] = [
        review.model_dump(mode="json")
        for review in job_repository.list_latest_reviews(job_id)
    ]
    result["prompt_count"] = job_repository.count_prompt_runs(job_id)
    return result


def _workspace_for(job):
    if not job.workspace_id or not job.workspace_revision:
        raise HTTPException(status_code=409, detail="Objective results are not ready.")
    workspace, workspace_error = _load_workspace(job)
    if workspace_error:
        raise HTTPException(status_code=409, detail=workspace_error)
    if workspace is None:
        raise HTTPException(status_code=409, detail="Objective workspace is unavailable.")
    return workspace


def _evidence_details(job, candidate, bundles: dict | None = None) -> list[dict]:
    from .source_ingestion.artifacts import load_extraction

    bundles = bundles if bundles is not None else {}
    details = []
    for evidence in candidate.evidence:
        source_job = get_latest_job_for_source_version(evidence.source_version_id)
        if source_job is None:
            continue
        if source_job.job_id not in bundles:
            bundles[source_job.job_id] = load_extraction(source_job.job_id)
        bundle = bundles[source_job.job_id]
        nodes = {node.node_id: node for node in bundle.document.nodes}
        for node_id in evidence.node_ids:
            node = nodes.get(node_id)
            details.append(
                {
                    **evidence.model_dump(mode="json"),
                    "node_id": node_id,
                    "text": node.text if node else None,
                    "locators": [
                        locator.model_dump(mode="json") for locator in node.locators
                    ]
                    if node
                    else [],
                    "source_run_id": source_job.job_id,
                    "source_filename": source_job.original_filename,
                }
            )
    return details


def _source_location(detail: dict) -> str:
    locator = (detail.get("locators") or [{}])[0]
    if locator.get("page"):
        location = f"Page {locator['page']}"
    elif locator.get("slide"):
        location = f"Slide {locator['slide']}"
    elif locator.get("chapter"):
        location = f"Chapter {locator['chapter']}"
    elif locator.get("section"):
        location = f"Section {locator['section']}"
    else:
        location = "Source location unavailable"
    return f"{detail.get('source_filename', detail['source_version_id'])} — {location}"


def _curriculum_context(workspace):
    blueprint = workspace.curriculum_blueprint
    coverage = workspace.curriculum_coverage
    domains = {domain.domain_id: domain for domain in blueprint.domains} if blueprint else {}
    assignments = (
        {assignment.candidate_id: assignment for assignment in coverage.assignments}
        if coverage
        else {}
    )
    return blueprint, coverage, domains, assignments


def _gap_records_by_candidate(coverage):
    values = {}
    for domain_record in coverage.gap_discovery_records if coverage else []:
        for target_record in domain_record.target_records:
            alignments = {
                item.candidate_id: item for item in target_record.alignments
            }
            for candidate_id in [
                *target_record.direct_candidate_ids,
                *target_record.supporting_candidate_ids,
            ]:
                values[candidate_id] = {
                    "domain_record": domain_record,
                    "target_record": target_record,
                    "alignment": alignments.get(candidate_id),
                }
    return values


PART_FEATURE_TYPES = (
    ("cover", "Cover", {"explicit_objective"}),
    ("setup", "Set-up", {"explicit_objective", "prerequisite_transfer"}),
    ("teach", "Teach", {"core_substance", "structured_visual"}),
    ("show", "Show", {"worked_example"}),
    ("practice", "Practice", {"practice_activity"}),
    ("check", "Check", {"assessment"}),
    ("sendoff", "Send-off", {"prerequisite_transfer"}),
)


def _part_availability(job, candidate, features, bundles: dict) -> list[dict]:
    values = []
    for ordinal, (part, label, feature_types) in enumerate(PART_FEATURE_TYPES, start=1):
        matches = [
            feature
            for feature in features
            if str(feature.feature_type) in feature_types
        ]
        if part == "cover":
            status = "found"
            summary = "Objective identity, source provenance, and review metadata are available."
            evidence = _evidence_details(job, candidate, bundles)
        else:
            statuses = {str(feature.status) for feature in matches}
            status = (
                "found"
                if "observed" in statuses
                else "possible"
                if "uncertain" in statuses
                else "not_found"
            )
            summary = "; ".join(feature.title for feature in matches) or (
                "No associated source material surfaced."
            )
            evidence = [
                detail
                for feature in matches
                for detail in _evidence_details(job, feature, bundles)
            ]
        values.append(
            {
                "part": part,
                "ordinal": ordinal,
                "label": label,
                "status": status,
                "summary": summary,
                "source_feature_ids": [feature.feature_id for feature in matches],
                "evidence_count": len(evidence),
                "evidence": evidence,
            }
        )
    return values


@router.get("/{job_id}/export.xlsx")
async def export_candidates(job_id: str):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    workspace = _workspace_for(job)
    blueprint, coverage, _, _ = _curriculum_context(workspace)
    reviews = {
        review.candidate_id: str(review.status)
        for review in job_repository.list_latest_reviews(job_id)
        if review.review_kind == ObjectiveReviewKind.OBJECTIVE
    }
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Proposed objectives"
    headers = [
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
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="007680")
    bundles = {}
    for candidate in workspace.candidates:
        classification = candidate.classification
        locations = list(
            dict.fromkeys(
                _source_location(detail)
                for detail in _evidence_details(job, candidate, bundles)
            )
        )
        sheet.append(
            [
                candidate.statement,
                str(candidate.support_profile.discovery_basis).replace("_", " ").title()
                if candidate.support_profile
                else "Legacy source-derived",
                str(candidate.support_profile.source_support_level).replace("_", " ").title()
                if candidate.support_profile
                else "Not assessed",
                "\n".join(candidate.support_profile.source_contributions)
                if candidate.support_profile
                else "",
                "\n".join(candidate.support_profile.missing_knowledge)
                if candidate.support_profile
                else "",
                "\n".join(candidate.support_profile.anticipated_llm_contributions)
                if candidate.support_profile
                else "",
                str(candidate.bloom_level).title()
                if candidate.bloom_level
                else "Unclassified",
                str(candidate.content_type_hint).title()
                if candidate.content_type_hint
                else "Unclassified",
                str(classification.combined_confidence).title()
                if classification
                else "Not available",
                ", ".join(classification.plausible_alternative_cells)
                if classification
                else "",
                candidate.practitioner_relevance,
                "\n".join(locations),
                reviews.get(candidate.candidate_id, "pending").replace("_", " ").title(),
                "",
            ]
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = [55, 20, 18, 45, 45, 45, 20, 22, 24, 32, 55, 38, 18, 45]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    if blueprint and coverage:
        coverage_sheet = workbook.create_sheet("Curriculum coverage")
        coverage_sheet.append(["Central purpose", blueprint.central_purpose])
        coverage_sheet.append(["Intended use", blueprint.intended_use])
        coverage_sheet.append([])
        coverage_sheet.append(
            [
                "Order",
                "Curriculum domain",
                "Importance",
                "Coverage state",
                "Coverage rationale",
                "Missing performance",
                "Initial gap discovery warranted",
                "Initial gap eligibility rationale",
                "Initial target discovery outcomes",
                "Accepted gap candidates",
                "Acknowledged by LDS",
            ]
        )
        coverage_by_domain = {
            item.domain_id: item for item in coverage.domain_coverage
        }
        discovery_by_domain = {
            record.domain_id: record for record in coverage.gap_discovery_records
        }
        for domain in blueprint.domains:
            finding = coverage_by_domain[domain.domain_id]
            discovery = discovery_by_domain.get(domain.domain_id)
            gap_warranted = (
                discovery.warranted
                if discovery
                else finding.gap_discovery_warranted
            )
            gap_rationale = (
                discovery.eligibility_rationale
                if discovery
                else finding.gap_discovery_rationale or ""
            )
            gap_result = "Not selected"
            if discovery and discovery.selected_for_discovery:
                gap_result = "\n".join(
                    (
                        f"{item.target.performance}: "
                        f"{len(item.direct_candidate_ids)} direct, "
                        f"{len(item.supporting_candidate_ids)} supporting"
                        if item.direct_candidate_ids or item.supporting_candidate_ids
                        else f"{item.target.performance}: no defensible candidate"
                    )
                    for item in discovery.target_records
                )
            coverage_sheet.append(
                [
                    domain.ordinal,
                    domain.title,
                    str(domain.importance).title(),
                    str(finding.state).replace("_", " ").title(),
                    finding.rationale,
                    "\n".join(finding.missing_performances),
                    "Yes" if gap_warranted else "No",
                    gap_rationale,
                    gap_result,
                    "\n".join(discovery.accepted_candidate_ids)
                    if discovery
                    else "",
                    "Yes"
                    if domain.domain_id in coverage.acknowledged_domain_ids
                    else "No",
                ]
            )
        for cell in coverage_sheet[4]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="007680")
        for column, width in enumerate(
            [10, 34, 18, 20, 60, 50, 24, 60, 65, 38, 20], start=1
        ):
            coverage_sheet.column_dimensions[
                coverage_sheet.cell(row=4, column=column).column_letter
            ].width = width
        for row in coverage_sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    output = BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="learning-objectives-{job_id}.xlsx"'
        },
    )


@router.get("/{job_id}/candidates")
async def list_candidates(
    job_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    decision: str | None = None,
    confidence: str | None = None,
    origin: str | None = None,
    rule_id: str | None = None,
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    workspace = _workspace_for(job)
    blueprint, coverage, domains, assignments = _curriculum_context(workspace)
    gap_records = _gap_records_by_candidate(coverage)
    reviews = job_repository.list_latest_reviews(job_id)
    bundles = {}
    by_candidate = {}
    for review in reviews:
        by_candidate.setdefault(review.candidate_id, {})[str(review.review_kind)] = review
    selected = []
    for candidate in workspace.candidates:
        classification_confidence = (
            candidate.classification.combined_confidence
            if candidate.classification
            else candidate.confidence
        )
        if confidence and str(classification_confidence) != confidence:
            continue
        if origin and str(candidate.origin) != origin:
            continue
        if rule_id and rule_id not in candidate.rule_ids:
            continue
        candidate_reviews = by_candidate.get(candidate.candidate_id, {})
        active_kind = ObjectiveReviewKind.OBJECTIVE
        active_review = candidate_reviews.get(str(active_kind))
        active_decision = str(active_review.status) if active_review else "pending"
        if decision and active_decision != decision:
            continue
        selected.append((candidate, candidate_reviews, active_decision))
    values = []
    for candidate, candidate_reviews, active_decision in selected[offset : offset + limit]:
        curriculum_assignment = assignments.get(candidate.candidate_id)
        gap_context = gap_records.get(candidate.candidate_id)
        gap_record = gap_context["domain_record"] if gap_context else None
        gap_target_record = gap_context["target_record"] if gap_context else None
        gap_alignment = gap_context["alignment"] if gap_context else None
        associated_features = [
            feature
            for feature in workspace.source_features
            if feature.feature_id in candidate.source_feature_ids
        ]
        present = [
            feature.title
            for feature in associated_features
            if str(feature.status) == "observed"
        ]
        feature_types = {str(feature.feature_type) for feature in associated_features}
        gaps = []
        if "practice_activity" not in feature_types:
            gaps.append("No source-native practice activity was associated.")
        if "assessment" not in feature_types:
            gaps.append("No source-native assessment was associated.")
        values.append(
            {
                **candidate.model_dump(mode="json"),
                "decision": active_decision,
                "reviews": {
                    key: value.model_dump(mode="json")
                    for key, value in candidate_reviews.items()
                },
                "critic_findings": [
                    finding.model_dump(mode="json")
                    for finding in workspace.critic_findings.get(candidate.candidate_id, [])
                ],
                "evidence_details": _evidence_details(job, candidate, bundles),
                "already_present": present,
                "likely_downstream_gaps": gaps,
                "part_availability": _part_availability(
                    job, candidate, associated_features, bundles
                ),
                "curriculum_assignment": {
                    **curriculum_assignment.model_dump(mode="json"),
                    "domains": [
                        domains[domain_id].model_dump(mode="json")
                        for domain_id in curriculum_assignment.domain_ids
                        if domain_id in domains
                    ],
                }
                if curriculum_assignment
                else None,
                "gap_discovery": {
                    "domain_id": gap_record.domain_id,
                    "eligibility_rationale": gap_record.eligibility_rationale,
                    "domain": domains[gap_record.domain_id].model_dump(mode="json"),
                    "target": gap_target_record.target.model_dump(mode="json"),
                    "alignment": gap_alignment.model_dump(mode="json")
                    if gap_alignment
                    else None,
                }
                if gap_record
                and gap_target_record
                and gap_record.domain_id in domains
                else None,
            }
        )
    return {
        "items": values,
        "total": len(selected),
        "offset": offset,
        "limit": limit,
        "workspace_revision": workspace.revision,
        "source_features": [
            {
                **feature.model_dump(mode="json"),
                "evidence_details": _evidence_details(job, feature, bundles),
            }
            for feature in workspace.source_features
        ],
        "rejected": [item.model_dump(mode="json") for item in workspace.rejected],
        "duplicate_groups": [
            item.model_dump(mode="json") for item in workspace.duplicate_groups
        ],
        "curriculum_blueprint": blueprint.model_dump(mode="json") if blueprint else None,
        "curriculum_coverage": coverage.model_dump(mode="json") if coverage else None,
        "curriculum_coverage_current": bool(
            coverage and coverage.workspace_revision == workspace.revision
        ),
    }


@router.get("/{job_id}/coverage")
async def get_curriculum_coverage(job_id: str):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    workspace = _workspace_for(job)
    blueprint, coverage, _domains, _assignments = _curriculum_context(workspace)
    return {
        "blueprint": blueprint.model_dump(mode="json") if blueprint else None,
        "coverage": coverage.model_dump(mode="json") if coverage else None,
        "current": bool(coverage and coverage.workspace_revision == workspace.revision),
    }


@router.patch("/{job_id}/coverage/domains/{domain_id}")
async def review_curriculum_domain(
    job_id: str,
    domain_id: str,
    payload: CurriculumDomainReviewRequest,
    request: Request,
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    if job.workflow_stage != ObjectiveJobStage.OBJECTIVE_REVIEW:
        raise HTTPException(
            status_code=409,
            detail="Curriculum findings can only be reviewed during objective review.",
        )
    if job.version != payload.expected_job_version:
        raise HTTPException(
            status_code=409, detail="Objective job was updated; reload before editing."
        )
    workspace = _workspace_for(job)
    blueprint = workspace.curriculum_blueprint
    coverage = workspace.curriculum_coverage
    if blueprint is None or coverage is None:
        raise HTTPException(status_code=404, detail="Curriculum coverage is unavailable.")
    if domain_id not in {domain.domain_id for domain in blueprint.domains}:
        raise HTTPException(status_code=404, detail="Curriculum domain not found.")

    domains = [
        domain.model_copy(update={"importance": payload.importance})
        if domain.domain_id == domain_id and payload.importance is not None
        else domain
        for domain in blueprint.domains
    ]
    acknowledged = set(coverage.acknowledged_domain_ids)
    if payload.acknowledged is True:
        acknowledged.add(domain_id)
    elif payload.acknowledged is False:
        acknowledged.discard(domain_id)
    new_revision = workspace.revision + 1
    revised_coverage = coverage.model_copy(
        update={
            "acknowledged_domain_ids": sorted(acknowledged),
            "workspace_revision": (
                new_revision
                if payload.importance is None
                else coverage.workspace_revision
            ),
        }
    )
    revised = workspace.__class__.model_validate(
        {
            **workspace.model_dump(mode="json"),
            "revision": new_revision,
            "curriculum_blueprint": blueprint.model_copy(
                update={"domains": domains}
            ).model_dump(mode="json"),
            "curriculum_coverage": revised_coverage.model_dump(mode="json"),
        }
    )
    workspace_repository.save_workspace_revision(
        revised,
        model_metadata={
            "edited_by": _actor(request),
            "edit": "curriculum_domain_review",
        },
    )
    try:
        updated = job_repository.update_job_workspace_revision(
            job_id,
            workspace_revision=new_revision,
            expected_version=payload.expected_job_version,
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_summary(updated)


@router.get("/{job_id}/source-features")
async def list_source_features(
    job_id: str,
    status: str | None = None,
    feature_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    workspace = _workspace_for(job)
    bundles = {}
    values = [
        {
            **feature.model_dump(mode="json"),
            "evidence_details": _evidence_details(job, feature, bundles),
        }
        for feature in workspace.source_features
        if (not status or str(feature.status) == status)
        and (not feature_type or str(feature.feature_type) == feature_type)
    ]
    return {
        "items": values[offset : offset + limit],
        "total": len(values),
        "offset": offset,
        "limit": limit,
    }


@router.get("/{job_id}/candidates/{candidate_id}/evidence")
async def get_candidate_evidence(job_id: str, candidate_id: str):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    workspace = _workspace_for(job)
    candidate = next(
        (value for value in workspace.candidates if value.candidate_id == candidate_id),
        None,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Objective candidate not found.")
    return _evidence_details(job, candidate)


def _save_candidates(job, workspace, candidates, request: Request, event: str):
    revised = workspace.model_copy(
        update={"revision": workspace.revision + 1, "candidates": candidates, "decisions": []}
    )
    workspace_repository.save_workspace_revision(
        revised,
        model_metadata={"edited_by": _actor(request), "edit": event},
    )
    return revised


def _assert_candidate_not_generating(job_id: str, candidate_id: str) -> None:
    if draft_repository.get_generation_job_for_candidate(job_id, candidate_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "This objective is already approved and its RLO generation has started. "
                "Request changes during the RLO review instead."
            ),
        )


@router.patch("/{job_id}/candidates/{candidate_id}")
async def edit_candidate(
    job_id: str,
    candidate_id: str,
    payload: CandidateEditRequest,
    request: Request,
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    if job.version != payload.expected_job_version:
        raise HTTPException(
            status_code=409,
            detail="Objective job was updated; reload before editing.",
        )
    workspace = _workspace_for(job)
    _assert_candidate_not_generating(job_id, candidate_id)
    updates = payload.model_dump(exclude={"expected_job_version"}, exclude_none=True)
    objective_fields = {
        "statement",
        "observable_behavior",
        "performance_context",
        "practitioner_relevance",
    }
    detail_fields = {
        "bloom_level",
        "scope",
        "prerequisites",
        "expected_effort_minutes",
        "source_feature_ids",
    }
    allowed = (
        objective_fields | detail_fields
        if job.workflow_stage == ObjectiveJobStage.OBJECTIVE_REVIEW
        else set()
    )
    if not set(updates) <= allowed:
        raise HTTPException(
            status_code=409,
            detail="Those fields cannot be edited in this review stage.",
        )
    found = False
    candidates = []
    for candidate in workspace.candidates:
        if candidate.candidate_id == candidate_id:
            candidate_values = {**candidate.model_dump(mode="json"), **updates}
            if set(updates) & objective_fields:
                candidate_values.update(
                    {
                        "classification": None,
                        "bloom_level": None,
                        "content_type_hint": None,
                        "poc2_scope_status": ObjectiveScopeStatus.NEEDS_REVIEW,
                        "poc2_scope_reason": (
                            "Objective performance changed; classification must be "
                            "rerun before POC2 approval."
                        ),
                    }
                )
            if candidate.support_profile and set(updates) & objective_fields:
                candidate_values["support_profile"] = {
                    **candidate.support_profile.model_dump(mode="json"),
                    "review_note": (
                        "The objective performance was edited by an LDS reviewer. "
                        "Confirm that the recorded source support and anticipated model "
                        "contribution still match before approval."
                    ),
                }
            candidates.append(
                ObjectiveCandidate.model_validate(candidate_values)
            )
            found = True
        else:
            candidates.append(candidate)
    if not found:
        raise HTTPException(status_code=404, detail="Objective candidate not found.")
    revised = _save_candidates(job, workspace, candidates, request, "candidate_edit")
    try:
        updated = job_repository.update_job_workspace_revision(
            job_id,
            workspace_revision=revised.revision,
            expected_version=payload.expected_job_version,
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job_repository.record_review(
        job_id,
        candidate_id=candidate_id,
        review_kind=ObjectiveReviewKind.OBJECTIVE,
        status=ObjectiveDecisionStatus.PENDING,
        note="Candidate changed; prior decision cleared.",
        decided_by=_actor(request),
    )
    return _job_summary(job_repository.get_objective_job(updated.job_id))


@router.post("/{job_id}/candidates/{candidate_id}/reclassify")
async def reclassify_candidate(
    job_id: str,
    candidate_id: str,
    payload: ReclassifyCandidateRequest,
    request: Request,
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    if job.workflow_stage != ObjectiveJobStage.OBJECTIVE_REVIEW:
        raise HTTPException(
            status_code=409,
            detail="Candidates can only be reclassified in objective review.",
        )
    if job.version != payload.expected_job_version:
        raise HTTPException(status_code=409, detail="Objective job was updated; reload.")
    workspace = _workspace_for(job)
    candidate = next(
        (item for item in workspace.candidates if item.candidate_id == candidate_id),
        None,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Objective candidate not found.")
    _assert_candidate_not_generating(job_id, candidate_id)
    service = ObjectiveDiscoveryService()
    result = service.classify_revised_candidate(
        candidate,
        brief=workspace.learning_brief,
        sibling_statements=[
            item.statement
            for item in workspace.candidates
            if item.candidate_id != candidate_id
        ],
        workspace_id=workspace.workspace_id,
    )
    revised_candidate = candidate.model_copy(
        update={
            "classification": result.classification,
            "bloom_level": (
                result.classification.bloom.value if result.classification else None
            ),
            "content_type_hint": (
                result.classification.content_kind.value
                if result.classification
                else None
            ),
            "poc2_scope_status": result.scope_status,
            "poc2_scope_reason": result.scope_reason,
        }
    )
    revised = _save_candidates(
        job,
        workspace,
        [
            revised_candidate if item.candidate_id == candidate_id else item
            for item in workspace.candidates
        ],
        request,
        "candidate_reclassification",
    )
    try:
        updated = job_repository.update_job_workspace_revision(
            job_id,
            workspace_revision=revised.revision,
            expected_version=payload.expected_job_version,
        )
        job_repository.append_prompt_runs(job_id, service.prompt_runs)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job_repository.record_review(
        job_id,
        candidate_id=candidate_id,
        review_kind=ObjectiveReviewKind.OBJECTIVE,
        status=ObjectiveDecisionStatus.PENDING,
        note="Objective reclassified; reviewer decision required.",
        decided_by=_actor(request),
    )
    return _job_summary(job_repository.get_objective_job(updated.job_id))


def _lds_clone(candidate: ObjectiveCandidate, statement: str) -> ObjectiveCandidate:
    support_profile = (
        candidate.support_profile.model_copy(
            update={
                "review_note": (
                    "This objective was added or reshaped by an LDS reviewer. Confirm "
                    "its recorded source support and anticipated model contribution "
                    "before approval."
                )
            }
        )
        if candidate.support_profile
        else None
    )
    return candidate.model_copy(
        update={
            "candidate_id": str(uuid.uuid4()),
            "statement": statement.strip(),
            "origin": ObjectiveOrigin.LDS,
            "selected_reason": "Added or reshaped by an LDS reviewer.",
            "duplicate_group": None,
            "classification": None,
            "bloom_level": None,
            "content_type_hint": None,
            "poc2_scope_status": ObjectiveScopeStatus.NEEDS_REVIEW,
            "poc2_scope_reason": (
                "Objective performance changed; classification must be rerun before "
                "POC2 approval."
            ),
            "support_profile": support_profile,
        }
    )


@router.post("/{job_id}/candidates", status_code=201)
async def add_candidate(
    job_id: str, payload: AddCandidateRequest, request: Request
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    if job.workflow_stage != ObjectiveJobStage.OBJECTIVE_REVIEW:
        raise HTTPException(
            status_code=409, detail="Candidates can only be added in objective review."
        )
    if job.version != payload.expected_job_version:
        raise HTTPException(status_code=409, detail="Objective job was updated; reload before editing.")
    workspace = _workspace_for(job)
    basis = next(
        (
            candidate
            for candidate in workspace.candidates
            if candidate.candidate_id == payload.based_on_candidate_id
        ),
        None,
    )
    if basis is None:
        raise HTTPException(status_code=404, detail="Basis candidate not found.")
    revised = _save_candidates(
        job,
        workspace,
        [*workspace.candidates, _lds_clone(basis, payload.statement)],
        request,
        "candidate_add",
    )
    try:
        updated = job_repository.update_job_workspace_revision(
            job_id,
            workspace_revision=revised.revision,
            expected_version=payload.expected_job_version,
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_summary(updated)


@router.post("/{job_id}/candidates/{candidate_id}/split")
async def split_candidate(
    job_id: str,
    candidate_id: str,
    payload: SplitCandidateRequest,
    request: Request,
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    if job.workflow_stage != ObjectiveJobStage.OBJECTIVE_REVIEW:
        raise HTTPException(
            status_code=409, detail="Candidates can only be split in objective review."
        )
    if job.version != payload.expected_job_version:
        raise HTTPException(status_code=409, detail="Objective job was updated; reload before editing.")
    workspace = _workspace_for(job)
    _assert_candidate_not_generating(job_id, candidate_id)
    source = next(
        (candidate for candidate in workspace.candidates if candidate.candidate_id == candidate_id),
        None,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Objective candidate not found.")
    replacements = [_lds_clone(source, statement) for statement in payload.statements]
    candidates = [
        candidate
        for candidate in workspace.candidates
        if candidate.candidate_id != candidate_id
    ] + replacements
    revised = _save_candidates(job, workspace, candidates, request, "candidate_split")
    try:
        updated = job_repository.update_job_workspace_revision(
            job_id,
            workspace_revision=revised.revision,
            expected_version=payload.expected_job_version,
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_summary(updated)


@router.post("/{job_id}/candidates/merge")
async def merge_candidates(
    job_id: str, payload: MergeCandidatesRequest, request: Request
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    if job.workflow_stage != ObjectiveJobStage.OBJECTIVE_REVIEW:
        raise HTTPException(
            status_code=409, detail="Candidates can only be merged in objective review."
        )
    if job.version != payload.expected_job_version:
        raise HTTPException(status_code=409, detail="Objective job was updated; reload before editing.")
    workspace = _workspace_for(job)
    selected_ids = set(payload.candidate_ids)
    for candidate_id in selected_ids:
        _assert_candidate_not_generating(job_id, candidate_id)
    selected = [
        candidate
        for candidate in workspace.candidates
        if candidate.candidate_id in selected_ids
    ]
    if len(selected) != len(selected_ids):
        raise HTTPException(
            status_code=404, detail="One or more objective candidates were not found."
        )
    evidence = list(
        {
            item.evidence_id: item
            for candidate in selected
            for item in candidate.evidence
        }.values()
    )
    feature_ids = list(
        dict.fromkeys(
            feature_id
            for candidate in selected
            for feature_id in candidate.source_feature_ids
        )
    )
    merged = _lds_clone(selected[0], payload.statement).model_copy(
        update={"evidence": evidence, "source_feature_ids": feature_ids}
    )
    revised = _save_candidates(
        job,
        workspace,
        [
            candidate
            for candidate in workspace.candidates
            if candidate.candidate_id not in selected_ids
        ]
        + [merged],
        request,
        "candidate_merge",
    )
    try:
        updated = job_repository.update_job_workspace_revision(
            job_id,
            workspace_revision=revised.revision,
            expected_version=payload.expected_job_version,
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_summary(updated)


@router.post("/{job_id}/candidates/{candidate_id}/reviews", status_code=201)
async def review_candidate(
    job_id: str,
    candidate_id: str,
    payload: ReviewRequest,
    request: Request,
):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    workspace = _workspace_for(job)
    if candidate_id not in {candidate.candidate_id for candidate in workspace.candidates}:
        raise HTTPException(status_code=404, detail="Objective candidate not found.")
    candidate = next(
        item for item in workspace.candidates if item.candidate_id == candidate_id
    )
    try:
        generation_job = draft_repository.get_generation_job_for_candidate(
            job_id, candidate_id
        )
        if (
            generation_job
            and payload.review_kind == ObjectiveReviewKind.OBJECTIVE
            and payload.status != ObjectiveDecisionStatus.APPROVED
        ):
            raise InvalidStateTransition(
                "Approved objectives cannot be reopened after RLO generation starts; "
                "request changes during RLO review instead"
            )
        if (
            payload.review_kind == ObjectiveReviewKind.OBJECTIVE
            and payload.status == ObjectiveDecisionStatus.APPROVED
        ):
            scope_error = candidate_scope_error(candidate)
            if scope_error:
                raise InvalidStateTransition(
                    f"Objective is outside POC2 authoring scope: {scope_error}"
                )
        decision = job_repository.record_review(
            job_id,
            candidate_id=candidate_id,
            review_kind=payload.review_kind,
            status=payload.status,
            note=payload.note,
            decided_by=_actor(request),
        )
        if (
            payload.review_kind == ObjectiveReviewKind.OBJECTIVE
            and payload.status == ObjectiveDecisionStatus.APPROVED
        ):
            draft_repository.create_generation_batch(
                _completed_package(job, workspace),
                created_by=_actor(request),
            )
        return decision
    except (InvalidStateTransition, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _assert_review_complete(job, workspace) -> None:
    if job.workflow_stage != ObjectiveJobStage.OBJECTIVE_REVIEW:
        return
    kind = ObjectiveReviewKind.OBJECTIVE
    latest = {
        review.candidate_id: review
        for review in job_repository.list_latest_reviews(job.job_id, kind)
    }
    expected = {candidate.candidate_id for candidate in workspace.candidates}
    unresolved = {
        candidate_id
        for candidate_id in expected
        if candidate_id not in latest
        or latest[candidate_id].status
        in {
            ObjectiveDecisionStatus.PENDING,
            ObjectiveDecisionStatus.REVISION_REQUESTED,
        }
    }
    if unresolved:
        raise InvalidStateTransition(
            f"{len(unresolved)} objective(s) still require a review decision"
        )


@router.post("/{job_id}/advance")
async def advance_job(job_id: str, payload: AdvanceRequest, request: Request):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    workspace = _workspace_for(job)
    try:
        _assert_review_complete(job, workspace)
        if job.workflow_stage == ObjectiveJobStage.COMPLETE:
            batch = draft_repository.create_generation_batch(
                _completed_package(job, workspace),
                created_by=_actor(request),
                finalized=True,
            )
            draft_repository.refresh_generation_batch(batch.batch_id)
            return _job_summary(job)
        updated = job_repository.advance_objective_job(
            job_id,
            expected_version=payload.expected_job_version,
            actor=_actor(request),
            note=payload.note,
        )
        if updated.workflow_stage == ObjectiveJobStage.COMPLETE:
            batch = draft_repository.create_generation_batch(
                _completed_package(updated, workspace),
                created_by=_actor(request),
                finalized=True,
            )
            draft_repository.refresh_generation_batch(batch.batch_id)
    except (InvalidStateTransition, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_summary(updated)


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, request: Request):
    try:
        return _job_summary(
            job_repository.retry_objective_job(job_id, actor=_actor(request))
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Objective job not found.") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{job_id}/prompts")
async def list_prompts(job_id: str):
    if job_repository.get_objective_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    return job_repository.list_prompt_run_summaries(job_id)


@router.get("/{job_id}/prompts/{prompt_run_id}")
async def get_prompt(job_id: str, prompt_run_id: str):
    prompt = job_repository.get_prompt_run(job_id, prompt_run_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt run not found.")
    return prompt


@router.get("/{job_id}/package", response_model=CompletedObjectivePackage)
async def get_completed_package(job_id: str):
    job = job_repository.get_objective_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Objective job not found.")
    if job.workflow_stage != ObjectiveJobStage.COMPLETE:
        raise HTTPException(status_code=409, detail="Objective job is not complete.")
    workspace = _workspace_for(job)
    return _completed_package(job, workspace)


def _completed_package(job, workspace) -> CompletedObjectivePackage:
    reviews = {
        review.candidate_id: review
        for review in job_repository.list_latest_reviews(
            job.job_id,
            ObjectiveReviewKind.OBJECTIVE,
        )
    }
    approved = [
        candidate
        for candidate in workspace.candidates
        if candidate.candidate_id in reviews
        and reviews[candidate.candidate_id].status == ObjectiveDecisionStatus.APPROVED
    ]
    return CompletedObjectivePackage(
        job_id=job.job_id,
        workspace_id=workspace.workspace_id,
        workspace_revision=workspace.revision,
        collection_id=workspace.collection_id,
        source_map_revision=workspace.learning_brief.source_map_revision,
        objectives=approved,
        source_features=workspace.source_features,
    )
