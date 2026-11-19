"""Preview creation and exact-version confirmation policy."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from ..adapters.rlo import RLOCompatibilityError, adapt_stored_rlo
from ..contracts import (
    CandidateCurationTrace,
    ConfirmedLearningRequest,
    LearningCommissionRequest,
    LearningRequestConfirmation,
    LearningRequestPreview,
    RLOCandidateDisposition,
    RelevanceBand,
)
from ..repository import PreviewRepository
from .curation import CandidateCurationService, CURATION_PROMPT_VERSION, deterministic_curation
from .interpretation import SearchIntentInterpreter
from .retrieval import RETRIEVAL_POLICY_VERSION, CatalogClient, RLODiscoveryService


class PreviewNotFoundError(LookupError):
    pass


class ConfirmationRejectedError(ValueError):
    pass


class StalePreviewError(ConfirmationRejectedError):
    pass


def _hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


class LearningRequestPreviewService:
    def __init__(
        self,
        interpreter: SearchIntentInterpreter,
        discovery: RLODiscoveryService,
        catalog: CatalogClient,
        repository: PreviewRepository,
        curation: CandidateCurationService | None = None,
    ) -> None:
        self.interpreter = interpreter
        self.discovery = discovery
        self.catalog = catalog
        self.repository = repository
        self.curation = curation

    async def create_preview(self, request: LearningCommissionRequest) -> LearningRequestPreview:
        intent, trace = await self.interpreter.interpret(request)
        outcome = await self.discovery.discover(request, intent)
        if self.curation is not None:
            curation_review, curation_trace = await self.curation.curate(
                request, intent, outcome.candidates
            )
        else:
            curation_review = deterministic_curation(
                outcome.candidates, reason="curation service not configured"
            )
            curation_trace = CandidateCurationTrace(
                prompt_version=CURATION_PROMPT_VERSION,
                reviewed_candidate_count=0,
                fallback_reason="curation service not configured",
            )
        snapshot = {
            "request": request.model_dump(mode="json"),
            "intent": intent.model_dump(mode="json"),
            "candidates": [candidate.model_dump(mode="json") for candidate in outcome.candidates],
            "gap_report": outcome.gap_report.model_dump(mode="json"),
            "curation_review": curation_review.model_dump(mode="json"),
            "compatibility_errors": list(outcome.compatibility_errors),
            "curation_prompt": curation_trace.prompt_version,
            "interpretation_prompt": trace.prompt_version,
            "retrieval_policy": RETRIEVAL_POLICY_VERSION,
            "index_revision": outcome.index_revision,
        }
        preview_hash = _hash(snapshot)
        existing = await self.repository.get_preview_by_hash(preview_hash)
        if existing:
            return existing
        preview = LearningRequestPreview(
            preview_id=f"preview-{preview_hash[:24]}",
            preview_hash=preview_hash,
            request=request,
            intent=intent,
            candidates=outcome.candidates,
            gap_report=outcome.gap_report,
            interpretation_trace=trace,
            curation_review=curation_review,
            curation_trace=curation_trace,
            compatibility_errors=outcome.compatibility_errors,
            retrieval_policy_version=RETRIEVAL_POLICY_VERSION,
            index_revision=outcome.index_revision,
            created_at=datetime.now(UTC),
        )
        await self.repository.put_preview(preview)
        return preview

    async def get_preview(self, preview_id: str) -> LearningRequestPreview:
        preview = await self.repository.get_preview(preview_id)
        if preview is None:
            raise PreviewNotFoundError(preview_id)
        return preview

    async def confirm(
        self, preview_id: str, command: LearningRequestConfirmation
    ) -> ConfirmedLearningRequest:
        preview = await self.get_preview(preview_id)
        if command.preview_hash != preview.preview_hash:
            raise StalePreviewError("preview hash does not match the immutable snapshot")
        if preview.retrieval_policy_version != RETRIEVAL_POLICY_VERSION:
            raise StalePreviewError("retrieval policy changed; create a new preview")
        if not preview.confirmation_allowed:
            raise ConfirmationRejectedError(preview.gap_report.explanation)

        existing = await self.repository.get_confirmation(preview_id)
        if existing is not None:
            same_command = (
                existing.preview_hash == command.preview_hash
                and existing.confirmed_course_goal == command.confirmed_course_goal
                and existing.candidates == command.candidates
                and existing.confirmation_actor == command.confirmation_actor
                and existing.requester_notes == command.requester_notes
            )
            if same_command:
                await self.repository.enqueue_job(existing)
                return existing
            raise ConfirmationRejectedError("preview was already confirmed with different choices")

        eligible = {
            (candidate.rlo_id, candidate.rlo_version): candidate
            for candidate in preview.candidates
            if candidate.relevance_band != RelevanceBand.FORBIDDEN
        }
        preview_keys = {
            (candidate.rlo_id, candidate.rlo_version) for candidate in preview.candidates
        }
        for candidate in command.candidates:
            if (candidate.rlo_id, candidate.rlo_version) not in preview_keys:
                raise ConfirmationRejectedError(
                    f"{candidate.rlo_id}@{candidate.rlo_version} is not part of this preview"
                )
        selected = [
            candidate for candidate in command.candidates
            if candidate.disposition in (
                RLOCandidateDisposition.INCLUDE,
                RLOCandidateDisposition.REQUIRED,
            )
        ]
        if not selected:
            raise ConfirmationRejectedError("at least one eligible RLO must be selected")
        for candidate in selected:
            key = (candidate.rlo_id, candidate.rlo_version)
            if key not in eligible:
                raise ConfirmationRejectedError(
                    f"{candidate.rlo_id}@{candidate.rlo_version} is below the minimum relevance threshold"
                )
            versions = await self.catalog.get_versions(candidate.rlo_id)
            current = next((item for item in versions if item.get("is_current")), None)
            if not current or current.get("rlo_version") != candidate.rlo_version:
                raise StalePreviewError(
                    f"{candidate.rlo_id}@{candidate.rlo_version} is no longer current"
                )
            try:
                raw = await self.catalog.get_exact(candidate.rlo_id, candidate.rlo_version)
                adapt_stored_rlo(raw)
            except (RLOCompatibilityError, ValueError) as exc:
                raise StalePreviewError(str(exc)) from exc

        confirmation = ConfirmedLearningRequest(
            request_id=preview.request.request_id,
            preview_id=preview.preview_id,
            preview_hash=preview.preview_hash,
            confirmed_course_goal=command.confirmed_course_goal,
            candidates=command.candidates,
            confirmation_actor=command.confirmation_actor,
            confirmed_at=datetime.now(UTC),
            requester_notes=command.requester_notes,
        )
        await self.repository.put_confirmation(confirmation)
        await self.repository.enqueue_job(confirmation)
        return confirmation
