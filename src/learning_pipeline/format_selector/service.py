"""Format selection service — Phase 11.

FormatSelectionService.select_format() is the single entry point.
It does not invoke the Modality Planner, the Workflow Planner, execute tools,
submit workflows, or modify the CourseBlueprint.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from learning_pipeline.contracts.assembly import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    FormatSelectionDecision,
    FormatSelectionMode,
    FormatSelectionRequest,
    FormatSelectionResult,
    FormatSelectionTrace,
    FormatSelectorStrategy,
    ModalityDeliveryProfile,
    ModalityEvaluation,
    ModalityFeasibility,
    SelectionBasis,
    SelectionFactor,
)

from .feasibility import evaluate_all_feasibility
from .recommender import FormatOutputValidationError, FakeFormatRecommender
from .registry import AvailableWorkflowRegistry
from .scoring import (
    SCORING_POLICY_VERSION,
    score_modality,
    select_best,
)


class FormatSelectionError(RuntimeError):
    """Raised when format selection cannot produce a result."""

    def __init__(
        self,
        message: str,
        *,
        blockers: tuple[str, ...] = (),
        feasible_alternatives: tuple[Modality, ...] = (),
    ) -> None:
        super().__init__(message)
        self.blockers = blockers
        self.feasible_alternatives = feasible_alternatives


# ── Hashing helpers ───────────────────────────────────────────────────────────


def _sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def _blueprint_hash(blueprint: CourseBlueprint) -> str:
    return _sha256(json.loads(blueprint.model_dump_json()))


def _constraints_hash(request: FormatSelectionRequest) -> str:
    return _sha256(json.loads(request.constraints.model_dump_json()))


def _registry_hash(snapshot: dict[str, Any]) -> str:
    return _sha256(snapshot)


def _profiles_hash(profiles: dict[Modality, ModalityDeliveryProfile]) -> str:
    return _sha256({
        m.value: json.loads(p.model_dump_json())
        for m, p in sorted(profiles.items(), key=lambda kv: kv[0].value)
    })


def _compute_input_hash(
    blueprint: CourseBlueprint,
    request: FormatSelectionRequest,
    registry_snapshot: dict[str, Any],
    profiles: dict[Modality, ModalityDeliveryProfile],
    policy_version: str,
    strategy: str,
    prompt_version: str | None,
    model: str | None,
) -> str:
    payload = {
        "blueprint": json.loads(blueprint.model_dump_json()),
        "request_content": {
            "blueprint_id": request.blueprint_id,
            "mode": request.mode,
            "requested_modality": request.requested_modality,
            "allow_fallback": request.allow_fallback,
            "preferred_modalities": list(request.preferred_modalities),
            "constraints": json.loads(request.constraints.model_dump_json()),
        },
        "registry_snapshot": registry_snapshot,
        "profiles": {
            m.value: json.loads(p.model_dump_json())
            for m, p in sorted(profiles.items(), key=lambda kv: kv[0].value)
        },
        "policy_version": policy_version,
        "strategy": strategy,
        "prompt_version": prompt_version,
        "model": model,
    }
    return _sha256(payload)


# ── Evaluation helpers ────────────────────────────────────────────────────────


def _build_infeasible_evaluation(feasibility: ModalityFeasibility) -> ModalityEvaluation:
    return ModalityEvaluation(
        modality=feasibility.modality,
        feasible=False,
        blockers=feasibility.blockers,
        factors=(),
        total_score=0.0,
    )


def _build_all_evaluations(
    all_feasibility: tuple[ModalityFeasibility, ...],
    profiles: dict[Modality, ModalityDeliveryProfile],
    request: FormatSelectionRequest,
    blueprint: CourseBlueprint,
) -> tuple[ModalityEvaluation, ...]:
    result = []
    for f in all_feasibility:
        if f.feasible:
            result.append(score_modality(f.modality, profiles[f.modality], request, blueprint))
        else:
            result.append(_build_infeasible_evaluation(f))
    return tuple(result)


# ── Service ───────────────────────────────────────────────────────────────────


class FormatSelectionService:
    """Selects the top-level learning deliverable modality for a given blueprint.

    Does not invoke planners, execute tools, or modify blueprints.
    """

    def __init__(
        self,
        registry: AvailableWorkflowRegistry,
        profiles: dict[Modality, ModalityDeliveryProfile],
        *,
        recommender=None,
        strategy: FormatSelectorStrategy = FormatSelectorStrategy.DETERMINISTIC,
        trace_root: Path | None = None,
    ) -> None:
        self._registry = registry
        self._profiles = profiles
        self._recommender = recommender
        self._strategy = strategy
        self._trace_root = trace_root

    async def select_format(
        self,
        blueprint: CourseBlueprint,
        request: FormatSelectionRequest,
        *,
        selection_id: str | None = None,
    ) -> FormatSelectionResult:
        if blueprint.blueprint_id != request.blueprint_id:
            raise FormatSelectionError(
                f"Blueprint ID mismatch: request has '{request.blueprint_id}', "
                f"supplied blueprint is '{blueprint.blueprint_id}'"
            )

        sid = selection_id or str(uuid.uuid4())
        registry_snapshot = self._registry.snapshot()

        recommender = self._recommender
        prompt_version = recommender.prompt_version if recommender else None
        model = recommender.model if recommender else None

        input_hash = _compute_input_hash(
            blueprint, request, registry_snapshot, self._profiles,
            SCORING_POLICY_VERSION, self._strategy.value, prompt_version, model,
        )

        bp_hash = _blueprint_hash(blueprint)
        constraints_hash = _constraints_hash(request)
        reg_hash = _registry_hash(registry_snapshot)
        prof_hash = _profiles_hash(self._profiles)

        # ── Cache check ───────────────────────────────────────────────────────
        if self._trace_root:
            cached = self._load_from_cache(input_hash)
            if cached is not None:
                return cached

        # ── Feasibility ───────────────────────────────────────────────────────
        all_feasibility = evaluate_all_feasibility(self._registry, self._profiles, request)
        feasible = [f for f in all_feasibility if f.feasible]

        # ── Score all candidates (infeasible get 0 with blockers) ─────────────
        all_evaluations = _build_all_evaluations(
            all_feasibility, self._profiles, request, blueprint
        )

        # ── Selection logic ───────────────────────────────────────────────────
        decision, llm_fallback_reason = await self._select(
            blueprint, request, all_feasibility, feasible, all_evaluations, sid,
        )

        # ── Trace ─────────────────────────────────────────────────────────────
        trace = FormatSelectionTrace(
            selection_id=sid,
            request_id=request.request_id,
            blueprint_hash=bp_hash,
            constraints_hash=constraints_hash,
            registry_snapshot_hash=reg_hash,
            profiles_hash=prof_hash,
            policy_version=SCORING_POLICY_VERSION,
            strategy=self._strategy.value,
            input_hash=input_hash,
            selected_modality=decision.selected_modality,
            basis=decision.basis,
            prompt_version=prompt_version,
            model=model,
            provider_request_id=recommender.provider_request_id if recommender else None,
            input_tokens=recommender.last_input_tokens if recommender else None,
            output_tokens=recommender.last_output_tokens if recommender else None,
            llm_fallback_reason=llm_fallback_reason,
        )

        result = FormatSelectionResult(decision=decision, trace=trace, from_cache=False)

        # ── Persist ───────────────────────────────────────────────────────────
        if self._trace_root:
            self._persist(input_hash, result)

        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _select(
        self,
        blueprint: CourseBlueprint,
        request: FormatSelectionRequest,
        all_feasibility: tuple[ModalityFeasibility, ...],
        feasible: list[ModalityFeasibility],
        all_evaluations: tuple[ModalityEvaluation, ...],
        selection_id: str,
    ) -> tuple[FormatSelectionDecision, str | None]:
        """Return (decision, llm_fallback_reason)."""
        llm_fallback_reason: str | None = None

        if request.mode == FormatSelectionMode.EXPLICIT:
            requested = request.requested_modality
            req_feasibility = next(f for f in all_feasibility if f.modality == requested)

            if req_feasibility.feasible:
                return (
                    self._make_decision(
                        selection_id=selection_id,
                        request=request,
                        blueprint=blueprint,
                        selected=requested,
                        basis=SelectionBasis.EXPLICIT,
                        evaluations=all_evaluations,
                        rationale=f"Explicit selection of '{requested}' accepted.",
                    ),
                    None,
                )

            if not request.allow_fallback:
                raise FormatSelectionError(
                    f"Requested modality '{requested}' is not feasible and "
                    f"allow_fallback is False.",
                    blockers=req_feasibility.blockers,
                    feasible_alternatives=tuple(f.modality for f in feasible),
                )

            if not feasible:
                raise FormatSelectionError(
                    f"Requested modality '{requested}' is not feasible and "
                    f"no alternative modalities are available.",
                    blockers=req_feasibility.blockers,
                    feasible_alternatives=(),
                )

            best = select_best(all_evaluations, request)
            return (
                self._make_decision(
                    selection_id=selection_id,
                    request=request,
                    blueprint=blueprint,
                    selected=best,
                    basis=SelectionBasis.EXPLICIT_FALLBACK,
                    evaluations=all_evaluations,
                    rationale=(
                        f"Requested modality '{requested}' is not feasible "
                        f"(fallback enabled). Falling back to '{best}'."
                    ),
                    fallback_from=requested,
                ),
                None,
            )

        # ── Auto mode ─────────────────────────────────────────────────────────
        if not feasible:
            raise FormatSelectionError(
                "No modalities are feasible for this request.",
                feasible_alternatives=(),
            )

        if len(feasible) == 1:
            selected = feasible[0].modality
            return (
                self._make_decision(
                    selection_id=selection_id,
                    request=request,
                    blueprint=blueprint,
                    selected=selected,
                    basis=SelectionBasis.SOLE_FEASIBLE,
                    evaluations=all_evaluations,
                    rationale=f"'{selected}' is the only feasible modality.",
                ),
                None,
            )

        # Multiple feasible candidates
        feasible_evals = tuple(e for e in all_evaluations if e.feasible)
        feasible_profiles = tuple(self._profiles[f.modality] for f in feasible)

        if (
            self._strategy == FormatSelectorStrategy.LLM_ASSISTED
            and self._recommender is not None
        ):
            try:
                recommendation = await self._recommender.recommend(
                    blueprint, request, feasible_profiles, feasible_evals
                )
                feasible_modalities = {f.modality for f in feasible}
                if recommendation.selected_modality in feasible_modalities:
                    return (
                        self._make_decision(
                            selection_id=selection_id,
                            request=request,
                            blueprint=blueprint,
                            selected=recommendation.selected_modality,
                            basis=SelectionBasis.LLM_ASSISTED,
                            evaluations=all_evaluations,
                            rationale=recommendation.rationale,
                            tradeoffs=recommendation.tradeoffs,
                        ),
                        None,
                    )
                llm_fallback_reason = (
                    f"LLM recommended '{recommendation.selected_modality}' "
                    f"which is not in the feasible set {sorted(m.value for m in feasible_modalities)}"
                )
            except (FormatOutputValidationError, Exception) as exc:
                llm_fallback_reason = f"LLM recommendation failed: {exc}"

            # Fall through to deterministic
            best = select_best(all_evaluations, request)
            return (
                self._make_decision(
                    selection_id=selection_id,
                    request=request,
                    blueprint=blueprint,
                    selected=best,
                    basis=SelectionBasis.LLM_FALLBACK,
                    evaluations=all_evaluations,
                    rationale=(
                        f"LLM recommendation not usable; deterministic fallback to '{best}'."
                    ),
                ),
                llm_fallback_reason,
            )

        # Deterministic
        best = select_best(all_evaluations, request)
        return (
            self._make_decision(
                selection_id=selection_id,
                request=request,
                blueprint=blueprint,
                selected=best,
                basis=SelectionBasis.DETERMINISTIC,
                evaluations=all_evaluations,
                rationale=f"Deterministic selection: '{best}' has the highest score.",
            ),
            None,
        )

    @staticmethod
    def _make_decision(
        *,
        selection_id: str,
        request: FormatSelectionRequest,
        blueprint: CourseBlueprint,
        selected: Modality,
        basis: SelectionBasis,
        evaluations: tuple[ModalityEvaluation, ...],
        rationale: str,
        tradeoffs: tuple[str, ...] = (),
        fallback_from: Modality | None = None,
    ) -> FormatSelectionDecision:
        return FormatSelectionDecision(
            selection_id=selection_id,
            request_id=request.request_id,
            blueprint_id=blueprint.blueprint_id,
            selected_modality=selected,
            basis=basis,
            evaluations=evaluations,
            rationale=rationale,
            tradeoffs=tradeoffs,
            policy_version=SCORING_POLICY_VERSION,
            fallback_from=fallback_from,
        )

    def _cache_dir(self, input_hash: str) -> Path:
        return self._trace_root / input_hash  # type: ignore[operator]

    def _load_from_cache(self, input_hash: str) -> FormatSelectionResult | None:
        cache_dir = self._cache_dir(input_hash)
        decision_path = cache_dir / "decision.json"
        trace_path = cache_dir / "trace.json"
        if decision_path.exists() and trace_path.exists():
            try:
                decision = FormatSelectionDecision.model_validate_json(
                    decision_path.read_text(encoding="utf-8")
                )
                trace = FormatSelectionTrace.model_validate_json(
                    trace_path.read_text(encoding="utf-8")
                )
                return FormatSelectionResult(decision=decision, trace=trace, from_cache=True)
            except Exception:
                return None
        return None

    def _persist(self, input_hash: str, result: FormatSelectionResult) -> None:
        cache_dir = self._cache_dir(input_hash)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "decision.json").write_text(
            result.decision.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "trace.json").write_text(
            result.trace.model_dump_json(indent=2), encoding="utf-8"
        )
