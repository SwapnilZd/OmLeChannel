from __future__ import annotations

from src.source_authoring.draft_contracts import DraftValidationFinding, RLODraftState

from .test_rlo_drafting import FakeResponses, _service, _request


def test_generated_rlo_cannot_replace_immutable_source_identity(monkeypatch):
    responses = FakeResponses()
    original_parse = responses.parse

    def altered(**kwargs):
        response = original_parse(**kwargs)
        if len(responses.calls) == 1:
            response.output_parsed.sources[0].checksum = "2" * 64
        return response

    responses.parse = altered
    service, _store, _responses = _service(monkeypatch, responses=responses)

    job = service.create(_request())

    assert job.state == RLODraftState.VALIDATION_FAILED
    assert any(finding.path == "sources" for finding in job.findings)


def test_unsupported_semantic_claim_blocks_human_approval(monkeypatch):
    responses = FakeResponses(
        findings=[
            DraftValidationFinding(
                code="unsupported_claim",
                severity="error",
                category="grounding",
                path="components.comp-rule-1",
                message="The cited node does not support this claim.",
            )
        ]
    )
    service, _store, _responses = _service(monkeypatch, responses=responses)

    job = service.create(_request())

    assert job.state == RLODraftState.VALIDATION_FAILED
    assert any(finding.code == "unsupported_claim" for finding in job.findings)
