"""CourseAssemblyService — Phase 12.

Orchestrates a full curriculum assembly run:
  1.  Validate request.
  2.  Load exact candidate RLOs from repository.
  3.  Enforce governance policy.
  4.  Build deterministic assembly-context projection.
  5.  Verify planning-context size limit.
  6.  Compute idempotency hash; check cache.
  7.  Call Assembly Agent (one initial structured model call).
  8.  Validate draft.
  9.  Build blueprint deterministically; allow one duration-only correction.
  10. Persist draft, blueprint, report, and trace.
  11. Return CourseAssemblyResult.

Does not automatically select a format or invoke downstream planners.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyPlanningTrace,
    CourseAssemblyDraft,
    CourseAssemblyReport,
    CourseAssemblyRequest,
    CourseAssemblyResult,
    RLOAssemblyContext,
)
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.client import PlanningOutputValidationError
from learning_pipeline.repository import RLONotFoundError, RLORepository, RLOVersionNotFoundError

from .agent import CurriculumAssemblyAgent
from .builder import BlueprintBuildError, build_blueprint
from .context import ContextBudgetExceededError, build_assembly_context, check_context_budget
from .draft_validation import DraftValidationError, validate_draft
from .governance import GOVERNANCE_POLICY_VERSION, enforce_governance

ASSEMBLY_POLICY_VERSION = GOVERNANCE_POLICY_VERSION


class CourseAssemblyError(RuntimeError):
    """Raised when assembly cannot produce a valid result."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def _compute_input_hash(
    request: CourseAssemblyRequest,
    rlo_snapshot: dict[str, str],
    contexts: tuple[RLOAssemblyContext, ...],
    policy_version: str,
    prompt_version: str,
    model: str | None,
) -> str:
    payload = {
        "request": json.loads(request.model_dump_json()),
        "rlo_snapshot": rlo_snapshot,
        "context_hash": _sha256([json.loads(c.model_dump_json()) for c in contexts]),
        "policy_version": policy_version,
        "prompt_version": prompt_version,
        "model": model or "",
    }
    # Exclude request_id from hash (same as Phase 11 pattern)
    req_payload = json.loads(request.model_dump_json())
    req_payload.pop("request_id", None)
    payload["request"] = req_payload
    return _sha256(payload)


class CourseAssemblyService:
    """Assembles a modality-agnostic CourseBlueprint from candidate RLOs.

    Parameters
    ----------
    agent:
        The assembly agent (fake or real).
    repository:
        RLO repository for loading exact candidate versions.
    trace_root:
        Directory for persistence.  None disables caching.
    context_budget_chars:
        Maximum serialized context size (default 500,000 chars).
    """

    def __init__(
        self,
        agent: CurriculumAssemblyAgent,
        repository: RLORepository,
        *,
        trace_root: Path | None = None,
        context_budget_chars: int = 500_000,
    ) -> None:
        self._agent = agent
        self._repository = repository
        self._trace_root = Path(trace_root) if trace_root else None
        self._budget = context_budget_chars

    async def assemble_course(
        self,
        request: CourseAssemblyRequest,
        idempotency_key: str | None = None,
    ) -> CourseAssemblyResult:
        """Run the full assembly pipeline and return the result.

        Parameters
        ----------
        request:
            Validated assembly request.
        idempotency_key:
            Optional caller-supplied key; a UUID is generated if omitted.
        """
        # Step 1: Request validation is done by Pydantic — no extra check needed.

        # Step 2: Load exact candidate RLOs
        rlos: dict[str, RLODocument] = {}
        for candidate in request.candidates:
            try:
                rlo = await self._repository.get(candidate.rlo_id, candidate.rlo_version)
            except RLONotFoundError as exc:
                raise CourseAssemblyError(
                    f"Candidate RLO '{candidate.rlo_id}' not found in repository."
                ) from exc
            except RLOVersionNotFoundError as exc:
                raise CourseAssemblyError(
                    f"Candidate RLO '{candidate.rlo_id}' found but not at version "
                    f"'{candidate.rlo_version}'. No silent version substitution."
                ) from exc
            rlos[candidate.rlo_id] = rlo

        # Step 3: Governance enforcement
        try:
            governance_rejected, governance_warnings = enforce_governance(
                request.candidates, rlos, request
            )
        except Exception as exc:
            raise CourseAssemblyError(str(exc)) from exc

        # Determine eligible candidates: not governance-rejected, not excluded
        excluded_ids = set(request.constraints.excluded_rlo_ids)
        eligible_candidates = [
            c for c in request.candidates
            if c.rlo_id not in governance_rejected
            and c.rlo_id not in excluded_ids
        ]

        # Step 4: Build deterministic assembly-context projections
        contexts: tuple[RLOAssemblyContext, ...] = tuple(
            build_assembly_context(rlos[c.rlo_id]) for c in eligible_candidates
        )

        # Step 5: Check context budget
        try:
            check_context_budget(contexts, self._budget)
        except ContextBudgetExceededError:
            raise

        # Step 6: Compute idempotency hash
        rlo_snapshot = {c.rlo_id: c.rlo_version for c in request.candidates}
        input_hash = _compute_input_hash(
            request, rlo_snapshot, contexts,
            ASSEMBLY_POLICY_VERSION, self._agent.prompt_version, self._agent.model,
        )

        # Check cache
        if self._trace_root:
            cached = self._load_from_cache(input_hash)
            if cached is not None:
                return cached

        # Step 7: Call Assembly Agent (one structured model call)
        try:
            planning_response = await self._agent.create_assembly_draft(request, contexts)
        except PlanningOutputValidationError as exc:
            raise CourseAssemblyError(
                "Assembly agent output failed schema validation. "
                "Submit a new assembly request to try again."
            ) from exc

        draft = planning_response.result
        if not isinstance(draft, CourseAssemblyDraft):
            raise CourseAssemblyError(
                f"Assembly agent returned unexpected type: {type(draft).__name__}"
            )

        # Step 8: Validate draft
        try:
            validate_draft(draft, request, contexts)
        except DraftValidationError as exc:
            raise CourseAssemblyError(f"Draft validation failed: {exc}") from exc

        # Step 9: Build blueprint deterministically. The real agent gets one
        # bounded correction when its otherwise-valid draft exceeds the hard
        # duration ceiling. Structural/schema failures remain fail-closed.
        try:
            result = build_blueprint(
                draft=draft,
                request=request,
                eligible_contexts=contexts,
                governance_rejected=governance_rejected,
                governance_warnings=governance_warnings,
                planning_response=planning_response,
                input_hash=input_hash,
            )
        except BlueprintBuildError as exc:
            repair_method = getattr(self._agent, "repair_duration_draft", None)
            is_duration_failure = str(exc).startswith("Estimated duration ")
            if repair_method is None or not is_duration_failure:
                raise CourseAssemblyError(f"Blueprint build failed: {exc}") from exc
            try:
                repaired_response = await repair_method(
                    request, contexts, draft, str(exc)
                )
            except PlanningOutputValidationError as repair_exc:
                raise CourseAssemblyError(
                    "Assembly duration repair failed schema validation."
                ) from repair_exc
            repaired_draft = repaired_response.result
            if not isinstance(repaired_draft, CourseAssemblyDraft):
                raise CourseAssemblyError(
                    "Assembly duration repair returned an unexpected result type."
                )
            try:
                validate_draft(repaired_draft, request, contexts)
                result = build_blueprint(
                    draft=repaired_draft,
                    request=request,
                    eligible_contexts=contexts,
                    governance_rejected=governance_rejected,
                    governance_warnings=governance_warnings,
                    planning_response=repaired_response,
                    input_hash=input_hash,
                )
            except (DraftValidationError, BlueprintBuildError, ValueError) as repair_exc:
                raise CourseAssemblyError(
                    f"Blueprint build failed after one duration repair: {repair_exc}"
                ) from repair_exc
            draft = repaired_draft
            planning_response = repaired_response
        except ValueError as exc:
            raise CourseAssemblyError(f"Blueprint build failed: {exc}") from exc

        # Patch trace hashes that the builder left empty (service has richer context)
        learner_hash = _sha256(json.loads(request.learner.model_dump_json()))
        constraints_hash = _sha256(json.loads(request.constraints.model_dump_json()))
        candidate_snapshot_hash = _sha256(rlo_snapshot)
        context_hash = _sha256([json.loads(c.model_dump_json()) for c in contexts])

        trace = AssemblyPlanningTrace(
            **{
                **json.loads(result.trace.model_dump_json()),
                "candidate_snapshot_hash": candidate_snapshot_hash,
                "learner_hash": learner_hash,
                "constraints_hash": constraints_hash,
                "context_hash": context_hash,
            }
        )
        result = CourseAssemblyResult(
            blueprint=result.blueprint,
            report=result.report,
            trace=trace,
            from_cache=False,
        )

        # Step 10: Persist
        if self._trace_root:
            self._persist(input_hash, result, draft)

        return result

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _cache_dir(self, input_hash: str) -> Path:
        return self._trace_root / input_hash  # type: ignore[operator]

    def _load_from_cache(self, input_hash: str) -> CourseAssemblyResult | None:
        from learning_pipeline.contracts.assembly import CourseBlueprint
        cache_dir = self._cache_dir(input_hash)
        bp_path = cache_dir / "course-blueprint.json"
        report_path = cache_dir / "assembly-report.json"
        trace_path = cache_dir / "planning-trace.json"
        if not (bp_path.exists() and report_path.exists() and trace_path.exists()):
            return None
        try:
            blueprint = CourseBlueprint.model_validate_json(bp_path.read_text(encoding="utf-8"))
            report = CourseAssemblyReport.model_validate_json(report_path.read_text(encoding="utf-8"))
            trace = AssemblyPlanningTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
            return CourseAssemblyResult(blueprint=blueprint, report=report, trace=trace, from_cache=True)
        except Exception:
            return None

    def _persist(
        self,
        input_hash: str,
        result: CourseAssemblyResult,
        draft: CourseAssemblyDraft,
    ) -> None:
        cache_dir = self._cache_dir(input_hash)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "assembly-draft.json").write_text(
            draft.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "course-blueprint.json").write_text(
            result.blueprint.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "assembly-report.json").write_text(
            result.report.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "planning-trace.json").write_text(
            result.trace.model_dump_json(indent=2), encoding="utf-8"
        )
