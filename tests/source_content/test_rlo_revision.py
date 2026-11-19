from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.source_authoring.authoring_contracts import AuthoringAssessmentOption
from src.source_authoring.draft_contracts import (
    DraftValidationFinding,
    RLODraftJob,
    RLODraftRequest,
    RLODraftState,
    RLOPendingRevision,
    RLORevisionPlanRequest,
)
from src.source_authoring.generation import RLOGenerationService
from src.source_authoring.generation_contracts import (
    AuthoringReviewDraft,
    GeneratedAssessment,
    GeneratedElementDraft,
    PartGenerationDraft,
)
from src.source_authoring.revision import (
    build_revision_plan,
    revision_finding_options,
)

from .test_rlo_authoring_contracts import _revision


def _job(*findings):
    return RLODraftJob(
        job_id="revision-job",
        state=RLODraftState.VALIDATION_FAILED,
        request=RLODraftRequest(
            workspace_id="workspace-1",
            workspace_revision=1,
            candidate_id="candidate-1",
            rlo_id="rlo-coffee-01",
            rlo_version="0.1.0",
        ),
        revision=1,
        authoring=_revision(),
        findings=list(findings),
    )


def _finding(code, category, path, *, repairable=True, severity="error"):
    return DraftValidationFinding(
        code=code,
        severity=severity,
        category=category,
        path=path,
        message=f"{code} requires review.",
        repairable=repairable,
    )


def test_revision_plan_exposes_two_call_assessment_scope():
    job = _job(_finding("CHECK-UNCLEAR", "pedagogy", "Check/check-01"))
    option = revision_finding_options(job)[0]

    plan = build_revision_plan(
        job,
        RLORevisionPlanRequest(
            action="repair_assessment",
            selected_finding_ids=[option.finding_id],
        ),
    )

    assert plan.executable is True
    assert plan.maximum_model_calls == 2
    assert plan.affected_parts == ["check"]
    assert plan.affected_element_ids == ["check-01"]
    assert plan.required_validator == "pedagogy"


def test_revision_plan_blocks_classification_capability_and_mixed_scope():
    classification = _finding(
        "TARGET_OBSERVED_CLASSIFICATION_MISMATCH",
        "classification",
        "Practice/practice-01; Check/check-01",
    )
    provenance = _finding("ORIGIN-MISMATCH", "grounding", "Setup/setup-01")
    job = _job(classification, provenance)
    options = revision_finding_options(job)

    assert options[0].executable is False
    assert "objective review" in options[0].stop_reason
    with pytest.raises(ValueError, match="stale or unknown"):
        build_revision_plan(
            job,
            RLORevisionPlanRequest(
                action="repair_provenance",
                selected_finding_ids=["finding-no-longer-present"],
            ),
        )


def test_revision_plan_does_not_spend_calls_on_advisory_style_notes():
    job = _job(
        _finding(
            "LEARNER_FACING_EM_DASHES",
            "schema",
            "Teach/teach-01",
            severity="warning",
        )
    )

    option = revision_finding_options(job)[0]

    assert option.executable is False
    assert "edit manually" in option.stop_reason


def test_historical_outside_scope_rlo_has_no_executable_revision():
    job = _job(_finding("CHECK-UNCLEAR", "pedagogy", "Check/check-01"))
    authoring = job.authoring
    outside = authoring.classifications.target.model_copy(
        update={"content_type": "principle", "bloom_level": "analyze"}
    )
    authoring = authoring.model_copy(
        update={
            "classifications": authoring.classifications.model_copy(
                update={"target": outside}
            )
        }
    )
    job = job.model_copy(update={"authoring": authoring})

    option = revision_finding_options(job)[0]

    assert option.executable is False
    assert "outside POC2" in option.stop_reason


class _RevisionStore:
    def __init__(self, job):
        self.job = job
        self.checkpoints = []
        self.prompt_runs = []

    def get_draft_job(self, _job_id):
        return self.job

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

    def list_generation_checkpoints(self, _job_id):
        return self.checkpoints

    def save_generation_checkpoint(self, job_id, **values):
        self.checkpoints.append(SimpleNamespace(job_id=job_id, **values))

    def record_generation_prompt_run(self, run):
        self.prompt_runs.append(run)

    def list_generation_prompt_runs(self, _job_id):
        return self.prompt_runs

    def refresh_generation_batch(self, _batch_id):
        return None


class _RevisionResponses:
    def parse(self, **kwargs):
        operation = kwargs["metadata"]["operation"]
        if operation.endswith("-repair"):
            assessment = GeneratedAssessment(
                stem="After inserting the capsule, which action completes the task?",
                type="multiple_choice_single",
                options=[
                    AuthoringAssessmentOption(
                        text="Press the brew button",
                        correct=True,
                        feedback="Correct; this completes the documented sequence.",
                        claim_refs=["claim-01"],
                    ),
                    AuthoringAssessmentOption(
                        text="Remove the capsule",
                        correct=False,
                        feedback="No; the brew action comes next.",
                        claim_refs=["claim-01"],
                    ),
                ],
                claim_refs=["claim-01"],
            )
            parsed = PartGenerationDraft(
                elements=[
                    GeneratedElementDraft(
                        part="check",
                        element_type="assessment_item",
                        assessment=assessment,
                        claim_refs=["claim-01"],
                        generation_note="Clarified the selected Check only.",
                        replace_element_id="check-01",
                    )
                ]
            )
        else:
            parsed = AuthoringReviewDraft(
                observed_classification=_revision().classifications.target
            )
        return SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def test_scoped_revision_changes_only_selected_element_and_stops_after_two_calls():
    selected_finding = _finding("CHECK-UNCLEAR", "pedagogy", "Check/check-01")
    retained_finding = _finding(
        "OPTIONAL-NOTE",
        "pedagogy",
        "Teach/teach-01",
        repairable=False,
        severity="warning",
    )
    job = _job(selected_finding, retained_finding)
    option = revision_finding_options(job)[0]
    plan = build_revision_plan(
        job,
        RLORevisionPlanRequest(
            action="repair_assessment",
            selected_finding_ids=[option.finding_id],
        ),
    )
    pending = RLOPendingRevision(
        revision_id="revision-1",
        plan=plan,
        reviewer="reviewer@deloitte.com",
        requested_at=datetime.now(timezone.utc).isoformat(),
        base_state=job.state,
    )
    job = job.model_copy(
        update={"state": RLODraftState.PLANNING, "pending_revision": pending}
    )
    original_setup = job.authoring.parts[1].model_dump(mode="json")
    store = _RevisionStore(job)
    service = RLOGenerationService(
        client=SimpleNamespace(responses=_RevisionResponses()), store=store
    )

    result = service.process(job.job_id)

    assert result.state == RLODraftState.IN_REVIEW
    assert result.revision == 2
    assert result.pending_revision is None
    assert len(store.prompt_runs) == 2
    assert result.revision_history[0].actual_model_calls == 2
    assert result.revision_history[0].usage["total_tokens"] == 30
    assert result.revision_history[0].resolved_finding_ids == [option.finding_id]
    assert result.authoring.parts[1].model_dump(mode="json") == original_setup
    check = result.authoring.parts[5].elements[0]
    assert "completes the task" in check.assessment.stem
    assert [item.code for item in result.findings] == ["OPTIONAL-NOTE"]
