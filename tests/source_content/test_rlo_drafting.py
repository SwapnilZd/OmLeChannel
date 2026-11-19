from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rlo_schema import RLO
from src.source_authoring.contracts import (
    EvidenceRole,
    LearningBrief,
    ObjectiveCandidate,
    ObjectiveBloomDecision,
    ObjectiveClassification,
    ObjectiveKindDecision,
    ObjectiveEvidence,
    ObjectiveWorkspace,
    PractitionerLens,
)
from src.source_authoring.draft_contracts import (
    DraftReviewResult,
    RLODraftJob,
    RLODraftRequest,
    RLODraftState,
    RLOReviewRequest,
    ReviewAction,
)
from src.source_authoring.authoring_contracts import (
    AuthoringClaim,
    AuthoringRLORevision,
    LLMKnowledgeProvenance,
)
from src.source_authoring.drafting import DraftSourceMaterial, RLODraftingService
from src.source_ingestion.contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceFormat,
    SourceLocator,
)


class MemoryStore:
    def __init__(self):
        self.jobs = {}
        self.reviews = []

    def create(self, request, *, created_by):
        job = RLODraftJob(
            job_id="draft-job-1",
            state=RLODraftState.QUEUED,
            request=request,
            created_by=created_by,
        )
        self.jobs[job.job_id] = job
        return job

    def load(self, job_id):
        return self.jobs.get(job_id)

    def transition(self, job, *, expected_state, save_revision=False):
        current = self.jobs[job.job_id]
        assert current.state == expected_state
        self.jobs[job.job_id] = job
        return job

    def record_review(self, job_id, review):
        self.reviews.append((job_id, review))


def _workspace() -> ObjectiveWorkspace:
    brief = LearningBrief(
        brief_id="brief-1",
        collection_id="collection-1",
        lenses=[
            PractitionerLens(
                lens_id="lens-1",
                title="Coffee preparer",
                practitioner_role="Office coffee preparer",
                relevant_tasks=["Prepare coffee"],
                rationale="The source defines an operating procedure.",
                inferred=True,
            )
        ],
        source_map_revision="map-v1",
        brief_revision="map-v1:default",
    )
    candidate = ObjectiveCandidate(
        candidate_id="candidate-brew",
        statement="Prepare coffee using the available machine.",
        observable_behavior="Prepare coffee",
        performance_context="When using the office coffee machine",
        practitioner_relevance="The practitioner needs a repeatable preparation routine.",
        bloom_level="apply",
        scope="One machine preparation procedure",
        rationale="The task is directly supported.",
        confidence="high",
        confidence_rationale="The source explicitly defines the procedure.",
        rule_ids=["D-6"],
        expected_effort_minutes=5,
        evidence=[
            ObjectiveEvidence(
                evidence_id="ev-brew",
                claim_id="claim-brew",
                source_version_id="source-v1",
                node_ids=["node-brew"],
                role=EvidenceRole.OBJECTIVE_DEFINING,
                rationale="Defines the machine operation.",
                assessment_eligible=True,
            )
        ],
        selected_reason="Useful observable procedure.",
        rank=1,
        classification=ObjectiveClassification(
            content_kind=ObjectiveKindDecision(
                value="procedure",
                confidence="high",
                rationale="The learner executes supported steps.",
            ),
            bloom=ObjectiveBloomDecision(
                value="apply",
                confidence="high",
                rationale="The learner performs the procedure in a new standard case.",
                expected_practice="Execute the supported procedure.",
            ),
            combined_confidence="high",
            rule_ids=["C-1", "C-2"],
        ),
    )
    return ObjectiveWorkspace(
        workspace_id="workspace-1",
        collection_id="collection-1",
        revision=1,
        learning_brief=brief,
        candidates=[candidate],
    )


def _material(*, node_id="node-brew") -> DraftSourceMaterial:
    document = ExtractedDocument(
        source_version_id="source-v1",
        extraction_run_id="run-1",
        format=SourceFormat.PDF,
        page_count=1,
        nodes=[
            DocumentNode(
                node_id=node_id,
                ordinal=0,
                ordinal_path=(0,),
                kind="paragraph",
                role="body",
                text="Press the brew button to prepare coffee.",
                locators=[SourceLocator(page=1)],
                method=ExtractionMethod.NATIVE,
            )
        ],
    )
    return DraftSourceMaterial(
        source_id="source-coffee",
        source_version_id="source-v1",
        title="Coffee machine manual",
        filename="coffee-manual.pdf",
        checksum="1" * 64,
        document=document,
    )


def _rlo(snapshot: dict, request: dict, *, omit_component_evidence=False) -> RLO:
    evidence_id = snapshot["evidence"][0]["id"]
    refs = [evidence_id]
    return RLO.model_validate(
        {
            "id": request["rlo_id"],
            "version": request["rlo_version"],
            "title": "Prepare coffee with the office machine",
            "topic": "Coffee preparation",
            "domain": "Workplace skills",
            "level": "introductory",
            "audience": ["Learning administrators"],
            "estimated_duration_minutes": 5,
            "content_type": "procedure",
            "performance_level": "do",
            "sources": snapshot["sources"],
            "evidence": snapshot["evidence"],
            "terminal_objective": request.get(
                "terminal_objective", "Prepare a cup of coffee correctly."
            ),
            "performance_context": "When operating the available office coffee machine.",
            "enabling_objective": {
                "id": "lo-1",
                "statement": snapshot["candidate"]["statement"],
                "bloom_level": "apply",
                "concepts_addressed": ["c-1"],
                "evidence_refs": refs,
            },
            "concepts": [
                {
                    "id": "c-1",
                    "name": "Brew control",
                    "definition": "The brew control starts extraction.",
                    "elaboration": "The machine must be ready before the control is pressed.",
                    "source_refs": [snapshot["sources"][0]["id"]],
                    "evidence_refs": refs,
                    "misconceptions": [
                        {
                            "id": "m-1",
                            "statement": "Extraction starts without operating the control.",
                            "correction": "The brew control must be pressed.",
                            "evidence_refs": refs,
                        }
                    ],
                }
            ],
            "components": [
                {
                    "id": "comp-rule-1",
                    "cdt_type": "rule",
                    "concepts_referenced": ["c-1"],
                    "misconceptions_addressed": ["m-1"],
                    "evidence_refs": [] if omit_component_evidence else refs,
                    "canonical_content": "Press the brew control when the machine is ready.",
                }
            ],
            "assessment_items": [
                {
                    "id": "q-1",
                    "stem": "What starts extraction?",
                    "type": "multiple_choice_single",
                    "concepts_assessed": ["c-1"],
                    "evidence_refs": refs,
                    "options": [
                        {
                            "id": "A",
                            "text": "Pressing the brew control",
                            "correct": True,
                            "misconception_targeted": None,
                            "feedback": "Correct.",
                            "evidence_refs": refs,
                        },
                        {
                            "id": "B",
                            "text": "Waiting",
                            "correct": False,
                            "misconception_targeted": "m-1",
                            "feedback": "Operate the brew control.",
                        },
                    ],
                }
            ],
            "design_brief": {
                "tone": "Direct and practical",
                "scaffolding_level": "low",
                "scaffolding_notes": "Assume no machine experience.",
                "feedback_policy": "Name the correct operating step.",
                "salience_hook_description": "Connect the procedure to a reliable cup.",
            },
            "gagne_event_mapping": {"event_4_present_content": "comp-rule-1"},
            "authoring_rationale": "A short grounded machine-operation procedure.",
            "role_tags": ["coffee_preparer"],
            "governance": {
                "status": "draft",
                "authoring_sme": "Pending assignment",
                "change_history": "0.1.0 generated",
            },
            "accessibility": {"features": ["plain_language"]},
            "rights": {
                "rights": "internal_use",
                "sharing_constraints": "Internal only",
            },
        }
    )


class FakeResponses:
    def __init__(self, *, omit_component_evidence=False, findings=()):
        self.calls = []
        self.omit_component_evidence = omit_component_evidence
        self.findings = list(findings)

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(kwargs["input"][1]["content"])
        if kwargs["text_format"] is RLO:
            parsed = _rlo(
                payload["snapshot"],
                payload["request"],
                omit_component_evidence=self.omit_component_evidence,
            )
        elif kwargs["text_format"] is DraftReviewResult:
            parsed = DraftReviewResult(findings=self.findings)
        else:
            raise AssertionError(kwargs["text_format"])
        return SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def _request() -> RLODraftRequest:
    return RLODraftRequest(
        workspace_id="workspace-1",
        workspace_revision=1,
        candidate_id="candidate-brew",
        rlo_id="rlo-coffee-brew",
        rlo_version="0.1.0",
    )


def _service(monkeypatch, *, responses=None, material=None):
    workspace = _workspace()
    monkeypatch.setattr(
        "src.source_authoring.drafting.repository.get_objective_workspace",
        lambda *_args: workspace,
    )
    store = MemoryStore()
    responses = responses or FakeResponses()
    service = RLODraftingService(
        client=SimpleNamespace(responses=responses),
        store=store,
        source_loader=lambda _candidate: [material or _material()],
    )
    return service, store, responses


def test_selected_objective_yields_evidence_complete_review_draft(monkeypatch):
    service, _store, responses = _service(monkeypatch)

    job = service.create(_request(), created_by="learning-admin")

    assert job.state == RLODraftState.IN_REVIEW
    assert job.revision == 1
    assert job.draft.evidence[0].node_ids == ["node-brew"]
    assert job.draft.enabling_objective.evidence_refs == ["ev-brew"]
    assert len(responses.calls) == 3
    assert all(call["model"].startswith("source-rlo-") for call in responses.calls)


def test_missing_extracted_node_fails_before_generation(monkeypatch):
    service, store, responses = _service(monkeypatch, material=_material(node_id="other-node"))

    with pytest.raises(ValueError, match="missing source node"):
        service.create(_request())

    assert store.jobs == {}
    assert responses.calls == []


def test_missing_claim_evidence_blocks_instructional_review(monkeypatch):
    responses = FakeResponses(omit_component_evidence=True)
    service, _store, responses = _service(monkeypatch, responses=responses)

    job = service.create(_request())

    assert job.state == RLODraftState.VALIDATION_FAILED
    assert job.findings[0].path == "components.comp-rule-1"
    assert len(responses.calls) == 1


def test_missing_required_authoring_metadata_blocks_instructional_review(monkeypatch):
    service, _store, _responses = _service(monkeypatch)
    job = service.create(_request())
    raw = job.draft.model_dump(mode="json")
    raw["audience"] = []
    raw["role_tags"] = []
    raw["accessibility"] = {"features": []}
    raw["rights"] = None

    updated = service.replace_draft(job.job_id, raw)

    assert updated.state == RLODraftState.VALIDATION_FAILED
    assert {item.code for item in updated.findings} == {
        "rights_required",
        "accessibility_required",
        "targeting_required",
    }


def test_one_instructional_designer_can_approve_valid_draft(monkeypatch):
    service, store, _responses = _service(monkeypatch)
    job = service.create(_request())

    approved = service.review(
        job.job_id,
        RLOReviewRequest(
            action=ReviewAction.APPROVE,
            authoring_sme="Coffee SME",
            signoff_authority="Learning Design Lead",
        ),
        reviewer="designer@deloitte.com",
    )

    assert approved.state == RLODraftState.APPROVED
    assert approved.draft.governance.reviewing_sme == "designer@deloitte.com"
    assert approved.draft.governance.status.value == "approved"
    assert len(store.reviews) == 1


def test_approval_marks_llm_domain_claims_review_accepted(monkeypatch):
    service, store, _responses = _service(monkeypatch)
    job = service.create(_request())
    provenance = LLMKnowledgeProvenance(
        provenance_id="llm-knowledge-1",
        operation="llm-domain-enrichment",
        model_alias="source-rlo-domain-enrichment",
        prompt_id="source-rlo-domain-enrichment",
        prompt_version="v1",
        prompt_filename="llm_domain_enrichment.md",
        prompt_sha256="a" * 64,
        input_sha256="b" * 64,
        generated_at="2026-09-09T12:00:00+00:00",
    )
    llm_claim = AuthoringClaim(
        claim_id="claim-llm",
        statement="A changed operating condition can require a different response.",
        knowledge_origin="llm_domain",
        verification_status="unverified",
        llm_provenance_ref=provenance.provenance_id,
        origin_rationale="Model knowledge fills a declared instructional gap.",
        role="objective_defining",
        assessment_eligible=True,
    )
    authoring = AuthoringRLORevision.model_construct(
        authoring_revision_id="authoring-revision-1",
        claims=[llm_claim],
        llm_knowledge_provenance=[provenance],
        parts=[],
    )
    store.jobs[job.job_id] = job.model_copy(update={"authoring": authoring})

    approved = service.review(
        job.job_id,
        RLOReviewRequest(
            action=ReviewAction.APPROVE,
            authoring_sme="Coffee SME",
            signoff_authority="Learning Design Lead",
        ),
        reviewer="designer@deloitte.com",
    )

    reviewed_claim = next(
        claim for claim in approved.authoring.claims if claim.claim_id == "claim-llm"
    )
    assert reviewed_claim.verification_status.value == "review_accepted"


def test_revision_and_rejection_require_human_note(monkeypatch):
    service, _store, _responses = _service(monkeypatch)
    job = service.create(_request())

    with pytest.raises(ValueError, match="require a note"):
        service.review(
            job.job_id,
            RLOReviewRequest(action=ReviewAction.REQUEST_REVISION),
            reviewer="designer@deloitte.com",
        )
