import json
from types import SimpleNamespace

import pytest

from src.source_authoring.contracts import (
    CandidateCoverageAssignment,
    CriticFinding,
    CurriculumGapTarget,
    EvidenceRole,
    GapTargetAlignment,
    ObjectiveBloomDecision,
    ObjectiveClassification,
    ObjectiveEvidence,
    ObjectiveKindDecision,
    ObjectiveDiscoveryBasis,
    ObjectiveScopeStatus,
    ObjectiveSupportProfile,
    ObjectiveWorkspace,
    PractitionerInstructions,
    PractitionerLens,
    SourceSupportLevel,
)
from src.source_authoring.objectives import (
    CoverageGapDraft,
    CurriculumBlueprintDraft,
    CurriculumCoverageDraft,
    CurriculumDomainCoverageDraft,
    CurriculumDomainDraft,
    CurriculumGapTargetDraft,
    EvidenceVerification,
    LensDraft,
    ObjectiveDiscoveryService,
    ObjectiveClassificationDraft,
    ObjectiveProposalDraft,
    ObjectiveSupportAssessmentDraft,
    PedagogyCritique,
    ProposedEvidenceUse,
    ProposedObjective,
    ProposedSignal,
    ProposedSourceFeature,
    RelatedObjectiveDraft,
    SignalDetectionDraft,
    SourceFeatureDraft,
)
from src.source_ingestion.contracts import (
    CollectionMap,
    CollectionSource,
    CoverageEntry,
    CoverageLedger,
    CoverageStatus,
    DocumentNode,
    EvidenceCitation,
    ExtractedDocument,
    ExtractionMethod,
    MapClaim,
    MapConflict,
    SourceLocator,
)
from src.source_ingestion.segmentation import TokenBudgetExceeded


class WorkspaceStore:
    def __init__(self):
        self.briefs = {}
        self.workspaces = {}

    def load(self, workspace_id):
        return self.workspaces.get(workspace_id)

    def save_brief(self, brief):
        self.briefs[brief.brief_revision] = brief
        return brief

    def save_workspace(self, workspace, **kwargs):
        self.workspaces[workspace.workspace_id] = workspace
        return workspace


def _proposal(
    candidate_id,
    *,
    uses=None,
    priority=1,
    statement=None,
    bloom_level="apply",
    content_type_hint="procedure",
):
    return ProposedObjective(
        candidate_id=candidate_id,
        statement=statement or f"Prepare coffee using procedure {candidate_id}.",
        observable_behavior="Prepare coffee",
        performance_context="When using the available coffee machine",
        practitioner_relevance=(
            "Deloitte practitioners may need to prepare coffee during workplace routines."
        ),
        scope="One coffee preparation procedure",
        prerequisites=[],
        rationale="The behavior is useful and directly supported.",
        confidence="medium",
        confidence_rationale="One direct procedural source claim supports the objective.",
        rule_ids=["D-6"],
        assumptions=["The machine is operational."],
        expected_effort_minutes=8,
        evidence_uses=uses
        or [
            ProposedEvidenceUse(
                claim_id="claim-brew",
                role=EvidenceRole.OBJECTIVE_DEFINING,
                rationale="This claim defines the preparation behavior.",
            )
        ],
        selected_reason="Directly supports a realistic learner task.",
        priority=priority,
    )


class ObjectiveResponses:
    def __init__(
        self,
        proposals,
        source_features=None,
        proposals_by_pass=None,
        gap_proposals=None,
        related_proposals=None,
        force_partial_coverage=False,
        partial_domain_indexes=None,
        unwarranted_domain_indexes=None,
        domain_importance_by_claim=None,
        gap_alignment_by_candidate=None,
        target_counts_by_domain_index=None,
        wrong_gap_target_id=False,
        invalid_classification_ids=None,
        invalid_classification_repairs=False,
        gap_alignment_claim_ids_by_candidate=None,
        cross_domain_gap_target=False,
    ):
        self.proposals = proposals
        self.source_features = source_features or []
        self.proposals_by_pass = proposals_by_pass
        self.gap_proposals = gap_proposals or []
        self.related_proposals = related_proposals or []
        self.force_partial_coverage = force_partial_coverage
        self.partial_domain_indexes = (
            set(partial_domain_indexes)
            if partial_domain_indexes is not None
            else ({0} if force_partial_coverage else set())
        )
        self.unwarranted_domain_indexes = set(unwarranted_domain_indexes or [])
        self.domain_importance_by_claim = domain_importance_by_claim or {}
        self.gap_alignment_by_candidate = gap_alignment_by_candidate or {}
        self.target_counts_by_domain_index = target_counts_by_domain_index or {}
        self.wrong_gap_target_id = wrong_gap_target_id
        self.invalid_classification_ids = set(invalid_classification_ids or [])
        self.invalid_classification_repairs = invalid_classification_repairs
        self.gap_alignment_claim_ids_by_candidate = (
            gap_alignment_claim_ids_by_candidate or {}
        )
        self.cross_domain_gap_target = cross_domain_gap_target
        self.proposal_pass = 0
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        text_format = kwargs["text_format"]
        if text_format is LensDraft:
            parsed = LensDraft(
                lenses=[
                    PractitionerLens(
                        lens_id="lens-1",
                        title="Coffee preparer",
                        practitioner_role="Person preparing coffee",
                        relevant_tasks=["Prepare a cup"],
                        rationale="The source contains an operating procedure.",
                        inferred=True,
                    )
                ]
            )
        elif text_format is CurriculumBlueprintDraft:
            content = json.loads(kwargs["input"][1]["content"])
            claim_ids = [claim["claim_id"] for claim in content.get("claims", [])]
            if not claim_ids:
                claim_ids = list(
                    dict.fromkeys(
                        claim_id
                        for partial in content.get("partial_blueprints", [])
                        for domain in partial["domains"]
                        for claim_id in domain["claim_ids"]
                    )
                )
            parsed = CurriculumBlueprintDraft(
                central_purpose="Prepare coffee and understand factors affecting it.",
                central_claim_ids=[claim_ids[0]],
                intended_use="Guide a learner through supported coffee decisions.",
                domains=[
                    CurriculumDomainDraft(
                        title=f"Domain for {claim_id}",
                        description=f"Learning supported by {claim_id}.",
                        importance=self.domain_importance_by_claim.get(
                            claim_id, "core"
                        ),
                        rationale="The claim contributes to the source purpose.",
                        claim_ids=[claim_id],
                    )
                    for claim_id in claim_ids
                ],
            )
        elif text_format is SignalDetectionDraft:
            content = json.loads(kwargs["input"][1]["content"])
            claim_ids = {claim["claim_id"] for claim in content["claims"]}
            parsed = SignalDetectionDraft(
                signals=[
                    ProposedSignal(
                        signal_id=f"signal-{proposal.candidate_id}",
                        rule_id=proposal.rule_ids[0],
                        signal_type="worked_example",
                        interpretation=proposal.rationale,
                        confidence=proposal.confidence,
                        evidence_uses=proposal.evidence_uses,
                    )
                    for proposal in self.proposals
                    if {item.claim_id for item in proposal.evidence_uses} <= claim_ids
                ]
            )
        elif text_format is SourceFeatureDraft:
            content = json.loads(kwargs["input"][1]["content"])
            claim_ids = {claim["claim_id"] for claim in content["claims"]}
            parsed = SourceFeatureDraft(
                source_features=[
                    feature
                    for feature in self.source_features
                    if {item.claim_id for item in feature.evidence_uses} <= claim_ids
                ]
            )
        elif text_format is ObjectiveProposalDraft:
            content = json.loads(kwargs["input"][1]["content"])
            claim_ids = {claim["claim_id"] for claim in content["claims"]}
            proposals = self.proposals
            if self.proposals_by_pass is not None:
                proposals = (
                    self.proposals_by_pass[self.proposal_pass]
                    if self.proposal_pass < len(self.proposals_by_pass)
                    else []
                )
                self.proposal_pass += 1
            parsed = ObjectiveProposalDraft(
                candidates=[
                    proposal
                    for proposal in proposals
                    if "batch_index" not in content
                    or {item.claim_id for item in proposal.evidence_uses} <= claim_ids
                ],
            )
        elif text_format is ObjectiveClassificationDraft:
            content = json.loads(kwargs["input"][1]["content"])
            candidate_id = content["candidate"]["candidate_id"]
            invalid = candidate_id in self.invalid_classification_ids and (
                self.invalid_classification_repairs
                or not kwargs["metadata"]["operation"].endswith("-repair")
            )
            is_analysis = candidate_id == "analyze-flavor"
            kind = "principle" if is_analysis else "procedure"
            bloom = "analyze" if is_analysis else "apply"
            classification = ObjectiveClassification(
                content_kind=ObjectiveKindDecision(
                    value=kind,
                    confidence="medium",
                    rationale="The expected performance determines the content kind.",
                ),
                bloom=ObjectiveBloomDecision(
                    value=bloom,
                    confidence="medium",
                    rationale="The expected practice determines the Bloom level.",
                    expected_practice="Perform the stated objective in a new case.",
                ),
                combined_confidence="medium",
                provisional=True,
                escalation_required=False,
                plausible_alternative_cells=[],
                rejected_cells=[],
                discriminator_question=None,
                verb_practice_mismatch=None,
                rule_ids=["C-1", "C-2", "C-20"],
            )
            if invalid:
                classification = classification.model_copy(
                    update={"escalation_required": True}
                )
            parsed = ObjectiveClassificationDraft.model_construct(
                candidate_id=candidate_id,
                scope_status=(
                    ObjectiveScopeStatus.OUTSIDE_POC2_SCOPE
                    if is_analysis
                    else ObjectiveScopeStatus.SUPPORTED
                ),
                classification=None if is_analysis else classification,
                scope_reason=(
                    "Principle × Analyze is outside POC2 authoring scope."
                    if is_analysis
                    else None
                ),
            )
        elif text_format is CurriculumCoverageDraft:
            content = json.loads(kwargs["input"][1]["content"])
            blueprint = content["curriculum_blueprint"]
            candidates = content.get("candidates", [])
            if not candidates:
                candidates = [
                    candidate
                    for partial in content.get("partial_reviews", [])
                    for candidate in partial["assignments"]
                ]
                candidate_claims = {candidate["candidate_id"]: [] for candidate in candidates}
            else:
                candidate_claims = {
                    candidate["candidate_id"]: candidate["claim_ids"]
                    for candidate in candidates
                }
            assignments = []
            for candidate in candidates:
                candidate_id = candidate["candidate_id"]
                domain_ids = [
                    domain["domain_id"]
                    for domain in blueprint["domains"]
                    if set(candidate_claims.get(candidate_id, [])) & set(domain["claim_ids"])
                ]
                assignments.append(
                    CandidateCoverageAssignment(
                        candidate_id=candidate_id,
                        domain_ids=domain_ids,
                        role="primary" if domain_ids else "peripheral",
                        contribution="Covers supported source material.",
                    )
                )
            domain_coverage = []
            for index, domain in enumerate(blueprint["domains"]):
                matched = [
                    assignment.candidate_id
                    for assignment in assignments
                    if domain["domain_id"] in assignment.domain_ids
                ]
                state = "adequate" if matched else "source_insufficient"
                if index in self.partial_domain_indexes and not any(
                    candidate_id.startswith("gap-") for candidate_id in matched
                ):
                    state = "partial"
                target_claim_ids = domain["claim_ids"]
                if (
                    self.cross_domain_gap_target
                    and index == 0
                    and len(blueprint["domains"]) > 1
                ):
                    target_claim_ids = [
                        *target_claim_ids,
                        blueprint["domains"][1]["claim_ids"][0],
                    ]
                domain_coverage.append(
                    CurriculumDomainCoverageDraft(
                        domain_id=domain["domain_id"],
                        state=state,
                        candidate_ids=matched,
                        rationale="Coverage was evaluated against the domain.",
                        gap_targets=[
                            CurriculumGapTargetDraft(
                                performance=(
                                    f"Perform missing work {target_number} for "
                                    f"{domain['claim_ids'][0]}."
                                ),
                                rationale=(
                                    "This performance materially advances the "
                                    "central instructional purpose."
                                ),
                                claim_ids=target_claim_ids,
                                evidence_sufficiency=(
                                    "insufficient"
                                    if index in self.unwarranted_domain_indexes
                                    else "sufficient"
                                ),
                                sufficiency_rationale=(
                                    "The domain claims define the performance."
                                    if index not in self.unwarranted_domain_indexes
                                    else "The claims do not define a complete performance."
                                ),
                                search_warranted=(
                                    index not in self.unwarranted_domain_indexes
                                ),
                            )
                            for target_number in range(
                                1,
                                self.target_counts_by_domain_index.get(index, 1) + 1,
                            )
                        ]
                        if state == "partial"
                        else [],
                    )
                )
            parsed = CurriculumCoverageDraft(
                assignments=assignments,
                domain_coverage=domain_coverage,
            )
        elif text_format is CoverageGapDraft:
            content = json.loads(kwargs["input"][1]["content"])
            parsed = CoverageGapDraft(
                target_id=(
                    "wrong-target"
                    if self.wrong_gap_target_id
                    else content["selected_gap_target"]["target_id"]
                ),
                candidates=self.gap_proposals,
            )
        elif text_format is RelatedObjectiveDraft:
            content = json.loads(kwargs["input"][1]["content"])
            parsed = RelatedObjectiveDraft(
                target_id=content["selected_gap_target"]["target_id"],
                candidates=self.related_proposals,
            )
        elif text_format is ObjectiveSupportAssessmentDraft:
            content = json.loads(kwargs["input"][1]["content"])
            support_profile = content["candidate"].get("support_profile")
            parsed = ObjectiveSupportAssessmentDraft(
                candidate_id=content["candidate"]["candidate_id"],
                accepted=support_profile is not None,
                support_profile=ObjectiveSupportProfile.model_validate(support_profile)
                if support_profile
                else None,
                rejection_reason=None
                if support_profile
                else "No related candidate was configured for this test.",
            )
        elif text_format is GapTargetAlignment:
            content = json.loads(kwargs["input"][1]["content"])
            proposal = content["candidate"]
            target = content["gap_target"]
            supplied_claim_ids = {claim["claim_id"] for claim in content["claims"]}
            parsed = GapTargetAlignment(
                target_id=target["target_id"],
                candidate_id=proposal["candidate_id"],
                alignment=self.gap_alignment_by_candidate.get(
                    proposal["candidate_id"], "direct"
                ),
                rationale="The candidate was compared with the complete target.",
                unsupported_performance_parts=[],
                claim_ids_used=self.gap_alignment_claim_ids_by_candidate.get(
                    proposal["candidate_id"],
                    [
                        item["claim_id"]
                        for item in proposal["evidence_uses"]
                        if item["claim_id"] in supplied_claim_ids
                    ],
                ),
            )
        elif text_format is EvidenceVerification:
            content = json.loads(kwargs["input"][1]["content"])
            candidate_id = content["candidate"]["candidate_id"]
            parsed = EvidenceVerification(
                candidate_id=candidate_id,
                supported=not candidate_id.startswith("unsupported"),
                unsupported_parts=["The behavior is not supported."]
                if candidate_id.startswith("unsupported")
                else [],
            )
        elif text_format is PedagogyCritique:
            content = json.loads(kwargs["input"][1]["content"])
            candidate_id = content["candidate"]["candidate_id"]
            topic = candidate_id.startswith("topic")
            parsed = PedagogyCritique(
                candidate_id=candidate_id,
                accepted=not topic,
                findings=[
                    CriticFinding(
                        code="topic_label",
                        message="This is a topic, not an observable objective.",
                        severity="error",
                    )
                ]
                if topic
                else [],
                duplicate_group="same-procedure" if candidate_id.startswith("dup") else None,
                recommended_rank=int(candidate_id.rsplit("-", 1)[-1])
                if candidate_id.rsplit("-", 1)[-1].isdigit()
                else 1,
            )
        else:
            raise AssertionError(f"unexpected response type: {text_format}")
        return SimpleNamespace(output_parsed=parsed, usage=None)


class ProposalBatchBudget:
    source_token_limit = 15_000
    request_token_limit = 15_000

    def require_within_limit(self, text, **_kwargs):
        if '"relationships"' in text and text.count('"statement"') > 1:
            raise TokenBudgetExceeded("proposal input exceeds configured limit")
        return 1


class VerificationBudget:
    source_token_limit = 15_000
    request_token_limit = 15_000

    def require_within_limit(self, text, **_kwargs):
        if '"assessment_eligible"' in text:
            raise TokenBudgetExceeded("evidence exceeds configured limit")
        return 1


class EnrichedBatchBudget:
    source_token_limit = 15_000
    request_token_limit = 15_000

    def require_within_limit(self, text, **_kwargs):
        content = json.loads(text)
        request_claim_ids = {
            claim["claim_id"] for claim in content.get("claims", [])
        }
        if '"detected_signals"' in text and request_claim_ids == {
            "claim-brew",
            "claim-soil",
        }:
            raise TokenBudgetExceeded("enriched proposal input exceeds configured limit")
        return 1


def _document(source_id="source-v1", node_texts=None):
    node_texts = node_texts or [
        "Insert a capsule and press the brew button.",
        "Soil conditions can influence coffee flavor.",
    ]
    nodes = [
        DocumentNode(
            node_id=f"{source_id}-node-{index}",
            ordinal=index,
            ordinal_path=(index,),
            kind="paragraph",
            role="body",
            text=text,
            locators=[SourceLocator(page=1)],
            method=ExtractionMethod.NATIVE,
        )
        for index, text in enumerate(node_texts, start=1)
    ]
    return ExtractedDocument(
        source_version_id=source_id,
        extraction_run_id=f"run-{source_id}",
        format="pdf",
        page_count=1,
        nodes=nodes,
    )


def _collection_map(*, multi_source=False):
    brew_citations = [
        EvidenceCitation(source_version_id="source-v1", node_ids=["source-v1-node-1"])
    ]
    sources = [CollectionSource(source_version_id="source-v1", ordinal=0)]
    conflicts = []
    if multi_source:
        brew_citations.append(
            EvidenceCitation(source_version_id="source-v2", node_ids=["source-v2-node-1"])
        )
        sources.append(
            CollectionSource(
                source_version_id="source-v2",
                ordinal=1,
                authority_note="Secondary operating guide",
            )
        )
        conflicts.append(
            MapConflict(
                conflict_id="conflict-brew",
                description="The guides specify different brew durations.",
                citations=brew_citations,
            )
        )
    claims = [
        MapClaim(
            claim_id="claim-brew",
            statement="The user inserts a capsule and starts brewing.",
            citations=brew_citations,
        ),
        MapClaim(
            claim_id="claim-soil",
            statement="Soil conditions can influence flavor.",
            citations=[
                EvidenceCitation(
                    source_version_id="source-v1", node_ids=["source-v1-node-2"]
                )
            ],
        ),
    ]
    entries = [
        CoverageEntry(
            source_version_id=citation.source_version_id,
            node_id=node_id,
            status=CoverageStatus.REPRESENTED,
            claim_ids=[claim.claim_id],
        )
        for claim in claims
        for citation in claim.citations
        for node_id in citation.node_ids
    ]
    return CollectionMap(
        map_id="map-collection",
        collection_id="collection-1",
        sources=sources,
        document_map_ids=[f"map-{source.source_version_id}" for source in sources],
        claims=claims,
        conflicts=conflicts,
        coverage=CoverageLedger(entries=entries),
        map_revision="source-map-v1",
    )


def _discover(
    proposals,
    *,
    collection_map=None,
    documents=None,
    findings_callback=None,
    token_budget=None,
):
    responses = ObjectiveResponses(proposals)
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
        findings_callback=findings_callback,
        token_budget=token_budget,
    )
    collection_map = collection_map or _collection_map()
    documents = documents or {"source-v1": _document()}
    return service.discover(collection_map, documents, created_by="admin-1"), responses


def test_preliminary_findings_are_published_before_candidate_verification_finishes():
    findings = []
    proposal = _proposal("brew-live")

    workspace, _ = _discover([proposal], findings_callback=findings.append)

    assert workspace.candidates[0].candidate_id == "brew-live"
    assert findings == [
        {
            "preliminary_candidates": [
                {
                    "candidate_id": "brew-live",
                    "statement": proposal.statement,
                    "confidence": str(proposal.confidence),
                    "practitioner_relevance": proposal.practitioner_relevance,
                }
            ],
            "preliminary_candidate_count": 1,
            "preliminary_feature_count": 0,
            "preliminary_signal_count": 1,
            "discovery_batches_completed": 1,
            "discovery_batch_count": 1,
            "discovery_pass_completed": 1,
            "new_candidates_this_pass": 1,
            "findings_status": "unverified",
        }
    ]


def test_discovery_passes_use_compact_memory_and_add_diverse_objectives():
    prepare = _proposal("prepare")
    analyze = _proposal(
        "analyze-flavor",
        statement="Analyze how soil conditions can affect coffee flavor.",
        bloom_level="analyze",
        content_type_hint="principle",
        uses=[
            ProposedEvidenceUse(
                claim_id="claim-soil",
                role=EvidenceRole.OBJECTIVE_DEFINING,
                rationale="Defines the flavor-analysis relationship.",
            )
        ],
    )
    responses = ObjectiveResponses(
        [prepare, analyze],
        proposals_by_pass=[[prepare], [analyze], []],
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert {candidate.statement for candidate in workspace.candidates} == {
        prepare.statement,
        analyze.statement,
    }
    proposal_calls = [
        call for call in responses.calls if call["text_format"] is ObjectiveProposalDraft
    ]
    assert len(proposal_calls) == 3
    second_input = json.loads(proposal_calls[1]["input"][1]["content"])
    context = second_input["discovery_context"]
    prepare_domain_id = next(
        domain["domain_id"]
        for domain in second_input["curriculum_blueprint"]["domains"]
        if "claim-brew" in domain["claim_ids"]
    )
    assert context["pass_number"] == 2
    assert context["prior_candidate_memory"] == [
        {
            "candidate_id": "prepare",
            "claim_ids": ["claim-brew"],
            "curriculum_domain_ids": [prepare_domain_id],
            "observable_behavior": "Prepare coffee",
            "statement": prepare.statement,
        }
    ]
    assert context["uncovered_claim_ids"] == ["claim-soil"]
    assert context["covered_curriculum_domain_ids"] == [prepare_domain_id]
    assert "diversity_summary" not in context


def test_discovery_persists_blueprint_and_set_level_coverage():
    workspace, responses = _discover([_proposal("brew-covered")])

    assert workspace.curriculum_blueprint is not None
    assert workspace.curriculum_coverage is not None
    assert workspace.curriculum_coverage.workspace_revision == workspace.revision
    assert workspace.curriculum_coverage.assignments[0].candidate_id == "brew-covered"
    proposal_inputs = [
        json.loads(call["input"][1]["content"])
        for call in responses.calls
        if call["text_format"] is ObjectiveProposalDraft
    ]
    assert proposal_inputs
    assert {
        value["curriculum_blueprint"]["blueprint_id"] for value in proposal_inputs
    } == {workspace.curriculum_blueprint.blueprint_id}
    coverage_input = next(
        json.loads(call["input"][1]["content"])
        for call in responses.calls
        if call["metadata"]["operation"] == "review-objective-set-coverage-initial"
    )
    assert coverage_input["curriculum_claims"] == [
        {
            "claim_id": "claim-brew",
            "statement": "The user inserts a capsule and starts brewing.",
        },
        {
            "claim_id": "claim-soil",
            "statement": "Soil conditions can influence flavor.",
        },
    ]


def test_cross_domain_gap_evidence_degrades_only_the_invalid_target():
    responses = ObjectiveResponses(
        [_proposal("brew-covered")],
        force_partial_coverage=True,
        cross_domain_gap_target=True,
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    target = workspace.curriculum_coverage.domain_coverage[0].gap_targets[0]
    assert target.claim_ids == ["claim-brew"]
    assert target.evidence_sufficiency == "insufficient"
    assert target.search_warranted is False
    assert "outside this curriculum domain" in target.sufficiency_rationale
    assert any(
        "reframed using only evidence" in question
        for question in workspace.curriculum_coverage.reviewer_questions
    )


def test_cross_domain_gap_checkpoint_replay_preserves_prior_model_results():
    checkpoints = {}

    def save(_job_id, **values):
        checkpoints[values["operation"]] = values["output_payload"]

    responses = ObjectiveResponses(
        [_proposal("brew-covered")],
        force_partial_coverage=True,
        cross_domain_gap_target=True,
    )
    first = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
        checkpoint_saver=save,
    ).discover(_collection_map(), {"source-v1": _document()}, created_by="admin-1")

    def load(_job_id, **identity):
        return checkpoints.get(identity["operation"])

    replay = ObjectiveDiscoveryService(
        client=SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **kwargs: pytest.fail("checkpoint replay called the model")
            )
        ),
        store=WorkspaceStore(),
        checkpoint_loader=load,
    ).discover(_collection_map(), {"source-v1": _document()}, created_by="admin-1")

    assert replay.curriculum_coverage == first.curriculum_coverage
    assert replay.candidates == first.candidates


def test_workspace_rejects_current_coverage_with_unknown_domain_reference():
    workspace, _responses = _discover([_proposal("brew-covered")])
    payload = workspace.model_dump(mode="json")
    payload["curriculum_coverage"]["assignments"][0]["domain_ids"] = [
        "unknown-domain"
    ]

    with pytest.raises(ValueError, match="unknown domain"):
        ObjectiveWorkspace.model_validate(payload)


def test_legacy_workspace_without_coverage_is_regenerated():
    store = WorkspaceStore()
    first_service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=ObjectiveResponses([_proposal("first")])),
        store=store,
    )
    first = first_service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )
    store.workspaces[first.workspace_id] = first.model_copy(
        update={"curriculum_blueprint": None, "curriculum_coverage": None}
    )
    second_service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=ObjectiveResponses([_proposal("second")])),
        store=store,
    )

    revised = second_service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert revised.revision == 2
    assert revised.curriculum_blueprint is not None
    assert revised.curriculum_coverage is not None


def test_one_bounded_gap_pass_adds_grounded_candidate_and_reruns_coverage():
    initial = _proposal("initial-brew")
    gap = _proposal("gap-brew", statement="The learner will be able to start brewing coffee.")
    responses = ObjectiveResponses(
        [initial],
        gap_proposals=[gap],
        force_partial_coverage=True,
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert [candidate.candidate_id for candidate in workspace.candidates] == [
        "initial-brew",
        "gap-brew",
    ]
    assert workspace.curriculum_coverage.gap_candidate_ids == ["gap-brew"]
    operations = [call["metadata"]["operation"] for call in responses.calls]
    gap_operations = [
        operation
        for operation in operations
        if operation.startswith("discover-curriculum-gap-")
    ]
    assert gap_operations == ["discover-curriculum-gap-0001-target-01"]
    assert "review-objective-set-coverage-initial" in operations
    assert "review-objective-set-coverage-final" in operations


def test_parse_replays_a_valid_model_checkpoint_without_calling_the_model():
    checkpoint = LensDraft(
        lenses=[
            PractitionerLens(
                lens_id="lens-1",
                title="Practitioner",
                practitioner_role="Deloitte practitioner",
                relevant_tasks=["Use the source material"],
                rationale="The source supports this lens.",
                inferred=True,
            )
        ]
    )
    loaded = []
    progress = []

    def load(job_id, **identity):
        loaded.append((job_id, identity))
        return checkpoint.model_dump(mode="json")

    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **kwargs: pytest.fail("checkpoint replay called the model")
        )
    )
    service = ObjectiveDiscoveryService(
        client=client,
        store=WorkspaceStore(),
        checkpoint_loader=load,
        progress_callback=lambda operation, state: progress.append((operation, state)),
    )

    result = service._parse(
        model="source-practitioner-lens",
        operation="propose-lenses",
        prompt=SimpleNamespace(
            prompt_id="test-prompt",
            version="v1",
            sha256="a" * 64,
            filename="test.md",
            text="Test prompt",
        ),
        content={"claims": []},
        text_format=LensDraft,
        job_id="objective-job-1",
    )

    assert result == checkpoint
    assert loaded[0][0] == "objective-job-1"
    assert loaded[0][1]["input_sha256"]
    assert progress == [("propose-lenses", "running"), ("propose-lenses", "completed")]


def test_invalid_classification_is_repaired_without_losing_the_objective():
    proposal = _proposal("repair-me")
    responses = ObjectiveResponses(
        [proposal], invalid_classification_ids={proposal.candidate_id}
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert [candidate.candidate_id for candidate in workspace.candidates] == [
        proposal.candidate_id
    ]
    assert workspace.candidates[0].classification is not None
    operations = [call["metadata"]["operation"] for call in responses.calls]
    assert f"classify-objective-{proposal.candidate_id}-repair" in operations


def test_repeated_invalid_classification_keeps_grounded_objective_unclassified():
    proposal = _proposal("keep-me")
    responses = ObjectiveResponses(
        [proposal],
        invalid_classification_ids={proposal.candidate_id},
        invalid_classification_repairs=True,
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    candidate = workspace.candidates[0]
    assert candidate.candidate_id == proposal.candidate_id
    assert candidate.classification is None
    assert candidate.bloom_level is None
    assert candidate.content_type_hint is None
    assert "Provisional classification unavailable" in candidate.assumptions[-1]
    assert not workspace.rejected


def test_gap_sweep_visits_each_eligible_domain_once_with_progressive_memory():
    initial_brew = _proposal("initial-brew")
    initial_soil = _proposal(
        "initial-soil",
        uses=[
            ProposedEvidenceUse(
                claim_id="claim-soil",
                role=EvidenceRole.OBJECTIVE_DEFINING,
                rationale="Defines a supported flavor decision.",
            )
        ],
    )
    gap_brew = _proposal("gap-brew")
    gap_soil = _proposal(
        "gap-soil",
        uses=[
            ProposedEvidenceUse(
                claim_id="claim-soil",
                role=EvidenceRole.OBJECTIVE_DEFINING,
                rationale="Defines a missing supported flavor decision.",
            )
        ],
    )
    responses = ObjectiveResponses(
        [initial_brew, initial_soil],
        gap_proposals=[gap_brew, gap_soil],
        partial_domain_indexes={0, 1},
        domain_importance_by_claim={"claim-soil": "supporting"},
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    gap_calls = [
        call for call in responses.calls if call["text_format"] is CoverageGapDraft
    ]
    assert len(gap_calls) == 2
    first = json.loads(gap_calls[0]["input"][1]["content"])
    second = json.loads(gap_calls[1]["input"][1]["content"])
    assert [claim["claim_id"] for claim in first["claims"]] == ["claim-brew"]
    assert [claim["claim_id"] for claim in second["claims"]] == ["claim-soil"]
    assert "gap-brew" in {
        item["candidate_id"] for item in second["existing_candidate_memory"]
    }
    records = workspace.curriculum_coverage.gap_discovery_records
    assert len(records) == 2
    assert [record.accepted_candidate_ids for record in records] == [
        ["gap-brew"],
        ["gap-soil"],
    ]
    assert all(record.prompt_run_ids for record in records)
    assert all(not record.no_candidate_found for record in records)
    assert all(record.selected_for_discovery for record in records)
    assert [rejection.reason_codes for rejection in records[0].rejections] == [
        ["claim_outside_selected_domain_batch"]
    ]
    assert [rejection.reason_codes for rejection in records[1].rejections] == [
        ["claim_outside_selected_domain_batch"]
    ]
    assert all(
        target_record.direct_candidate_ids
        for record in records
        for target_record in record.target_records
    )


def test_gap_sweep_records_an_ineligible_partial_domain_without_calling_model():
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        force_partial_coverage=True,
        unwarranted_domain_indexes={0},
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    gap_calls = [
        call for call in responses.calls if call["text_format"] is CoverageGapDraft
    ]
    assert gap_calls == []
    record = workspace.curriculum_coverage.gap_discovery_records[0]
    assert record.warranted is False
    assert record.selected_for_discovery is False
    assert record.prompt_run_ids == []
    assert record.no_candidate_found is True


def test_source_insufficient_target_can_produce_labeled_related_objective():
    related = _proposal(
        "related-brew",
        uses=[
            ProposedEvidenceUse(
                claim_id="claim-brew",
                role=EvidenceRole.SOURCE_ANCHOR,
                rationale="The source establishes the related operating context.",
            )
        ],
        statement=(
            "Select an appropriate preparation adjustment when operating conditions "
            "change."
        ),
    ).model_copy(
        update={
            "support_profile": ObjectiveSupportProfile(
                discovery_basis=ObjectiveDiscoveryBasis.SOURCE_RELATED,
                source_support_level=SourceSupportLevel.PARTIAL,
                source_relationship=(
                    "The documented procedure anchors the operating context."
                ),
                source_contributions=["The source identifies the preparation action."],
                missing_knowledge=[
                    "Criteria for choosing an adjustment under changed conditions."
                ],
                anticipated_llm_contributions=[
                    "Supply generally applicable decision criteria and qualifications."
                ],
                source_claim_ids=["claim-brew"],
            )
        }
    )
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        related_proposals=[related],
        force_partial_coverage=True,
        unwarranted_domain_indexes={0},
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    candidate = next(
        item for item in workspace.candidates if item.candidate_id == "related-brew"
    )
    assert candidate.support_profile.discovery_basis == ObjectiveDiscoveryBasis.SOURCE_RELATED
    assert candidate.support_profile.source_support_level == SourceSupportLevel.PARTIAL
    assert candidate.evidence[0].role == EvidenceRole.SOURCE_ANCHOR
    assert candidate.evidence[0].assessment_eligible is False


def test_gap_sweep_accepts_empty_domain_result_and_still_finishes_review():
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        force_partial_coverage=True,
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    record = workspace.curriculum_coverage.gap_discovery_records[0]
    assert record.warranted is True
    assert record.no_candidate_found is True
    assert record.proposed_candidate_ids == []
    operations = [call["metadata"]["operation"] for call in responses.calls]
    assert "review-objective-set-coverage-final" in operations


def test_gap_sweep_visits_each_atomic_target_once_within_one_domain():
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        force_partial_coverage=True,
        target_counts_by_domain_index={0: 2},
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    gap_calls = [
        call for call in responses.calls if call["text_format"] is CoverageGapDraft
    ]
    assert len(gap_calls) == 2
    targets = [
        json.loads(call["input"][1]["content"])["selected_gap_target"]
        for call in gap_calls
    ]
    assert len({target["target_id"] for target in targets}) == 2
    record = workspace.curriculum_coverage.gap_discovery_records[0]
    assert len(record.target_records) == 2
    assert all(item.prompt_run_ids for item in record.target_records)
    final_review = next(
        call
        for call in responses.calls
        if call["metadata"]["operation"] == "review-objective-set-coverage-final"
    )
    final_input = json.loads(final_review["input"][1]["content"])
    assert len(final_input["initial_gap_discovery"][0]["targets"]) == 2


def test_gap_alignment_retains_supporting_candidate_and_rejects_off_target():
    supporting = _proposal(
        "gap-supporting",
        statement="The learner will be able to explain a related preparation concept.",
    )
    off_target = _proposal(
        "gap-off-target",
        statement="The learner will be able to recall an adjacent source detail.",
    )
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        gap_proposals=[supporting, off_target],
        force_partial_coverage=True,
        gap_alignment_by_candidate={
            "gap-supporting": "supporting",
            "gap-off-target": "off_target",
        },
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert [candidate.candidate_id for candidate in workspace.candidates] == [
        "initial-brew",
        "gap-supporting",
    ]
    target_record = workspace.curriculum_coverage.gap_discovery_records[
        0
    ].target_records[0]
    assert target_record.direct_candidate_ids == []
    assert target_record.supporting_candidate_ids == ["gap-supporting"]
    assert [item.alignment for item in target_record.alignments] == [
        "supporting",
        "off_target",
    ]
    assert target_record.rejections[0].candidate_id == "gap-off-target"
    assert target_record.rejections[0].reason_codes == ["off_target_gap_proposal"]


def test_gap_alignment_discards_claims_outside_the_proposal():
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        gap_proposals=[_proposal("gap-brew")],
        force_partial_coverage=True,
        gap_alignment_claim_ids_by_candidate={
            "gap-brew": ["claim-brew", "claim-outside-proposal"]
        },
    )

    workspace = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    ).discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    target_record = workspace.curriculum_coverage.gap_discovery_records[
        0
    ].target_records[0]
    assert target_record.alignments[0].claim_ids_used == ["claim-brew"]
    assert target_record.direct_candidate_ids == ["gap-brew"]


def test_invalid_gap_alignment_rejects_only_its_candidate():
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        gap_proposals=[_proposal("gap-brew")],
        force_partial_coverage=True,
        gap_alignment_claim_ids_by_candidate={
            "gap-brew": ["claim-outside-proposal"]
        },
    )

    workspace = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    ).discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert [candidate.candidate_id for candidate in workspace.candidates] == [
        "initial-brew"
    ]
    target_record = workspace.curriculum_coverage.gap_discovery_records[
        0
    ].target_records[0]
    assert target_record.no_candidate_found is True
    assert target_record.rejections[0].reason_codes == ["invalid_gap_alignment"]


def test_gap_target_ids_are_stable_for_the_same_blueprint_and_performance():
    target_ids = []
    for _ in range(2):
        responses = ObjectiveResponses(
            [_proposal("initial-brew")],
            force_partial_coverage=True,
        )
        service = ObjectiveDiscoveryService(
            client=SimpleNamespace(responses=responses),
            store=WorkspaceStore(),
        )
        workspace = service.discover(
            _collection_map(), {"source-v1": _document()}, created_by="admin-1"
        )
        target_ids.append(
            workspace.curriculum_coverage.gap_discovery_records[0]
            .target_records[0]
            .target.target_id
        )

    assert target_ids[0] == target_ids[1]


def test_gap_proposal_with_wrong_target_id_fails_deterministically():
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        force_partial_coverage=True,
        wrong_gap_target_id=True,
    )
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    with pytest.raises(ValueError, match="wrong target ID"):
        service.discover(
            _collection_map(), {"source-v1": _document()}, created_by="admin-1"
        )


def test_workspace_rejects_gap_target_claim_outside_its_domain():
    responses = ObjectiveResponses(
        [_proposal("initial-brew")],
        force_partial_coverage=True,
    )
    workspace = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    ).discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )
    payload = workspace.model_dump(mode="json")
    payload["curriculum_coverage"]["gap_discovery_records"][0]["target_records"][
        0
    ]["target"]["claim_ids"] = ["claim-outside-domain"]

    with pytest.raises(ValueError, match="unknown domain claim"):
        ObjectiveWorkspace.model_validate(payload)


def test_enriched_candidate_batches_split_adaptively_until_they_fit():
    proposals = [
        _proposal("brew-adaptive"),
        _proposal(
            "soil-adaptive",
            uses=[
                ProposedEvidenceUse(
                    claim_id="claim-soil",
                    role=EvidenceRole.OBJECTIVE_DEFINING,
                    rationale="Defines the flavor-analysis behavior.",
                )
            ],
        ),
    ]

    workspace, responses = _discover(
        proposals,
        token_budget=EnrichedBatchBudget(),
    )

    assert {candidate.candidate_id for candidate in workspace.candidates} == {
        "brew-adaptive",
        "soil-adaptive",
    }
    proposal_calls = [
        call
        for call in responses.calls
        if call["text_format"] is ObjectiveProposalDraft
    ]
    assert len(proposal_calls) == 4


def test_supporting_context_survives_without_expanding_assessment_boundary():
    proposal = _proposal(
        "brew-1",
        uses=[
            ProposedEvidenceUse(
                claim_id="claim-brew",
                role=EvidenceRole.OBJECTIVE_DEFINING,
                rationale="Defines the procedure.",
            ),
            ProposedEvidenceUse(
                claim_id="claim-soil",
                role=EvidenceRole.SUPPORTING_CONTEXT,
                rationale="Can enrich the explanation of flavor.",
            ),
        ],
    )

    workspace, _ = _discover([proposal])

    evidence = workspace.candidates[0].evidence
    core = next(item for item in evidence if item.role == EvidenceRole.OBJECTIVE_DEFINING)
    context = next(item for item in evidence if item.role == EvidenceRole.SUPPORTING_CONTEXT)
    assert core.assessment_eligible is True
    assert context.assessment_eligible is False
    assert context.claim_id == "claim-soil"


def test_supporting_context_cannot_be_marked_as_assessment_evidence():
    with pytest.raises(ValueError, match="cannot expand the assessment boundary"):
        ObjectiveEvidence(
            evidence_id="evidence-1",
            claim_id="claim-soil",
            source_version_id="source-v1",
            node_ids=["source-v1-node-2"],
            role=EvidenceRole.SUPPORTING_CONTEXT,
            rationale="Flavor context",
            assessment_eligible=True,
        )


def test_source_insufficient_domain_cannot_warrant_gap_discovery():
    with pytest.raises(ValueError, match="requires sufficient evidence"):
        CurriculumGapTarget(
            target_id="target-1",
            domain_id="domain-1",
            performance="Perform unsupported work.",
            rationale="The performance would matter if it were supported.",
            claim_ids=["claim-1"],
            evidence_sufficiency="insufficient",
            sufficiency_rationale="The claim names but does not teach the work.",
            search_warranted=True,
        )


def test_source_features_are_cited_and_associated_with_candidates():
    proposal = _proposal("brew-1")
    feature = ProposedSourceFeature(
        feature_id="feature-procedure",
        feature_type="core_substance",
        status="observed",
        title="Coffee preparation steps",
        description="The source contains an ordered preparation procedure.",
        rationale="The procedure is explicit.",
        evidence_uses=[
            ProposedEvidenceUse(
                claim_id="claim-brew",
                role=EvidenceRole.OBJECTIVE_DEFINING,
                rationale="The claim contains the steps.",
            )
        ],
        candidate_ids=["brew-1"],
    )
    responses = ObjectiveResponses([proposal], [feature])
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert workspace.source_features[0].feature_id == "feature-procedure"
    assert workspace.source_features[0].evidence[0].node_ids == ["source-v1-node-1"]
    assert workspace.candidates[0].source_feature_ids == ["feature-procedure"]


def test_broad_candidates_remain_reviewable_but_unresolved_citations_are_rejected():
    proposals = [
        _proposal("unsupported-1", priority=1),
        _proposal(
            "missing-2",
            priority=2,
            uses=[
                ProposedEvidenceUse(
                    claim_id="missing-claim",
                    role=EvidenceRole.OBJECTIVE_DEFINING,
                    rationale="Missing evidence.",
                )
            ],
        ),
        _proposal("topic-3", priority=3, statement="Coffee preparation"),
    ]

    workspace, responses = _discover(proposals)

    assert [item.candidate_id for item in workspace.candidates] == [
        "unsupported-1",
        "topic-3",
    ]
    assert {item.candidate_id for item in workspace.rejected} == {"missing-2"}
    assert workspace.candidates[0].confidence == "medium"
    assert workspace.candidates[0].classification is not None
    assert workspace.candidates[0].classification.content_kind.value == "procedure"
    classification_calls = [
        call
        for call in responses.calls
        if call["text_format"] is ObjectiveClassificationDraft
    ]
    assert len(classification_calls) == 2
    assert workspace.critic_findings == {}
    operations = [call["metadata"]["operation"] for call in responses.calls]
    assert "verify-objective" not in operations
    assert "critique-objective" not in operations


def test_bloom_level_capitalization_is_normalized_deterministically():
    proposal = _proposal("brew-capitalized").model_copy(
        update={"bloom_level": "Apply"}
    )

    workspace, _ = _discover([proposal])

    assert workspace.candidates[0].bloom_level == "apply"


def test_candidate_inventory_is_uncapped_and_ranking_is_deterministic():
    proposals = [_proposal(f"candidate-{index}", priority=index) for index in range(1, 12)]
    proposals.extend(
        [
            _proposal("dup-12", priority=12),
            _proposal("dup-13", priority=13),
            _proposal("candidate-14", priority=14),
        ]
    )

    workspace, _ = _discover(proposals)

    assert len(workspace.candidates) == 14
    assert [candidate.rank for candidate in workspace.candidates] == list(range(1, 15))
    assert workspace.duplicate_groups == []
    assert workspace.rejected == []


def test_potentially_duplicate_candidates_remain_separate_and_reviewable():
    workspace, _ = _discover(
        [_proposal("dup-2", priority=1), _proposal("dup-1", priority=2)]
    )

    assert [candidate.candidate_id for candidate in workspace.candidates] == [
        "dup-2",
        "dup-1",
    ]
    assert workspace.duplicate_groups == []
    assert workspace.rejected == []


def test_multi_source_evidence_and_known_conflicts_remain_separate():
    collection_map = _collection_map(multi_source=True)
    workspace, _ = _discover(
        [_proposal("brew-multi")],
        collection_map=collection_map,
        documents={"source-v1": _document(), "source-v2": _document("source-v2")},
    )

    candidate = workspace.candidates[0]
    assert [item.source_version_id for item in candidate.evidence] == [
        "source-v1",
        "source-v2",
    ]
    assert candidate.conflicts == ["The guides specify different brew durations."]


def test_over_context_claim_map_is_proposed_in_bounded_batches():
    proposals = [
        _proposal("brew-1"),
        _proposal(
            "soil-2",
            uses=[
                ProposedEvidenceUse(
                    claim_id="claim-soil",
                    role=EvidenceRole.OBJECTIVE_DEFINING,
                    rationale="Defines a flavor-analysis objective.",
                )
            ],
            priority=2,
        ),
    ]
    responses = ObjectiveResponses(proposals)
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
        token_budget=ProposalBatchBudget(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    proposal_calls = [
        call
        for call in responses.calls
        if call["text_format"] is ObjectiveProposalDraft
    ]
    assert len(proposal_calls) == 4
    assert {candidate.candidate_id for candidate in workspace.candidates} == {
        "brew-1",
        "soil-2",
    }


def test_changed_admin_context_creates_a_new_workspace_revision():
    responses = ObjectiveResponses([_proposal("brew-1")])
    store = WorkspaceStore()
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=store,
    )
    collection_map = _collection_map()
    documents = {"source-v1": _document()}

    first = service.discover(
        collection_map,
        documents,
        workspace_id="workspace-1",
        created_by="admin-1",
    )
    second = service.discover(
        collection_map,
        documents,
        instructions=PractitionerInstructions(roles=["Hospitality lead"]),
        workspace_id="workspace-1",
        created_by="admin-1",
    )

    assert first.revision == 1
    assert second.revision == 2
    assert second.learning_brief.instructions.roles == ["Hospitality lead"]


def test_initial_discovery_does_not_invoke_the_evidence_verification_gate():
    responses = ObjectiveResponses([_proposal("brew-wide")])
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=WorkspaceStore(),
        token_budget=VerificationBudget(),
    )

    workspace = service.discover(
        _collection_map(), {"source-v1": _document()}, created_by="admin-1"
    )

    assert workspace.rejected == []
    assert workspace.candidates[0].candidate_id == "brew-wide"
    assert workspace.candidates[0].confidence == "medium"
    assert workspace.critic_findings == {}
    operations = [call["metadata"]["operation"] for call in responses.calls]
    assert "verify-objective" not in operations
