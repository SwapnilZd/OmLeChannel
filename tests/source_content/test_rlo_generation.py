from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from src.source_authoring.authoring_contracts import (
    AuthoringAssessmentOption,
    AuthoringFinding,
    ClassificationDecision,
    GuidanceAssessment,
    RLOPartKind,
)
from src.source_authoring.draft_contracts import (
    RLODraftJob,
    RLODraftRequest,
    RLODraftState,
    RLOGenerationCheckpoint,
)
from src.source_authoring.generation import (
    AUTHORING_GUIDANCE_POLICY,
    ENRICHMENT_PROMPT,
    EvidenceContextError,
    MAPPING_PROMPT,
    PEDAGOGY_PROMPT,
    PRACTICE_CHECK_PROMPT,
    REPAIR_PROMPT,
    RLOGenerationService,
    SENDOFF_PROMPT,
    SETUP_PROMPT,
    TEACH_SHOW_PROMPT,
)
from src.source_authoring.generation_contracts import (
    AuthoringReviewDraft,
    CollectionReviewDraft,
    GeneratedAssessment,
    GeneratedElementDraft,
    LLMEnrichmentClaimDraft,
    LLMEnrichmentDraft,
    MappingChallengeDraft,
    MappedClaimDraft,
    NodeCitationDraft,
    PartGenerationDraft,
    RequirementCoverageDraft,
    SourceMapDraft,
    TargetPlanDraft,
)
from src.source_authoring.methodology import get_methodology_profile
from src.source_ingestion.segmentation import SourceTokenBudget

from .test_rlo_drafting import _material, _workspace


def test_part_generation_schema_is_compatible_with_strict_structured_outputs():
    schema = to_strict_json_schema(PartGenerationDraft)

    def assert_closed_objects(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
            for child in value.values():
                assert_closed_objects(child)
        elif isinstance(value, list):
            for child in value:
                assert_closed_objects(child)

    assert_closed_objects(schema)


def test_generated_assessments_reject_open_response():
    with pytest.raises(ValidationError):
        GeneratedAssessment(
            stem="Explain your answer.",
            type="open_response",
            correct_response="A complete explanation.",
            scoring_criteria="Score the explanation.",
            feedback_guidance="Respond to omissions.",
            claim_refs=["claim-1"],
        )


def test_practice_check_prompt_requires_closed_responses():
    assert PRACTICE_CHECK_PROMPT.version == "v11"
    assert "automatically evaluable learner response" in PRACTICE_CHECK_PROMPT.text
    assert "Do not generate open-response questions" in PRACTICE_CHECK_PROMPT.text
    assert "approved performance to terminology recall" in (
        PRACTICE_CHECK_PROMPT.text
    )


def test_final_review_and_repair_enforce_plain_language_cohesion():
    assert MAPPING_PROMPT.version == "v6"
    assert "claims about instructional design" in MAPPING_PROMPT.text
    assert ENRICHMENT_PROMPT.version == "v3"
    assert "only an illustrative" in ENRICHMENT_PROMPT.text
    assert PEDAGOGY_PROMPT.version == "v11"
    assert "plain, direct language" in PEDAGOGY_PROMPT.text
    assert "Do not use em dashes" in PEDAGOGY_PROMPT.text
    assert "`repairable: true`" in PEDAGOGY_PROMPT.text
    assert "free-text learner request" in PEDAGOGY_PROMPT.text
    assert "selection of a complete supported" in PEDAGOGY_PROMPT.text
    assert REPAIR_PROMPT.version == "v10"
    assert "plain, direct language" in REPAIR_PROMPT.text
    assert "Do not use em dashes" in REPAIR_PROMPT.text
    assert "Replace any open-response or free-text learner question" in REPAIR_PROMPT.text
    assert "populate `assessment`" in REPAIR_PROMPT.text
    assert "may use only claims whose role is `objective_defining`" in REPAIR_PROMPT.text


def test_authoring_prompts_require_grounded_practitioner_engagement():
    assert AUTHORING_GUIDANCE_POLICY.version == "v1"
    assert "prioritized creative brief" in AUTHORING_GUIDANCE_POLICY.text
    assert "not as an exhaustive compliance checklist" in AUTHORING_GUIDANCE_POLICY.text
    assert SETUP_PROMPT.version == "v7"
    assert "recognizable work moment" in SETUP_PROMPT.text
    assert "generic openings" in SETUP_PROMPT.text
    assert TEACH_SHOW_PROMPT.version == "v7"
    assert "clear decision point" in TEACH_SHOW_PROMPT.text
    assert "expert judgment" in TEACH_SHOW_PROMPT.text
    assert "useful coaching" in PRACTICE_CHECK_PROMPT.text
    assert "plausible misreadings" in PRACTICE_CHECK_PROMPT.text
    assert SENDOFF_PROMPT.version == "v6"
    assert "one specific cue" in SENDOFF_PROMPT.text
    assert "Do not flatten effective learner-facing content" in REPAIR_PROMPT.text
    for prompt in (SETUP_PROMPT, TEACH_SHOW_PROMPT, PRACTICE_CHECK_PROMPT, SENDOFF_PROMPT):
        assert AUTHORING_GUIDANCE_POLICY.text in prompt.text


def test_generation_filters_closed_response_and_guidance_only_findings():
    findings = [
        AuthoringFinding(
            code="INVALID-OWN-TERMS",
            severity="error",
            category="pedagogy",
            path="parts.check",
            message="Require the learner to answer in their own terms.",
            repairable=True,
        ),
        AuthoringFinding(
            code="INVALID-OWN-WORDS",
            severity="warning",
            category="pedagogy",
            path="parts.check",
            message="The check does not require an own-words explanation.",
            repairable=True,
        ),
        AuthoringFinding(
            code="INVALID-PREFERRED-SHAPE",
            severity="warning",
            category="pedagogy",
            path="parts.practice",
            message="The practice does not use three attempts as the preferred shape.",
            repairable=True,
        ),
        AuthoringFinding(
            code="VALID-CHECK-ISSUE",
            severity="error",
            category="pedagogy",
            path="parts.check",
            message="The Check repeats the Practice item.",
            repairable=True,
        ),
    ]

    assert [
        finding.code
        for finding in RLOGenerationService._admissible_pedagogy_findings(findings)
    ] == ["VALID-CHECK-ISSUE"]


def test_enrichment_supporting_context_is_deterministically_non_assessable():
    claim = LLMEnrichmentClaimDraft(
        local_ref="llm-001",
        statement="A supporting detail.",
        role="supporting_context",
        assessment_eligible=True,
        origin_rationale="Supplies useful context for the objective.",
    )

    assert claim.assessment_eligible is False


def test_generated_assessment_drops_supporting_context_references():
    assessment = GeneratedAssessment(
        stem="Which recommendation is adequately supported?",
        type="multiple_choice_single",
        options=[
            AuthoringAssessmentOption(
                text="The supported recommendation",
                correct=True,
                feedback="This uses the decision criterion.",
                claim_refs=["eligible", "context"],
            ),
            AuthoringAssessmentOption(
                text="An unsupported recommendation",
                correct=False,
                feedback="This relies only on context.",
                claim_refs=["context"],
            ),
        ],
        claim_refs=["eligible", "context"],
    )

    normalized = RLOGenerationService._assessment_with_eligible_claims(
        assessment,
        {
            "eligible": SimpleNamespace(assessment_eligible=True),
            "context": SimpleNamespace(assessment_eligible=False),
        },
    )

    assert normalized.claim_refs == ["eligible"]
    assert normalized.options[0].claim_refs == ["eligible"]
    assert normalized.options[1].claim_refs == []


def test_guidance_review_discards_unknown_and_duplicate_model_results():
    profile = get_methodology_profile("procedure", "apply")
    guidance_id = profile.guidance[0].guidance_id
    assessments = [
        GuidanceAssessment(
            guidance_id="unknown-guidance",
            status="missed",
            explanation="Unknown output should not invalidate the RLO.",
        ),
        GuidanceAssessment(
            guidance_id=guidance_id,
            status="approximated",
            explanation="Useful treatment — with lower fidelity.",
        ),
        GuidanceAssessment(
            guidance_id=guidance_id,
            status="missed",
            explanation="Duplicate output should be ignored.",
        ),
    ]

    admitted = RLOGenerationService._admissible_guidance_assessments(
        profile, assessments
    )

    assert [item.guidance_id for item in admitted] == [guidance_id]
    assert admitted[0].status == "approximated"
    assert admitted[0].explanation == "Useful treatment — with lower fidelity."


class MemoryGenerationStore:
    def __init__(self, job, material):
        self.job = job
        self.material = material
        self.checkpoints = {}
        self.prompt_runs = []
        self.batch_state = "running"
        self.batch_finalized = False
        self.batch_findings = []

    def get_draft_job(self, _job_id):
        return self.job

    def load_collection_source_materials(self, _collection_id):
        return [self.material]

    def list_generation_checkpoints(self, _job_id):
        return sorted(self.checkpoints.values(), key=lambda item: item.sequence)

    def save_generation_checkpoint(self, job_id, **kwargs):
        checkpoint = RLOGenerationCheckpoint(
            job_id=job_id,
            created_at="2026-09-03T12:00:00+00:00",
            **kwargs,
        )
        self.checkpoints[checkpoint.operation] = checkpoint
        return checkpoint

    def record_generation_prompt_run(self, run):
        self.prompt_runs.append(run)

    def update_draft_job_progress(self, _job_id, *, state, operation, completed_operations):
        self.job = self.job.model_copy(
            update={
                "state": state,
                "current_operation": operation,
                "completed_operations": completed_operations,
            }
        )
        return self.job

    def save_draft_job(self, job, *, expected_state, save_revision=False):
        assert self.job.state == expected_state
        self.job = job
        return job

    def refresh_generation_batch(self, _batch_id):
        return SimpleNamespace(state=self.batch_state)

    def get_generation_batch(self, _batch_id):
        return SimpleNamespace(
            finalized=self.batch_finalized,
            state=self.batch_state,
        )

    def list_draft_jobs(self, *, batch_id):
        assert batch_id == self.job.batch_id
        return [self.job]

    def complete_collection_validation(self, _batch_id, findings):
        self.batch_findings = findings


class FakeGenerationResponses:
    def __init__(
        self,
        *,
        source_insufficient=False,
        incomplete_mapping=False,
        repair_once=False,
        persistent_mismatch=False,
        invalid_repair_output=False,
        invalid_repair_claim=False,
        second_repair_required=False,
        missed_guidance=False,
    ):
        self.source_insufficient = source_insufficient
        self.incomplete_mapping = incomplete_mapping
        self.repair_once = repair_once
        self.persistent_mismatch = persistent_mismatch
        self.invalid_repair_output = invalid_repair_output
        self.invalid_repair_claim = invalid_repair_claim
        self.second_repair_required = second_repair_required
        self.missed_guidance = missed_guidance
        self.grounding_calls = 0
        self.calls = 0
        self.payloads = {}

    def parse(self, **kwargs):
        self.calls += 1
        operation = kwargs["metadata"]["operation"]
        payload = json.loads(kwargs["input"][1]["content"])
        self.payloads[operation] = payload
        profile = get_methodology_profile("procedure", "apply")
        if operation == "target-classification":
            parsed = TargetPlanDraft(
                classification=ClassificationDecision(
                    content_type="procedure",
                    bloom_level="apply",
                    confidence="high",
                    rationale="The learner executes a documented single-actor sequence.",
                )
            )
        elif operation == "source-mapping-challenge":
            parsed = MappingChallengeDraft()
        elif operation.startswith("source-mapping-"):
            segment = payload["source_segments"][0]
            claim = MappedClaimDraft(
                local_ref="brew",
                statement="Press the brew button to prepare coffee.",
                citations=[
                    NodeCitationDraft(
                        source_version_id="source-v1",
                        segment_ids=[segment["segment_id"]],
                    )
                ],
                role="objective_defining",
                assessment_eligible=True,
                requirement_refs=[item.requirement_id for item in profile.requirements],
            )
            claims = [claim]
            if self.invalid_repair_claim:
                claims.append(
                    MappedClaimDraft(
                        local_ref="context",
                        statement="Coffee is available in the office.",
                        citations=[
                            NodeCitationDraft(
                                source_version_id="source-v1",
                                segment_ids=[segment["segment_id"]],
                            )
                        ],
                        role="supporting_context",
                        assessment_eligible=False,
                    )
                )
            parsed = SourceMapDraft(
                claims=claims,
                coverage=[
                    RequirementCoverageDraft(
                        requirement_id=item.requirement_id,
                        status="partial" if self.incomplete_mapping else "complete",
                        claim_refs=["brew"],
                    )
                    for item in profile.requirements
                ],
            )
        elif operation == "llm-domain-enrichment":
            parsed = LLMEnrichmentDraft(
                claims=[
                    LLMEnrichmentClaimDraft(
                        local_ref="operating-context",
                        statement=(
                            "A changed operating condition can require selecting a "
                            "different preparation response."
                        ),
                        role="objective_defining",
                        assessment_eligible=True,
                        requirement_refs=[
                            item["requirement_id"]
                            for item in payload["missing_requirements"]
                        ],
                        origin_rationale=(
                            "This generally applicable decision principle is model "
                            "knowledge, not a statement attributed to the source."
                        ),
                    )
                ]
            )
        elif operation == "generate-practice-check":
            claim_ref = "claim-map-0001"
            from src.source_authoring.authoring_contracts import (
                AuthoringAssessmentOption,
            )

            assessment = GeneratedAssessment(
                stem="What action prepares the coffee?",
                type="multiple_choice_single",
                options=[
                    AuthoringAssessmentOption(
                        text="Press the brew button",
                        correct=True,
                        feedback="Correct; the source directs this action.",
                        claim_refs=[claim_ref],
                    ),
                    AuthoringAssessmentOption(
                        text="Wait without pressing it",
                        correct=False,
                        feedback="No; press the brew button.",
                        claim_refs=[claim_ref],
                    ),
                ],
                claim_refs=[claim_ref],
            )
            by_part = {
                part: [
                    item.requirement_id for item in profile.requirements if item.part == part
                ]
                for part in RLOPartKind
            }
            parsed = PartGenerationDraft(
                elements=[
                    GeneratedElementDraft(
                        part="practice",
                        element_type="practice_item",
                        assessment=assessment,
                        claim_refs=[claim_ref],
                        requirement_refs=by_part[RLOPartKind.PRACTICE],
                        guidance_refs=[
                            item.guidance_id
                            for item in profile.guidance_for(RLOPartKind.PRACTICE)
                        ],
                        generation_note="Practice wording generated from the supported action.",
                    ),
                    GeneratedElementDraft(
                        part="check",
                        element_type="assessment_item",
                        assessment=assessment,
                        claim_refs=[claim_ref],
                        requirement_refs=by_part[RLOPartKind.CHECK],
                        guidance_refs=[
                            item.guidance_id
                            for item in profile.guidance_for(RLOPartKind.CHECK)
                        ],
                        generation_note="Check wording generated from the supported action.",
                    ),
                ]
            )
        elif operation == "generate-teach-show" and self.source_insufficient:
            parsed = PartGenerationDraft(
                source_insufficient=True,
                insufficiency_reason="The source does not support the required teaching substance.",
            )
        elif operation == "generate-teach-show":
            by_part = {
                part: [
                    item.requirement_id
                    for item in profile.requirements
                    if item.part == part
                ]
                for part in RLOPartKind
            }
            parsed = PartGenerationDraft(
                elements=[
                    GeneratedElementDraft(
                        part="teach",
                        element_type="explanation",
                        content="Pressing the brew button starts the supported coffee preparation action.",
                        claim_refs=["claim-map-0001"],
                        requirement_refs=by_part[RLOPartKind.TEACH],
                        guidance_refs=[
                            item.guidance_id
                            for item in profile.guidance_for(RLOPartKind.TEACH)
                        ],
                        generation_note="Organized the supported action as learner-facing instruction.",
                    ),
                    GeneratedElementDraft(
                        part="show",
                        element_type="worked_example",
                        content="A practitioner prepares coffee by pressing the brew button.",
                        claim_refs=["claim-map-0001"],
                        requirement_refs=by_part[RLOPartKind.SHOW],
                        guidance_refs=[
                            item.guidance_id
                            for item in profile.guidance_for(RLOPartKind.SHOW)
                        ],
                        generation_note="Presented the supported action in a simple example.",
                    ),
                ]
            )
        elif operation.startswith("generate-"):
            parsed = PartGenerationDraft()
        elif operation.startswith("validate-grounding"):
            self.grounding_calls += 1
            parsed = AuthoringReviewDraft(
                findings=[
                    AuthoringFinding(
                        code="worked_example_clarity",
                        severity="error",
                        category="grounding",
                        path="parts.show",
                        message="The worked example needs a clearer supported action.",
                        repairable=True,
                    )
                ]
                if (
                    self.repair_once
                    and (
                        self.grounding_calls == 1
                        or self.second_repair_required
                        and self.grounding_calls == 2
                    )
                )
                else []
            )
        elif operation.startswith("validate-provenance"):
            parsed = AuthoringReviewDraft()
        elif operation == "validate-pedagogy":
            parsed = AuthoringReviewDraft(
                observed_classification=ClassificationDecision(
                    content_type="concept" if self.persistent_mismatch else "procedure",
                    bloom_level="understand" if self.persistent_mismatch else "apply",
                    confidence="high",
                    rationale="Practice and Check require executing the supported action.",
                ),
                guidance_assessments=[
                    GuidanceAssessment(
                        guidance_id=item.guidance_id,
                        status=(
                            "missed"
                            if self.missed_guidance and index == 0
                            else "achieved"
                        ),
                        explanation="The RLO addresses this guidance coherently.",
                        affected_paths=[f"parts.{item.part.value}"],
                    )
                    for index, item in enumerate(profile.guidance)
                ],
            )
        elif operation.startswith("validate-pedagogy-after-repair"):
            parsed = AuthoringReviewDraft(
                observed_classification=ClassificationDecision(
                    content_type="concept" if self.persistent_mismatch else "procedure",
                    bloom_level="understand" if self.persistent_mismatch else "apply",
                    confidence="high",
                    rationale="The repaired RLO remains aligned.",
                ),
                guidance_assessments=[
                    GuidanceAssessment(
                        guidance_id=item.guidance_id,
                        status="achieved",
                        explanation="The repaired RLO addresses this guidance.",
                        affected_paths=[f"parts.{item.part.value}"],
                    )
                    for item in profile.guidance
                ],
            )
        elif operation.startswith("targeted-repair"):
            if self.invalid_repair_output and operation == "targeted-repair":
                PartGenerationDraft.model_validate(
                    {
                        "elements": [
                            {
                                "part": "practice",
                                "element_type": "practice_item",
                                "content": "This is not a valid practice assessment.",
                                "claim_refs": ["claim-map-0001"],
                                "generation_note": "Invalid repair fixture.",
                            }
                        ]
                    }
                )
            if self.invalid_repair_claim:
                from src.source_authoring.authoring_contracts import (
                    AuthoringAssessmentOption,
                )

                assessment = GeneratedAssessment(
                    stem="Which context is correct?",
                    type="multiple_choice_single",
                    options=[
                        AuthoringAssessmentOption(
                            text="Coffee is available",
                            correct=True,
                            feedback="Correct.",
                            claim_refs=["claim-map-0002"],
                        ),
                        AuthoringAssessmentOption(
                            text="Coffee is unavailable",
                            correct=False,
                            feedback="Incorrect.",
                            claim_refs=["claim-map-0002"],
                        ),
                    ],
                    claim_refs=["claim-map-0002"],
                )
                parsed = PartGenerationDraft(
                    elements=[
                        GeneratedElementDraft(
                            part="practice",
                            element_type="practice_item",
                            assessment=assessment,
                            claim_refs=["claim-map-0002"],
                            requirement_refs=["procedure-apply-practice-performance"],
                            generation_note="Invalid supporting-context assessment fixture.",
                        )
                    ]
                )
                return SimpleNamespace(
                    output_parsed=parsed,
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=5,
                        total_tokens=15,
                    ),
                )
            parsed = PartGenerationDraft(
                elements=[
                    GeneratedElementDraft(
                        part="show",
                        element_type="worked_example",
                        content="The practitioner inserts the capsule, then presses brew.",
                        claim_refs=["claim-map-0001"],
                        requirement_refs=["procedure-apply-show-case"],
                        generation_note="Clarified the supported action sequence.",
                        replace_element_id="source-procedure-apply-show-case",
                    )
                ]
            )
        elif operation.startswith("collection-validation-"):
            parsed = CollectionReviewDraft()
        else:
            raise AssertionError(operation)
        return SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def test_generation_builds_reviewable_seven_part_rlo(monkeypatch):
    workspace = _workspace()
    job = RLODraftJob(
        job_id="generation-job-1",
        batch_id="batch-1",
        objective_job_id="objective-job-1",
        state=RLODraftState.PLANNING,
        request=RLODraftRequest(
            workspace_id=workspace.workspace_id,
            workspace_revision=workspace.revision,
            candidate_id=workspace.candidates[0].candidate_id,
            rlo_id="rlo-coffee-generated",
            rlo_version="0.1.0",
        ),
        attempt=1,
    )
    store = MemoryGenerationStore(job, _material())
    store.batch_state = "in_review"
    store.batch_finalized = True
    monkeypatch.setattr(
        "src.source_authoring.generation.repository.get_objective_workspace",
        lambda *_args: workspace,
    )
    responses = FakeGenerationResponses()
    service = RLOGenerationService(
        client=SimpleNamespace(responses=responses), store=store
    )

    result = service.process(job.job_id)

    assert result.state == RLODraftState.IN_REVIEW
    assert result.authoring is not None
    assert [part.kind.value for part in result.authoring.parts] == [
        "cover",
        "setup",
        "teach",
        "show",
        "practice",
        "check",
        "send_off",
    ]
    assert result.draft.authoring_revision_id == result.authoring.authoring_revision_id
    assert result.draft.terminal_objective is None
    assert result.draft.assessment_items
    assert len(result.authoring.guidance_assessments) == len(
        result.authoring.methodology_profile.guidance
    )
    assert all(
        assessment.status == "achieved"
        for assessment in result.authoring.guidance_assessments
    )
    for part_name in ("practice", "check"):
        part = next(part for part in result.authoring.parts if part.kind == part_name)
        assert part.elements[0].origin.value == "mixed"
    assert len(store.prompt_runs) == len(store.checkpoints) - 1
    assert all(run.prompt_snapshot for run in store.prompt_runs)
    mapped_segment = responses.payloads["source-mapping-0001"]["source_segments"][0]
    assert mapped_segment["segment_id"]
    assert mapped_segment["text"] == "Press the brew button to prepare coffee."
    assert "guidance" not in responses.payloads["source-mapping-0001"][
        "methodology_profile"
    ]
    assert "guidance" not in responses.payloads["source-mapping-challenge"][
        "methodology_profile"
    ]
    assert responses.payloads["source-mapping-challenge"]["evidence"]
    assert all(
        responses.payloads[operation]["evidence"]
        for operation in (
            "generate-teach-show",
            "generate-practice-check",
            "generate-setup",
            "generate-sendoff",
        )
    )
    assert all(
        responses.payloads[operation]["generation_policy_sha256"]
        for operation in (
            "generate-teach-show",
            "generate-practice-check",
            "generate-setup",
            "generate-sendoff",
        )
    )
    validation_evidence = responses.payloads["validate-grounding"]["authoring"][
        "evidence"
    ]
    assert all(item["segment_ids"] for item in validation_evidence)
    instructional_foundation = responses.payloads["generate-practice-check"][
        "assembled_rlo_context"
    ]
    assert any(
        element["content"].startswith("Pressing the brew button")
        for element in instructional_foundation["teach"]
    )
    assert any(
        element["content"].startswith("A practitioner prepares coffee")
        for element in instructional_foundation["show"]
    )
    generation_operations = [
        run.operation for run in store.prompt_runs if run.operation.startswith("generate-")
    ]
    assert generation_operations == [
        "generate-teach-show",
        "generate-practice-check",
        "generate-setup",
        "generate-sendoff",
    ]
    setup_context = responses.payloads["generate-setup"]["assembled_rlo_context"]
    assert {"teach", "show", "practice", "check"} <= set(setup_context)
    sendoff_context = responses.payloads["generate-sendoff"]["assembled_rlo_context"]
    assert {"teach", "show", "practice", "check"} <= set(sendoff_context)
    expected_guidance_parts = {
        "generate-teach-show": {"teach", "show"},
        "generate-practice-check": {"practice", "check"},
        "generate-setup": {"setup"},
        "generate-sendoff": set(),
    }
    for operation, expected_parts in expected_guidance_parts.items():
        guidance = responses.payloads[operation]["methodology_profile"]["guidance"]
        assert {item["part"] for item in guidance} == expected_parts

    service.process_collection("batch-1")

    assert any(
        run.operation.startswith("collection-validation-")
        for run in store.prompt_runs
    )

    calls = responses.calls
    store.job = result.model_copy(update={"state": RLODraftState.PLANNING})
    resumed = service.process(job.job_id)

    assert resumed.state == RLODraftState.IN_REVIEW
    assert responses.calls == calls


def test_missed_authoring_guidance_remains_reviewable(monkeypatch):
    service, _store = _service(
        monkeypatch, FakeGenerationResponses(missed_guidance=True)
    )

    result = service.process("generation-job-variant")

    assert result.state == RLODraftState.IN_REVIEW
    assert result.draft is not None
    assert result.authoring.guidance_assessments[0].status == "missed"
    assert not any(
        finding.code == "unresolved_knowledge_gap" for finding in result.findings
    )


def test_incomplete_source_map_adds_attributed_model_knowledge(monkeypatch):
    workspace = _workspace()
    job = RLODraftJob(
        job_id="generation-job-enrichment",
        state=RLODraftState.PLANNING,
        request=RLODraftRequest(
            workspace_id=workspace.workspace_id,
            workspace_revision=workspace.revision,
            candidate_id=workspace.candidates[0].candidate_id,
            rlo_id="rlo-coffee-enriched",
            rlo_version="0.1.0",
        ),
    )
    store = MemoryGenerationStore(job, _material())
    monkeypatch.setattr(
        "src.source_authoring.generation.repository.get_objective_workspace",
        lambda *_args: workspace,
    )
    responses = FakeGenerationResponses(incomplete_mapping=True)
    service = RLOGenerationService(
        client=SimpleNamespace(responses=responses), store=store
    )

    result = service.process(job.job_id)

    assert result.state == RLODraftState.IN_REVIEW
    llm_claim = next(
        claim
        for claim in result.authoring.claims
        if claim.knowledge_origin == "llm_domain"
    )
    assert llm_claim.evidence_refs == []
    assert llm_claim.verification_status == "unverified"
    assert llm_claim.llm_provenance_ref
    assert result.authoring.llm_knowledge_provenance[0].model_alias == (
        "source-rlo-domain-enrichment"
    )
    assert "llm-domain-enrichment" in store.checkpoints
    assert any(
        finding.code == "llm_domain_review_priority"
        for finding in result.authoring.findings
    )


def _service(monkeypatch, responses):
    workspace = _workspace()
    job = RLODraftJob(
        job_id="generation-job-variant",
        state=RLODraftState.PLANNING,
        request=RLODraftRequest(
            workspace_id=workspace.workspace_id,
            workspace_revision=workspace.revision,
            candidate_id=workspace.candidates[0].candidate_id,
            rlo_id="rlo-coffee-variant",
            rlo_version="0.1.0",
        ),
    )
    store = MemoryGenerationStore(job, _material())
    monkeypatch.setattr(
        "src.source_authoring.generation.repository.get_objective_workspace",
        lambda *_args: workspace,
    )
    return RLOGenerationService(
        client=SimpleNamespace(responses=responses), store=store
    ), store


def test_unresolved_teach_gap_is_reviewable_validation_failure(monkeypatch):
    service, _store = _service(
        monkeypatch, FakeGenerationResponses(source_insufficient=True)
    )

    result = service.process("generation-job-variant")

    assert result.state == RLODraftState.VALIDATION_FAILED
    assert result.draft is None
    assert result.authoring is not None
    assert any(
        finding.code == "unresolved_knowledge_gap"
        for finding in result.authoring.findings
    )


def test_repair_changes_only_named_element_and_revalidates(monkeypatch):
    responses = FakeGenerationResponses(repair_once=True)
    service, store = _service(monkeypatch, responses)

    result = service.process("generation-job-variant")

    assert result.state == RLODraftState.IN_REVIEW
    show = next(part for part in result.authoring.parts if part.kind.value == "show")
    assert show.elements[0].origin.value == "source"
    assert responses.grounding_calls == 2
    assert "targeted-repair" in store.checkpoints


def test_invalid_repair_output_preserves_authoring_for_review(monkeypatch):
    responses = FakeGenerationResponses(
        repair_once=True,
        invalid_repair_output=True,
    )
    service, store = _service(monkeypatch, responses)

    result = service.process("generation-job-variant")

    assert result.state == RLODraftState.VALIDATION_FAILED
    assert result.draft is None
    assert result.authoring is not None
    assert "targeted-repair" not in store.checkpoints
    assert any(finding.code == "worked_example_clarity" for finding in result.findings)
    assert any(finding.code == "REPAIR_OUTPUT_INVALID" for finding in result.findings)


def test_semantically_invalid_repair_is_rejected_before_persistence(monkeypatch):
    responses = FakeGenerationResponses(
        repair_once=True,
        invalid_repair_claim=True,
    )
    service, store = _service(monkeypatch, responses)

    result = service.process("generation-job-variant")

    assert result.state == RLODraftState.VALIDATION_FAILED
    assert result.authoring is not None
    assert all(
        "claim-map-0002" not in element.claim_refs
        for part in result.authoring.parts
        for element in part.elements
        if element.assessment is not None
    )
    assert any(finding.code == "REPAIR_OUTPUT_INVALID" for finding in result.findings)
    assert store.job == result


def test_second_repair_pass_handles_findings_revealed_by_revalidation(monkeypatch):
    responses = FakeGenerationResponses(
        repair_once=True,
        second_repair_required=True,
    )
    service, store = _service(monkeypatch, responses)

    result = service.process("generation-job-variant")

    assert result.state == RLODraftState.IN_REVIEW
    assert responses.grounding_calls == 3
    assert "targeted-repair-2" in store.checkpoints
    assert "validate-pedagogy-after-repair-2" in store.checkpoints


def test_persistent_target_observed_mismatch_stays_visible(monkeypatch):
    service, _store = _service(
        monkeypatch, FakeGenerationResponses(persistent_mismatch=True)
    )

    result = service.process("generation-job-variant")

    assert result.state == RLODraftState.VALIDATION_FAILED
    assert result.draft is None
    assert result.authoring.classifications.target.content_type.value == "procedure"
    assert result.authoring.classifications.observed.content_type.value == "concept"
    assert any(
        finding.code == "target_observed_mismatch" for finding in result.findings
    )


def test_large_source_is_split_into_ordered_configured_tranches():
    material = _material()
    long_node = material.document.nodes[0].model_copy(
        update={"text": " ".join(f"step-{index}" for index in range(80))}
    )
    material.document = material.document.model_copy(update={"nodes": [long_node]})
    budget = SourceTokenBudget(source_token_limit=20, request_token_limit=200)
    from src.source_ingestion.segmentation import segment_document

    material.segments = segment_document(
        material.document, max_tokens=20, overlap_tokens=0, budget=budget
    )
    service = RLOGenerationService(
        client=SimpleNamespace(),
        token_budget=budget,
        store=SimpleNamespace(),
    )

    tranches = service._source_tranches([material])

    assert len(tranches) > 1
    assert [entry["chunk_index"] for tranche in tranches for entry in tranche] == list(
        range(sum(len(tranche) for tranche in tranches))
    )
    assert all(
        sum(budget.count(entry["text"]) for entry in tranche)
        <= budget.source_token_limit
        for tranche in tranches
    )


def test_snapshot_keeps_complete_token_bounded_table_evidence():
    workspace = _workspace()
    material = _material()
    header = f"| Name{' ' * 2200}| Purpose |"
    table_text = "\n".join(
        [header, "|---|---|", "| Preparation | Establish readiness |"]
    )
    table_node = material.document.nodes[0].model_copy(
        update={"kind": "table", "role": "table", "text": table_text}
    )
    material.document = material.document.model_copy(update={"nodes": [table_node]})
    from src.source_ingestion.segmentation import segment_document

    material.segments = segment_document(material.document)
    service = RLOGenerationService(client=SimpleNamespace(), store=SimpleNamespace())

    snapshot = service._snapshot(
        workspace, workspace.candidates[0], [material]
    )

    evidence = snapshot.evidence[0]
    assert len(evidence.excerpt) > 2_000
    assert "| Preparation | Establish readiness |" in evidence.excerpt
    assert evidence.segment_ids == [material.segments[0].segment_id]


def test_complete_long_table_evidence_reaches_generation_validation_and_repair(
    monkeypatch,
):
    workspace = _workspace()
    material = _material()
    header = f"| Name{' ' * 2200}| Purpose |"
    substantive_row = "| Preparation | Establish readiness |"
    table_text = "\n".join([header, "|---|---|", substantive_row])
    table_node = material.document.nodes[0].model_copy(
        update={"kind": "table", "role": "table", "text": table_text}
    )
    material.document = material.document.model_copy(update={"nodes": [table_node]})
    from src.source_ingestion.segmentation import segment_document

    material.segments = segment_document(material.document)
    job = RLODraftJob(
        job_id="long-table-generation",
        state=RLODraftState.PLANNING,
        request=RLODraftRequest(
            workspace_id=workspace.workspace_id,
            workspace_revision=workspace.revision,
            candidate_id=workspace.candidates[0].candidate_id,
            rlo_id="rlo-long-table",
            rlo_version="0.1.0",
        ),
    )
    store = MemoryGenerationStore(job, material)
    monkeypatch.setattr(
        "src.source_authoring.generation.repository.get_objective_workspace",
        lambda *_args: workspace,
    )
    responses = FakeGenerationResponses(repair_once=True)
    service = RLOGenerationService(
        client=SimpleNamespace(responses=responses), store=store
    )

    result = service.process(job.job_id)

    assert result.state == RLODraftState.IN_REVIEW
    assert substantive_row in responses.payloads["source-mapping-0001"][
        "source_segments"
    ][0]["text"]
    assert substantive_row in responses.payloads["source-mapping-challenge"][
        "evidence"
    ][0]["excerpt"]
    assert substantive_row in responses.payloads["generate-teach-show"]["evidence"][
        0
    ]["excerpt"]
    assert substantive_row in responses.payloads["validate-grounding"]["authoring"][
        "evidence"
    ][0]["excerpt"]
    assert substantive_row in responses.payloads["targeted-repair"]["authoring"][
        "evidence"
    ][0]["excerpt"]


def test_mapping_cites_one_exact_segment_from_a_split_node():
    workspace = _workspace()
    material = _material()
    long_node = material.document.nodes[0].model_copy(
        update={"text": " ".join(f"instruction-{index}" for index in range(30))}
    )
    material.document = material.document.model_copy(update={"nodes": [long_node]})
    from src.source_ingestion.segmentation import segment_document

    material.segments = segment_document(
        material.document, max_tokens=20, overlap_tokens=0
    )
    selected_segment = material.segments[1]
    service = RLOGenerationService(client=SimpleNamespace(), store=SimpleNamespace())
    snapshot = service._snapshot(workspace, workspace.candidates[0], [material])
    profile = get_methodology_profile("procedure", "apply")
    requirement_id = profile.requirements[3].requirement_id
    source_map = SourceMapDraft(
        claims=[
            MappedClaimDraft(
                local_ref="selected",
                statement="The selected source span supports this instruction.",
                citations=[
                    NodeCitationDraft(
                        source_version_id="source-v1",
                        segment_ids=[selected_segment.segment_id],
                    )
                ],
                role="objective_defining",
                assessment_eligible=True,
                requirement_refs=[requirement_id],
            )
        ]
    )

    _sources, evidence, _claims, _coverage = service._normalize_mapping(
        snapshot, [material], [source_map], profile
    )

    mapped = evidence[-1]
    assert mapped.segment_ids == [selected_segment.segment_id]
    assert mapped.excerpt == selected_segment.text
    assert mapped.excerpt != material.segments[0].text


def test_visual_explanation_claim_is_declared_as_source_synthesis():
    workspace = _workspace()
    material = _material()
    direct_node = material.document.nodes[0]
    visual_node = direct_node.model_copy(
        update={
            "node_id": "node-visual-explanation",
            "ordinal": 1,
            "ordinal_path": (1,),
            "kind": "visual_explanation",
            "role": "visual_explanation",
            "text": "The diagram depicts the brew control as the action trigger.",
        }
    )
    material.document = material.document.model_copy(
        update={"nodes": [direct_node, visual_node]}
    )
    from src.source_ingestion.segmentation import segment_document

    material.segments = segment_document(
        material.document, max_tokens=8, overlap_tokens=0
    )
    visual_segment = next(
        segment
        for segment in material.segments
        if "node-visual-explanation" in segment.node_ids
    )
    service = RLOGenerationService(client=SimpleNamespace(), store=SimpleNamespace())
    snapshot = service._snapshot(workspace, workspace.candidates[0], [material])
    profile = get_methodology_profile("procedure", "apply")
    source_map = SourceMapDraft(
        claims=[
            MappedClaimDraft(
                local_ref="visual",
                statement="The visual indicates that the brew control starts the action.",
                citations=[
                    NodeCitationDraft(
                        source_version_id="source-v1",
                        segment_ids=[visual_segment.segment_id],
                    )
                ],
                role="objective_defining",
                assessment_eligible=True,
                requirement_refs=[profile.requirements[0].requirement_id],
            )
        ]
    )

    _sources, _evidence, claims, _coverage = service._normalize_mapping(
        snapshot, [material], [source_map], profile
    )

    mapped_claim = claims[-1]
    assert mapped_claim.knowledge_origin == "source_synthesis"
    assert mapped_claim.source_claim_refs == ["claim-brew"]
    assert "Derived interpretation of a source visual" in mapped_claim.origin_rationale


def test_mapping_retains_exact_lineage_across_multiple_sources():
    workspace = _workspace()
    first = _material()
    second_node = first.document.nodes[0].model_copy(
        update={
            "node_id": "node-safety",
            "text": "Confirm the cup is positioned before brewing.",
        }
    )
    second_document = first.document.model_copy(
        update={"source_version_id": "source-v2", "nodes": [second_node]}
    )
    second = type(first)(
        source_id="source-safety",
        source_version_id="source-v2",
        title="Coffee safety note",
        filename="coffee-safety.pdf",
        checksum="2" * 64,
        document=second_document,
    )
    service = RLOGenerationService(
        client=SimpleNamespace(), store=SimpleNamespace()
    )
    snapshot = service._snapshot(
        workspace, workspace.candidates[0], [first, second]
    )
    profile = get_methodology_profile("procedure", "apply")
    requirement_id = profile.requirements[3].requirement_id
    source_map = SourceMapDraft(
        claims=[
            MappedClaimDraft(
                local_ref="safety",
                statement="Position the cup before brewing.",
                citations=[
                    NodeCitationDraft(
                        source_version_id="source-v2",
                        segment_ids=[second.segments[0].segment_id],
                    )
                ],
                role="objective_defining",
                assessment_eligible=True,
                requirement_refs=[requirement_id],
            )
        ],
        coverage=[
            RequirementCoverageDraft(
                requirement_id=requirement_id,
                status="complete",
                claim_refs=["safety"],
            )
        ],
    )

    sources, evidence, claims, coverage = service._normalize_mapping(
        snapshot, [first, second], [source_map], profile
    )

    assert [source.source_version_id for source in sources] == ["source-v1", "source-v2"]
    mapped_evidence = evidence[-1]
    assert mapped_evidence.source_version_id == "source-v2"
    assert mapped_evidence.source_ref == sources[1].id
    assert claims[-1].evidence_refs == [mapped_evidence.id]
    assert coverage[requirement_id]["claims"] == [claims[-1].claim_id]


def test_mapping_rejects_source_version_that_does_not_own_segment():
    workspace = _workspace()
    material = _material()
    service = RLOGenerationService(client=SimpleNamespace(), store=SimpleNamespace())
    snapshot = service._snapshot(workspace, workspace.candidates[0], [material])
    profile = get_methodology_profile("procedure", "apply")
    requirement_id = profile.requirements[3].requirement_id
    source_map = SourceMapDraft(
        claims=[
            MappedClaimDraft(
                local_ref="brew",
                statement="Press the brew button.",
                citations=[
                    NodeCitationDraft(
                        source_version_id="source-v1-with-a-copying-error",
                        segment_ids=[material.segments[0].segment_id],
                    )
                ],
                role="objective_defining",
                assessment_eligible=True,
                requirement_refs=[requirement_id],
            )
        ],
        coverage=[
            RequirementCoverageDraft(
                requirement_id=requirement_id,
                status="complete",
                claim_refs=["brew"],
            )
        ],
    )

    with pytest.raises(EvidenceContextError, match="does not own"):
        service._normalize_mapping(snapshot, [material], [source_map], profile)


def test_worker_rejects_outside_scope_before_any_model_call(monkeypatch):
    workspace = _workspace()
    outside = workspace.candidates[0].model_copy(
        update={
            "poc2_scope_status": "outside_poc2_scope",
            "poc2_scope_reason": "Principle × Analyze is outside POC2 scope.",
        }
    )
    workspace = workspace.model_copy(update={"candidates": [outside]})
    job = RLODraftJob(
        job_id="outside-scope-job",
        state=RLODraftState.PLANNING,
        request=RLODraftRequest(
            workspace_id=workspace.workspace_id,
            workspace_revision=workspace.revision,
            candidate_id=outside.candidate_id,
            rlo_id="rlo-outside",
            rlo_version="0.1.0",
        ),
    )
    store = MemoryGenerationStore(job, _material())
    monkeypatch.setattr(
        "src.source_authoring.generation.repository.get_objective_workspace",
        lambda *_args: workspace,
    )
    responses = FakeGenerationResponses()

    result = RLOGenerationService(
        client=SimpleNamespace(responses=responses), store=store
    ).process(job.job_id)

    assert result.state == RLODraftState.FAILED
    assert result.retryable is False
    assert "outside POC2" in result.error_message
    assert responses.calls == 0
