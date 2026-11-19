from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError
from rlo_schema import Evidence, Source

from src.source_authoring.authoring_contracts import (
    AuthoringAssessment,
    AuthoringAssessmentOption,
    AuthoringClaim,
    AuthoringElement,
    AuthoringElementType,
    AuthoringObjective,
    AuthoringPart,
    AuthoringRLORevision,
    ClaimKnowledgeOrigin,
    ClaimVerificationStatus,
    ClassificationDecision,
    ElementOrigin,
    GenerationProvenance,
    GuidanceAssessment,
    LLMKnowledgeProvenance,
    PartStatus,
    RLOClassifications,
    RLOPartKind,
)
from src.source_authoring.catalog_adapter import adapt_authoring_rlo
from src.source_authoring.draft_contracts import summarize_content_provenance
from src.source_authoring.methodology import PROFILES, get_methodology_profile


def _revision() -> AuthoringRLORevision:
    excerpt = "Press the brew button after inserting the capsule."
    source = Source(
        id="src-01",
        title="Coffee machine manual",
        reference="coffee-manual.pdf",
        authority="primary",
        ingested_source_id="source-1",
        source_version_id="source-v1",
        checksum="1" * 64,
    )
    evidence = Evidence(
        id="ev-01",
        source_ref="src-01",
        source_version_id="source-v1",
        node_ids=["node-1"],
        locator="page 1",
        role="objective_defining",
        excerpt=excerpt,
        excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
    )
    target = ClassificationDecision(
        content_type="procedure",
        bloom_level="apply",
        confidence="high",
        rationale="The learner executes documented steps.",
    )
    profile = get_methodology_profile("procedure", "apply")
    requirement_by_part = {
        part: [
            item.requirement_id for item in profile.requirements if item.part == part
        ]
        for part in RLOPartKind
    }
    claim = AuthoringClaim(
        claim_id="claim-01",
        statement=excerpt,
        evidence_refs=["ev-01"],
        role="objective_defining",
        assessment_eligible=True,
        requirement_refs=requirement_by_part[RLOPartKind.TEACH],
    )

    def text_element(element_id, element_type, content, *, generated=False):
        return AuthoringElement(
            element_id=element_id,
            element_type=element_type,
            content=content,
            origin=ElementOrigin.GENERATED if generated else ElementOrigin.SOURCE,
            claim_refs=["claim-01"],
            evidence_refs=["ev-01"],
            generation_note="Instructional framing generated from claim-01."
            if generated
            else None,
        )

    parts = [
        AuthoringPart(
            kind="cover",
            ordinal=1,
            status="complete",
            requirement_refs=requirement_by_part[RLOPartKind.COVER],
            elements=[
                AuthoringElement(
                    element_id="cover-01",
                    element_type="metadata",
                    content={"title": "Prepare coffee"},
                    origin="source",
                )
            ],
        ),
        AuthoringPart(
            kind="setup",
            ordinal=2,
            status="complete",
            requirement_refs=requirement_by_part[RLOPartKind.SETUP],
            elements=[text_element("setup-01", "hook", "A colleague needs coffee.", generated=True)],
        ),
        AuthoringPart(
            kind="teach",
            ordinal=3,
            status="complete",
            requirement_refs=requirement_by_part[RLOPartKind.TEACH],
            elements=[text_element("teach-01", "step", excerpt)],
        ),
        AuthoringPart(
            kind="show",
            ordinal=4,
            status="complete",
            requirement_refs=requirement_by_part[RLOPartKind.SHOW],
            elements=[text_element("show-01", "worked_example", "Insert, then press.", generated=True)],
        ),
        AuthoringPart(
            kind="practice",
            ordinal=5,
            status="complete",
            requirement_refs=requirement_by_part[RLOPartKind.PRACTICE],
            elements=[
                AuthoringElement(
                    element_id="practice-01",
                    element_type="practice_item",
                    assessment=AuthoringAssessment(
                        stem="What should you do after inserting the capsule?",
                        type="multiple_choice_single",
                        options=[
                            AuthoringAssessmentOption(
                                text="Press the brew button",
                                correct=True,
                                feedback="Correct; this follows the documented sequence.",
                                claim_refs=["claim-01"],
                            ),
                            AuthoringAssessmentOption(
                                text="Remove the capsule",
                                correct=False,
                                feedback="No; press the brew button next.",
                                claim_refs=["claim-01"],
                            ),
                        ],
                        claim_refs=["claim-01"],
                    ),
                    origin="generated",
                    claim_refs=["claim-01"],
                    evidence_refs=["ev-01"],
                    generation_note="Practice wording generated from the documented sequence.",
                )
            ],
        ),
        AuthoringPart(
            kind="check",
            ordinal=6,
            status="complete",
            requirement_refs=requirement_by_part[RLOPartKind.CHECK],
            elements=[
                AuthoringElement(
                    element_id="check-01",
                    element_type="assessment_item",
                    assessment=AuthoringAssessment(
                        stem="Select the next action after inserting the capsule.",
                        type="multiple_choice_single",
                        options=[
                            AuthoringAssessmentOption(
                                text="Press the brew button",
                                correct=True,
                                feedback="Correct.",
                                claim_refs=["claim-01"],
                            ),
                            AuthoringAssessmentOption(
                                text="Remove the capsule",
                                correct=False,
                                feedback="Review the documented sequence.",
                                claim_refs=["claim-01"],
                            ),
                        ],
                        claim_refs=["claim-01"],
                    ),
                    origin="generated",
                    claim_refs=["claim-01"],
                    evidence_refs=["ev-01"],
                    generation_note="Assessment wording generated from claim-01.",
                )
            ],
        ),
        AuthoringPart(
            kind="send_off",
            ordinal=7,
            status="complete",
            requirement_refs=requirement_by_part[RLOPartKind.SEND_OFF],
            elements=[text_element("send-01", "transfer_prompt", "Recall the sequence at the machine.", generated=True)],
        ),
    ]
    return AuthoringRLORevision(
        rlo_id="rlo-coffee-01",
        version="0.1.0",
        revision=1,
        title="Prepare coffee",
        topic="Coffee preparation",
        domain="Workplace skills",
        estimated_duration_minutes=5,
        objective=AuthoringObjective(
            candidate_id="candidate-1",
            statement="Prepare coffee using the documented machine sequence.",
            performance_context="At an available office coffee machine.",
            evidence_refs=["ev-01"],
        ),
        classifications=RLOClassifications(target=target),
        methodology_profile=profile,
        sources=[source],
        evidence=[evidence],
        claims=[claim],
        parts=parts,
        provenance=GenerationProvenance(
            rules_version="2026-09-03",
            authoring_schema_version="source-rlo-authoring-v1",
            methodology_profile_id=profile.profile_id,
            methodology_profile_version=profile.version,
        ),
        authoring_revision_id="authoring-rlo-coffee-01-r1",
    )


def test_five_poc2_methodology_cells_are_explicit():
    assert len(PROFILES) == 5
    assert {profile.profile_id for profile in PROFILES.values()} == {
        "fact-remember",
        "concept-understand",
        "concept-apply",
        "process-understand",
        "procedure-apply",
    }
    for profile in PROFILES.values():
        assert profile.version == "poc2-five-cell-guidance-2026-09-15-v1"
        assert profile.intent
        assert profile.avoid
        assert profile.review_dimensions
        assert {item.part for item in profile.guidance} == {
            RLOPartKind.SETUP,
            RLOPartKind.TEACH,
            RLOPartKind.SHOW,
            RLOPartKind.PRACTICE,
            RLOPartKind.CHECK,
        }
        assert len({item.guidance_id for item in profile.guidance}) == len(
            profile.guidance
        )
    with pytest.raises(ValueError, match="unsupported RLO classification cell"):
        get_methodology_profile("fact", "apply")


def test_guidance_references_must_belong_to_the_selected_profile():
    revision = _revision()
    raw = revision.model_dump(mode="json")
    raw["parts"][1]["elements"][0]["guidance_refs"] = ["unknown-guidance"]

    with pytest.raises(ValidationError, match="unknown guidance"):
        AuthoringRLORevision.model_validate(raw)

    raw = revision.model_dump(mode="json")
    raw["guidance_assessments"] = [
        GuidanceAssessment(
            guidance_id="unknown-guidance",
            status="missed",
            explanation="The guidance was not addressed.",
        ).model_dump(mode="json")
    ]
    with pytest.raises(ValidationError, match="unknown guidance"):
        AuthoringRLORevision.model_validate(raw)


def test_authoring_revision_requires_canonical_part_order():
    revision = _revision()
    raw = revision.model_dump(mode="json")
    raw["parts"][1], raw["parts"][2] = raw["parts"][2], raw["parts"][1]

    with pytest.raises(ValidationError, match="canonical order"):
        AuthoringRLORevision.model_validate(raw)


def test_supporting_context_cannot_define_assessment_answer():
    revision = _revision()
    raw = revision.model_dump(mode="json")
    raw["claims"][0]["role"] = "supporting_context"

    with pytest.raises(ValidationError, match="supporting context"):
        AuthoringRLORevision.model_validate(raw)


def test_model_domain_claim_requires_model_provenance_not_source_evidence():
    revision = _revision()
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
    claim = AuthoringClaim(
        claim_id="claim-llm-1",
        statement="A changed condition can require a different response.",
        knowledge_origin=ClaimKnowledgeOrigin.LLM_DOMAIN,
        verification_status=ClaimVerificationStatus.UNVERIFIED,
        llm_provenance_ref=provenance.provenance_id,
        origin_rationale="General model knowledge added to fill a declared gap.",
        role="objective_defining",
        assessment_eligible=True,
    )
    enriched = revision.model_copy(
        update={
            "claims": [*revision.claims, claim],
            "llm_knowledge_provenance": [provenance],
        }
    )

    assert AuthoringRLORevision.model_validate(enriched).claims[-1] == claim

    raw = claim.model_dump(mode="json")
    raw["evidence_refs"] = ["ev-01"]
    with pytest.raises(ValidationError, match="cannot claim source evidence"):
        AuthoringClaim.model_validate(raw)


def test_content_provenance_summary_separates_origins_and_llm_assessments():
    revision = _revision()
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
    synthesis = AuthoringClaim(
        claim_id="claim-synthesis",
        statement="The documented action forms a repeatable preparation step.",
        evidence_refs=["ev-01"],
        source_claim_refs=["claim-01"],
        knowledge_origin="source_synthesis",
        origin_rationale="Restates the documented action as a reusable step.",
        role="objective_defining",
        assessment_eligible=True,
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
    raw = revision.model_dump(mode="json")
    raw["claims"].extend(
        [
            synthesis.model_dump(mode="json"),
            llm_claim.model_dump(mode="json"),
        ]
    )
    raw["llm_knowledge_provenance"] = [provenance.model_dump(mode="json")]
    raw["parts"][4]["elements"][0]["claim_refs"].append("claim-llm")
    enriched = AuthoringRLORevision.model_validate(raw)

    summary = summarize_content_provenance(enriched)

    assert summary.source_supported_claims == 1
    assert summary.source_synthesis_claims == 1
    assert summary.llm_domain_claims == 1
    assert summary.llm_backed_assessment_ids == ["practice-01"]
    assert summary.llm_provenance_records == 1


def test_adapter_builds_catalog_rlo_without_terminal_objective():
    authoring = _revision()

    catalog = adapt_authoring_rlo(authoring)

    assert catalog.terminal_objective is None
    assert catalog.authoring_revision_id == authoring.authoring_revision_id
    assert catalog.enabling_objective.statement == authoring.objective.statement
    assert catalog.content_type.value == "procedure"
    assert catalog.assessment_items[0].evidence_refs == ["ev-01"]
    assert catalog.gagne_event_mapping.event_4_present_content


def test_adapter_excludes_supporting_context_from_objective_evidence():
    authoring = _revision()
    excerpt = "Coffee origin may affect flavor."
    context_evidence = Evidence(
        id="ev-context",
        source_ref="src-01",
        source_version_id="source-v1",
        node_ids=["node-context"],
        locator="page 2",
        role="supporting_context",
        excerpt=excerpt,
        excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
    )
    context_claim = AuthoringClaim(
        claim_id="claim-context",
        statement=excerpt,
        evidence_refs=[context_evidence.id],
        role="supporting_context",
        assessment_eligible=False,
    )
    authoring = authoring.model_copy(
        update={
            "evidence": [*authoring.evidence, context_evidence],
            "claims": [*authoring.claims, context_claim],
            "objective": authoring.objective.model_copy(
                update={"evidence_refs": ["ev-01", context_evidence.id]}
            ),
        }
    )

    catalog = adapt_authoring_rlo(authoring)

    assert catalog.enabling_objective.evidence_refs == ["ev-01"]


def test_source_insufficient_revision_is_not_publishable():
    revision = _revision()
    raw = revision.model_dump(mode="json")
    raw["parts"][2]["status"] = PartStatus.SOURCE_INSUFFICIENT
    authoring = AuthoringRLORevision.model_validate(raw)

    with pytest.raises(ValueError, match="source-insufficient"):
        adapt_authoring_rlo(authoring)
