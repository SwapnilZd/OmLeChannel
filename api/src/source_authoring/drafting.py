"""Bounded generation, validation, and review for evidence-grounded RLOs."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    load_lite_llm_settings,
)
from openai import OpenAI
from pydantic import ValidationError
from rlo_schema import Evidence, EvidenceRole, RLO, Source

from src.source_ingestion.contracts import ExtractedDocument, SourceSegment
from src.source_ingestion.segmentation import SourceTokenBudget, segment_document

from . import draft_repository, repository
from .cell_scope import authoring_scope_error
from .contracts import ObjectiveWorkspace
from .authoring_contracts import ClaimKnowledgeOrigin, ClaimVerificationStatus
from .draft_contracts import (
    DraftReviewResult,
    DraftValidationFinding,
    RLODraftJob,
    RLODraftRequest,
    RLODraftSnapshot,
    RLODraftState,
    RLOReviewRecord,
    RLOReviewRequest,
    ReviewAction,
)
from .prompt_assets import load_prompt_asset


DRAFT_PROMPT_VERSION = "v1"
DRAFT_MODEL = ModelAlias.SOURCE_RLO_DRAFTING
GROUNDING_MODEL = ModelAlias.SOURCE_RLO_GROUNDING_REVIEW
PEDAGOGY_MODEL = ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW


def _legacy_asset(filename: str, prompt_id: str):
    return load_prompt_asset(
        filename,
        prompt_id=prompt_id,
        version=DRAFT_PROMPT_VERSION,
        group="rlo_generation",
    )


LEGACY_DRAFT_PROMPT = _legacy_asset(
    "legacy_catalog_drafting.md", "source-rlo-legacy-catalog-drafting"
)
LEGACY_GROUNDING_PROMPT = _legacy_asset(
    "legacy_catalog_grounding.md", "source-rlo-legacy-catalog-grounding"
)
LEGACY_PEDAGOGY_PROMPT = _legacy_asset(
    "legacy_catalog_pedagogy.md", "source-rlo-legacy-catalog-pedagogy"
)
LEGACY_REPAIR_PROMPT = _legacy_asset(
    "legacy_catalog_repair.md", "source-rlo-legacy-catalog-repair"
)


class DraftSourceMaterial:
    def __init__(
        self,
        *,
        source_id: str,
        source_version_id: str,
        title: str,
        filename: str,
        checksum: str,
        document: ExtractedDocument,
        segments: list[SourceSegment] | None = None,
    ) -> None:
        self.source_id = source_id
        self.source_version_id = source_version_id
        self.title = title
        self.filename = filename
        self.checksum = checksum
        self.document = document
        self.segments = segments if segments is not None else segment_document(document)


class RepositoryDraftStore:
    def create(self, request: RLODraftRequest, *, created_by: str | None) -> RLODraftJob:
        return draft_repository.create_draft_job(request, created_by=created_by)

    def load(self, job_id: str) -> RLODraftJob | None:
        return draft_repository.get_draft_job(job_id)

    def transition(
        self,
        job: RLODraftJob,
        *,
        expected_state: RLODraftState,
        save_revision: bool = False,
    ) -> RLODraftJob:
        return draft_repository.save_draft_job(
            job, expected_state=expected_state, save_revision=save_revision
        )

    def record_review(self, job_id: str, review: RLOReviewRecord) -> None:
        draft_repository.record_draft_review(job_id, review)


def _locator(document: ExtractedDocument, node_ids: list[str]) -> str:
    by_id = {node.node_id: node for node in document.nodes}
    pages = sorted(
        {locator.page for node_id in node_ids for locator in by_id[node_id].locators if locator.page}
    )
    slides = sorted(
        {locator.slide for node_id in node_ids for locator in by_id[node_id].locators if locator.slide}
    )
    chapters = sorted(
        {
            locator.chapter
            for node_id in node_ids
            for locator in by_id[node_id].locators
            if locator.chapter
        }
    )
    values = pages or slides or chapters
    label = "page" if pages else "slide" if slides else "chapter"
    return f"{label}{'s' if len(values) != 1 else ''} {', '.join(map(str, values))}"


def _excerpt(document: ExtractedDocument, node_ids: list[str]) -> str | None:
    by_id = {node.node_id: node for node in document.nodes}
    text = "\n".join(by_id[node_id].text or "" for node_id in node_ids).strip()
    return text or None


def _evidence_segments(
    material: DraftSourceMaterial, node_ids: list[str]
) -> list[SourceSegment]:
    wanted = set(node_ids)
    return [
        segment
        for segment in sorted(material.segments, key=lambda item: item.ordinal)
        if wanted.intersection(segment.node_ids)
    ]


def _segment_excerpt(segments: list[SourceSegment]) -> str | None:
    text = "\n\n".join(segment.text.strip() for segment in segments).strip()
    return text or None


def _draft_findings(rlo: RLO) -> list[DraftValidationFinding]:
    findings: list[DraftValidationFinding] = []

    def required_metadata(code: str, path: str, present: bool, message: str) -> None:
        if not present:
            findings.append(
                DraftValidationFinding(
                    code=code,
                    severity="error",
                    category="schema",
                    path=path,
                    message=message,
                )
            )

    def require(path: str, refs: list[str]) -> None:
        if not refs:
            findings.append(
                DraftValidationFinding(
                    code="evidence_required",
                    severity="error",
                    category="schema",
                    path=path,
                    message="Generated instructional claims require at least one evidence reference.",
                )
            )

    require("enabling_objective", rlo.enabling_objective.evidence_refs)
    for concept in rlo.concepts:
        require(f"concepts.{concept.id}", concept.evidence_refs)
        for misconception in concept.misconceptions:
            require(
                f"concepts.{concept.id}.misconceptions.{misconception.id}",
                misconception.evidence_refs,
            )
    for component in rlo.components:
        require(f"components.{component.id}", component.evidence_refs)
    for item in rlo.assessment_items:
        require(f"assessment_items.{item.id}", item.evidence_refs)
        for option in item.options or []:
            if option.correct:
                require(f"assessment_items.{item.id}.options.{option.id}", option.evidence_refs)
    required_metadata(
        "rights_required",
        "rights",
        rlo.rights is not None,
        "Usage rights and sharing constraints are required before review.",
    )
    required_metadata(
        "accessibility_required",
        "accessibility.features",
        bool(rlo.accessibility.features),
        "At least one applicable accessibility feature is required before review.",
    )
    required_metadata(
        "targeting_required",
        "audience",
        bool(rlo.audience or rlo.role_tags),
        "At least one audience descriptor or role tag is required before review.",
    )
    return findings


class RLODraftingService:
    def __init__(
        self,
        *,
        client=None,
        store=None,
        source_loader=None,
        token_budget=None,
    ) -> None:
        settings = load_lite_llm_settings(required=False)
        self.client = client or OpenAI(base_url=settings.base_url, api_key=settings.api_key)
        self.store = store or RepositoryDraftStore()
        self.source_loader = source_loader or draft_repository.load_source_materials
        self.token_budget = token_budget or SourceTokenBudget()
        self.usage: dict[str, list[dict[str, int]]] = {}

    def _parse(self, *, model, operation, prompt, content, text_format, job_id):
        serialized = json.dumps(content, separators=(",", ":"), sort_keys=True)
        self.token_budget.require_within_limit(serialized)
        response = self.client.responses.parse(
            model=model,
            metadata=build_litellm_metadata(model, operation=operation, job_id=job_id),
            extra_headers=build_langfuse_headers(model, operation=operation, job_id=job_id),
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": serialized},
            ],
            text_format=text_format,
        )
        if response.output_parsed is None:
            raise ValueError(f"model returned no {operation} result")
        usage = getattr(response, "usage", None)
        values = {
            key: value
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance((value := getattr(usage, key, None)), int)
        }
        self.usage.setdefault(str(model), []).append(values)
        return response.output_parsed

    def _workspace_candidate(self, request: RLODraftRequest):
        workspace = repository.get_objective_workspace(
            request.workspace_id, request.workspace_revision
        )
        if workspace is None:
            raise ValueError("objective workspace revision does not exist")
        candidate = next(
            (item for item in workspace.candidates if item.candidate_id == request.candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("objective candidate does not exist")
        return workspace, candidate

    def _snapshot(
        self,
        workspace: ObjectiveWorkspace,
        candidate,
        materials: list[DraftSourceMaterial],
    ) -> RLODraftSnapshot:
        by_version = {material.source_version_id: material for material in materials}
        candidate_versions = list(
            dict.fromkeys(item.source_version_id for item in candidate.evidence)
        )
        if not set(candidate_versions) <= set(by_version):
            raise ValueError("loaded source materials do not contain candidate evidence")
        required_versions = list(by_version)
        source_ref_by_version = {
            version_id: f"src-{index:02d}"
            for index, version_id in enumerate(required_versions, start=1)
        }
        sources = []
        for version_id in required_versions:
            material = by_version[version_id]
            sources.append(
                Source(
                    id=source_ref_by_version[version_id],
                    title=material.title,
                    reference=material.filename,
                    authority="primary",
                    ingested_source_id=material.source_id,
                    source_version_id=version_id,
                    checksum=material.checksum,
                    canonical_locator=material.filename,
                )
            )
        evidence = []
        evidence_nodes = []
        for item in candidate.evidence:
            material = by_version[item.source_version_id]
            nodes = {node.node_id: node for node in material.document.nodes}
            missing = set(item.node_ids) - nodes.keys()
            if missing:
                raise ValueError(
                    f"candidate evidence references missing source node '{sorted(missing)[0]}'"
                )
            selected_segments = _evidence_segments(material, item.node_ids)
            if not selected_segments:
                raise ValueError("candidate evidence has no resolvable source segments")
            excerpt = _segment_excerpt(selected_segments)
            evidence.append(
                Evidence(
                    id=item.evidence_id,
                    source_ref=source_ref_by_version[item.source_version_id],
                    source_version_id=item.source_version_id,
                    node_ids=item.node_ids,
                    segment_ids=[segment.segment_id for segment in selected_segments],
                    locator=_locator(material.document, item.node_ids),
                    role=EvidenceRole(item.role),
                    excerpt=excerpt,
                    excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest()
                    if excerpt
                    else None,
                    usage_note=item.rationale,
                )
            )
            evidence_nodes.extend(
                {
                    "evidence_id": item.evidence_id,
                    "source_version_id": item.source_version_id,
                    "node_id": node_id,
                    "text": nodes[node_id].text,
                    "locators": [
                        locator.model_dump(mode="json") for locator in nodes[node_id].locators
                    ],
                }
                for node_id in item.node_ids
            )
        return RLODraftSnapshot(
            candidate=candidate,
            learning_brief=workspace.learning_brief,
            sources=sources,
            evidence=evidence,
            evidence_nodes=evidence_nodes,
            source_features=workspace.source_features,
            prompt_version=DRAFT_PROMPT_VERSION,
            model_aliases=[str(DRAFT_MODEL), str(GROUNDING_MODEL), str(PEDAGOGY_MODEL)],
        )

    @staticmethod
    def _fixed_fields(rlo: RLO, job: RLODraftJob) -> list[DraftValidationFinding]:
        findings = _draft_findings(rlo)
        expected_sources = [item.model_dump(mode="json") for item in job.snapshot.sources]
        expected_evidence = [item.model_dump(mode="json") for item in job.snapshot.evidence]
        checks = (
            (rlo.id == job.request.rlo_id, "id", "RLO ID changed during generation."),
            (
                rlo.version == job.request.rlo_version,
                "version",
                "RLO version changed during generation.",
            ),
            (
                rlo.enabling_objective.statement == job.snapshot.candidate.statement,
                "enabling_objective.statement",
                "Selected objective statement changed during generation.",
            ),
            (
                [item.model_dump(mode="json") for item in rlo.sources] == expected_sources,
                "sources",
                "Immutable source identity changed during generation.",
            ),
            (
                [item.model_dump(mode="json") for item in rlo.evidence] == expected_evidence,
                "evidence",
                "Immutable evidence ledger changed during generation.",
            ),
        )
        for valid, path, message in checks:
            if not valid:
                findings.append(
                    DraftValidationFinding(
                        code="immutable_grounding_changed",
                        severity="error",
                        category="schema",
                        path=path,
                        message=message,
                    )
                )
        return findings

    def _semantic_findings(self, rlo: RLO, snapshot: RLODraftSnapshot, job_id: str):
        grounding = self._parse(
            model=GROUNDING_MODEL,
            operation="review-grounding",
            prompt=LEGACY_GROUNDING_PROMPT.text,
            content={
                "rlo": rlo.model_dump(mode="json"),
                "exact_evidence_nodes": snapshot.evidence_nodes,
            },
            text_format=DraftReviewResult,
            job_id=job_id,
        )
        pedagogy = self._parse(
            model=PEDAGOGY_MODEL,
            operation="review-pedagogy",
            prompt=LEGACY_PEDAGOGY_PROMPT.text,
            content={
                "rlo": rlo.model_dump(mode="json"),
                "approved_candidate": snapshot.candidate.model_dump(mode="json"),
                "learning_brief": snapshot.learning_brief.model_dump(mode="json"),
            },
            text_format=DraftReviewResult,
            job_id=job_id,
        )
        return [*grounding.findings, *pedagogy.findings]

    def create(self, request: RLODraftRequest, *, created_by: str | None = None) -> RLODraftJob:
        workspace, candidate = self._workspace_candidate(request)
        materials = self.source_loader(candidate)
        snapshot = self._snapshot(workspace, candidate, materials)
        job = self.store.create(request, created_by=created_by)
        if job.state != RLODraftState.QUEUED:
            return job
        generating = job.model_copy(
            update={"state": RLODraftState.GENERATING, "snapshot": snapshot}
        )
        job = self.store.transition(job=generating, expected_state=RLODraftState.QUEUED)
        try:
            rlo = self._parse(
                model=DRAFT_MODEL,
                operation="generate-draft",
                prompt=LEGACY_DRAFT_PROMPT.text,
                content={
                    "request": request.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                },
                text_format=RLO,
                job_id=job.job_id,
            )
            findings = self._fixed_fields(rlo, job)
            if not any(item.severity == "error" for item in findings):
                findings.extend(self._semantic_findings(rlo, snapshot, job.job_id))
            repairable = [item for item in findings if item.severity == "error" and item.repairable]
            if repairable:
                repaired = self._parse(
                    model=DRAFT_MODEL,
                    operation="repair-draft",
                    prompt=LEGACY_REPAIR_PROMPT.text,
                    content={
                        "rlo": rlo.model_dump(mode="json"),
                        "findings": [item.model_dump(mode="json") for item in repairable],
                        "fixed_sources": [item.model_dump(mode="json") for item in snapshot.sources],
                        "fixed_evidence": [item.model_dump(mode="json") for item in snapshot.evidence],
                    },
                    text_format=RLO,
                    job_id=job.job_id,
                )
                rlo = repaired
                findings = self._fixed_fields(rlo, job)
                if not any(item.severity == "error" for item in findings):
                    findings.extend(self._semantic_findings(rlo, snapshot, job.job_id))
            state = (
                RLODraftState.VALIDATION_FAILED
                if any(item.severity == "error" for item in findings)
                else RLODraftState.IN_REVIEW
            )
            completed = job.model_copy(
                update={
                    "state": state,
                    "draft": rlo,
                    "findings": findings,
                    "revision": 1,
                    "model_metadata": {"aliases": snapshot.model_aliases, "usage": self.usage},
                }
            )
            return self.store.transition(
                job=completed,
                expected_state=RLODraftState.GENERATING,
                save_revision=True,
            )
        except Exception as exc:
            failed = job.model_copy(
                update={"state": RLODraftState.FAILED, "error_message": str(exc)}
            )
            self.store.transition(job=failed, expected_state=RLODraftState.GENERATING)
            raise

    def replace_draft(self, job_id: str, raw: dict) -> RLODraftJob:
        job = self.store.load(job_id)
        if job is None or job.draft is None:
            raise ValueError("draft job does not exist")
        if job.authoring is not None:
            scope_error = authoring_scope_error(job.authoring)
            if scope_error:
                raise ValueError(f"RLO is outside POC2 authoring scope: {scope_error}")
        if job.state not in {
            RLODraftState.IN_REVIEW,
            RLODraftState.VALIDATION_FAILED,
            RLODraftState.REVISION_REQUESTED,
        }:
            raise ValueError("draft cannot be edited in its current state")
        try:
            rlo = RLO.model_validate(raw)
        except ValidationError:
            raise
        findings = self._fixed_fields(rlo, job)
        if not any(item.severity == "error" for item in findings):
            findings.extend(self._semantic_findings(rlo, job.snapshot, job.job_id))
        updated = job.model_copy(
            update={
                "state": RLODraftState.VALIDATION_FAILED
                if any(item.severity == "error" for item in findings)
                else RLODraftState.IN_REVIEW,
                "draft": rlo,
                "findings": findings,
                "revision": job.revision + 1,
            }
        )
        return self.store.transition(job=updated, expected_state=job.state, save_revision=True)

    def review(self, job_id: str, request: RLOReviewRequest, *, reviewer: str) -> RLODraftJob:
        job = self.store.load(job_id)
        if job is None:
            raise ValueError("draft job does not exist")
        if job.state not in {
            RLODraftState.IN_REVIEW,
            RLODraftState.REVISION_REQUESTED,
            RLODraftState.SOURCE_INSUFFICIENT,
            RLODraftState.VALIDATION_FAILED,
        }:
            raise ValueError("draft is not available for instructional-designer review")
        authoring = job.authoring
        scope_error = authoring_scope_error(authoring)
        if scope_error and request.action != ReviewAction.REJECT:
            raise ValueError(f"RLO is outside POC2 authoring scope: {scope_error}")
        if request.action == ReviewAction.APPROVE:
            if job.state != RLODraftState.IN_REVIEW or job.draft is None:
                raise ValueError("only a clean, complete RLO can be approved")
            if any(item.severity == "error" for item in job.findings):
                raise ValueError("draft with validation errors cannot be approved")
            governance = job.draft.governance.model_copy(
                update={
                    "status": type(job.draft.governance.status).APPROVED,
                    "authoring_sme": request.authoring_sme or job.created_by or reviewer,
                    "reviewing_sme": reviewer,
                    "signoff_date": date.today(),
                    "signoff_authority": request.signoff_authority or reviewer,
                }
            )
            draft = RLO.model_validate(
                {**job.draft.model_dump(mode="json"), "governance": governance.model_dump(mode="json")}
            )
            if authoring is not None:
                authoring = authoring.model_copy(
                    update={
                        "claims": [
                            claim.model_copy(
                                update={
                                    "verification_status": ClaimVerificationStatus.REVIEW_ACCEPTED
                                }
                            )
                            if claim.knowledge_origin == ClaimKnowledgeOrigin.LLM_DOMAIN
                            else claim
                            for claim in authoring.claims
                        ]
                    }
                )
            state = RLODraftState.APPROVED
        elif request.action == ReviewAction.REQUEST_REVISION:
            if not request.note:
                raise ValueError("revision requests require a note")
            draft = job.draft
            state = RLODraftState.REVISION_REQUESTED
        else:
            if not request.note:
                raise ValueError("rejections require a note")
            draft = job.draft
            state = RLODraftState.REJECTED
        review = RLOReviewRecord(
            revision=job.revision,
            action=request.action,
            note=request.note,
            reviewer=reviewer,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        updated = job.model_copy(
            update={
                "state": state,
                "draft": draft,
                "authoring": authoring,
                "reviews": [*job.reviews, review],
            }
        )
        result = self.store.transition(job=updated, expected_state=job.state)
        self.store.record_review(job_id, review)
        return result
