"""
ModalityPlanningService — Phase 10 / Phase 13C.

Orchestrates a full modality planning run (podcast or video):
  1. Validates the blueprint.
  2. Resolves selected RLO content into a ModalityPlanningContext.
  3. Computes currently producible podcast affordances.
  4. Calls the Podcast Modality Planner (one structured model call).
  5. Validates coverage, ordering, and duration.
  6. Persists the plan, coverage report, and trace.
  7. Enforces idempotency: same input hash → cached result, no second LLM call.

Idempotency key
---------------
SHA-256 of: resolved context JSON + affordance view JSON + modality +
            prompt version + model.  Any change in blueprint, RLO content,
            affordances, prompt version, or model invalidates the cache.

Trace directory layout
-----------------------
{trace_root}/{input_hash}/
    modality_plan.json
    coverage_report.json
    trace.json

If trace_root is None, results are returned but not persisted.

This service is intentionally independent of WorkflowPlanningService.
It does not call the Workflow Planner or submit a workflow automatically.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from learning_pipeline.affordances.catalog import PlannerAffordanceView
from learning_pipeline.affordances.feasibility import (
    AffordanceSupportRule,
    compute_producible_affordances,
)
from learning_pipeline.affordances.podcast import (
    PODCAST_SUPPORT_RULES,
    build_podcast_affordance_catalog,
)
from learning_pipeline.affordances.catalog import ModalityAffordanceCatalog
from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan
from learning_pipeline.contracts.planning import (
    ModalityCoverageReport,
    ModalityPlanningContext,
    ModalityPlanningResult,
    ModalityPlanningTrace,
)
from learning_pipeline.planners.modality.context import ModalityContextResolver
from learning_pipeline.planners.modality.validation import check_coverage
from learning_pipeline.tools.catalog import ProductionToolCatalog


class ModalityPlanningCacheError(RuntimeError):
    """Raised when a cached modality plan cannot be loaded."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _context_hash(context: ModalityPlanningContext, affordances: PlannerAffordanceView, modality: Modality, prompt_version: str, model: str | None) -> str:  # noqa: E501
    payload = json.dumps(
        {
            "context": json.loads(context.model_dump_json()),
            "affordances": json.loads(affordances.model_dump_json()),
            "modality": str(modality),
            "prompt_version": prompt_version,
            "model": model or "",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return _sha256_hex(payload.encode("utf-8"))


def _plan_hash(plan: ModalityPlan) -> str:
    return _sha256_hex(plan.model_dump_json().encode("utf-8"))


def _blueprint_hash(blueprint: CourseBlueprint) -> str:
    return _sha256_hex(blueprint.model_dump_json().encode("utf-8"))


class ModalityPlanningService:
    """Orchestrate one full modality planning run with idempotency.

    Supports any modality planner that implements:
      - async create_modality_plan(blueprint, modality, context, affordances)
      - .prompt_version  (str property)
      - .model           (str property)

    Parameters
    ----------
    resolver:
        Resolves RLO content from the blueprint into a ModalityPlanningContext.
    planner:
        Modality-specific planner (one LLM call per uncached request).
        Duck-typed: PodcastModalityPlanner and VideoModalityPlanner both satisfy.
    tool_catalog:
        Production tool catalog; used to determine producible affordances.
    support_rules:
        Affordance feasibility rules.  Defaults to PODCAST_SUPPORT_RULES for
        backward compatibility.
    affordance_catalog:
        Affordance catalog for the target modality.  Defaults to the podcast
        catalog for backward compatibility.
    extra_capabilities:
        Additional virtual capability strings injected into the available-
        capability set before computing producible affordances (e.g.
        ``frozenset({"visual_asset_available"})`` when visual assets exist).
    trace_root:
        Directory for plan and trace persistence.  Pass None to disable caching.
    """

    def __init__(
        self,
        resolver: ModalityContextResolver,
        planner,  # duck-typed: prompt_version, model, create_modality_plan()
        tool_catalog: ProductionToolCatalog,
        *,
        support_rules: tuple[AffordanceSupportRule, ...] = PODCAST_SUPPORT_RULES,
        affordance_catalog: ModalityAffordanceCatalog | None = None,
        extra_capabilities: frozenset[str] = frozenset(),
        available_capabilities: frozenset[str] | None = None,
        trace_root: Path | None = None,
    ) -> None:
        self._resolver = resolver
        self._planner = planner
        self._tool_catalog = tool_catalog
        self._support_rules = support_rules
        self._trace_root = Path(trace_root) if trace_root else None
        self._affordance_catalog = affordance_catalog or build_podcast_affordance_catalog()
        self._extra_capabilities = extra_capabilities
        self._available_capabilities = available_capabilities

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _cache_dir(self, input_hash: str) -> Path | None:
        if self._trace_root is None:
            return None
        return self._trace_root / input_hash

    def _load_cached(self, cache_dir: Path) -> ModalityPlanningResult | None:
        plan_path = cache_dir / "modality_plan.json"
        cov_path = cache_dir / "coverage_report.json"
        trace_path = cache_dir / "trace.json"
        if not (plan_path.exists() and cov_path.exists() and trace_path.exists()):
            return None
        try:
            plan = ModalityPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
            coverage = ModalityCoverageReport.model_validate_json(cov_path.read_text(encoding="utf-8"))
            trace = ModalityPlanningTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ModalityPlanningCacheError(
                f"Corrupt modality planning cache at '{cache_dir}': {exc}"
            ) from exc
        return ModalityPlanningResult(
            modality_plan=plan,
            coverage=coverage,
            trace=trace,
            from_cache=True,
        )

    def _save(
        self,
        cache_dir: Path,
        plan: ModalityPlan,
        coverage: ModalityCoverageReport,
        trace: ModalityPlanningTrace,
    ) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "modality_plan.json").write_text(
            plan.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "coverage_report.json").write_text(
            coverage.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "trace.json").write_text(
            trace.model_dump_json(indent=2), encoding="utf-8"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_modality_plan(
        self,
        blueprint: CourseBlueprint,
        modality: Modality = Modality.PODCAST,
        *,
        planning_request_id: str | None = None,
    ) -> ModalityPlanningResult:
        """Resolve, plan, validate coverage/ordering/duration, and cache.

        If an identical resolved context + affordance view was planned before
        (same input hash) and trace_root is set, returns the cached result
        without calling the LLM.

        Parameters
        ----------
        blueprint:
            Course blueprint; used for RLO loading and context resolution.
        modality:
            Target modality; must be podcast for this service.
        planning_request_id:
            Caller-provided ID for the trace.  A UUID is generated if omitted.

        Returns
        -------
        ModalityPlanningResult
        """
        request_id = planning_request_id or str(uuid.uuid4())

        # 1. Resolve context
        context: ModalityPlanningContext = await self._resolver.resolve(blueprint)

        # 2. Compute producible affordances
        available_caps = (
            self._available_capabilities
            if self._available_capabilities is not None
            else self._tool_catalog.capabilities
        ) | self._extra_capabilities
        affordances: PlannerAffordanceView = compute_producible_affordances(
            catalog=self._affordance_catalog,
            support_rules=self._support_rules,
            available_capabilities=available_caps,
            modality=modality,
        )

        # 3. Compute input hash for idempotency
        planner_prompt_version = getattr(self._planner, "prompt_version", "unknown")
        planner_model = getattr(self._planner, "model", None)
        input_hash = _context_hash(
            context, affordances, modality,
            planner_prompt_version, planner_model,
        )
        bp_hash = _blueprint_hash(blueprint)

        # 4. Check cache
        cache_dir = self._cache_dir(input_hash)
        if cache_dir is not None:
            cached = self._load_cached(cache_dir)
            if cached is not None:
                return cached

        # 5. Call planner (one LLM call)
        plan: ModalityPlan = await self._planner.create_modality_plan(
            blueprint, modality, context, affordances
        )

        # 6. Validate coverage, ordering, duration from the returned plan
        #    (Reconstruct a synthetic draft view for coverage from plan.scenes)
        coverage = _compute_coverage_from_plan(plan, context)
        check_coverage(coverage)
        check_ordering_from_plan(plan, blueprint)
        check_duration_from_plan(plan, blueprint)

        # 7. Build trace
        affordance_view_hash = _sha256_hex(affordances.model_dump_json().encode("utf-8"))
        plan_hash = _plan_hash(plan)

        trace = ModalityPlanningTrace(
            planning_request_id=request_id,
            planner_type=type(self._planner).__name__,
            modality=modality,
            prompt_version=planner_prompt_version,
            model=planner_model,
            blueprint_hash=bp_hash,
            context_hash=_sha256_hex(context.model_dump_json().encode("utf-8")),
            affordance_view_hash=affordance_view_hash,
            modality_plan_hash=plan_hash,
            validation_summary=(
                f"Covered: {len(coverage.covered_objective_ids)} objectives, "
                f"{len(coverage.covered_concept_ids)} concepts, "
                f"{len(coverage.covered_component_ids)} components, "
                f"{len(coverage.covered_assessment_ids)} assessments"
            ),
        )

        # 8. Persist
        if cache_dir is not None:
            self._save(cache_dir, plan, coverage, trace)

        return ModalityPlanningResult(
            modality_plan=plan,
            coverage=coverage,
            trace=trace,
            from_cache=False,
        )


# ── Coverage / ordering / duration from a ModalityPlan ───────────────────────


def _compute_coverage_from_plan(
    plan: ModalityPlan,
    context: ModalityPlanningContext,
) -> ModalityCoverageReport:
    """Compute coverage by examining scene source_content references in the plan."""
    required_objectives: set[str] = set()
    required_concepts: set[str] = set()
    required_components: set[str] = set()
    required_assessments: set[str] = set()

    for rlo_ctx in context.rlo_contexts:
        required_objectives.update(rlo_ctx.selected_objective_ids)
        required_concepts.update(rlo_ctx.selected_concept_ids)
        required_components.update(rlo_ctx.selected_component_ids)
        required_assessments.update(rlo_ctx.selected_assessment_ids)

    covered_objectives: set[str] = set()
    covered_concepts: set[str] = set()
    covered_components: set[str] = set()
    covered_assessments: set[str] = set()

    coverage_counts: dict[str, int] = {}

    for scene in plan.scenes:
        for ref in scene.source_content:
            for oid in ref.objective_ids:
                coverage_counts[f"obj:{oid}"] = coverage_counts.get(f"obj:{oid}", 0) + 1
                covered_objectives.add(oid)
            for cid in ref.concept_ids:
                coverage_counts[f"con:{cid}"] = coverage_counts.get(f"con:{cid}", 0) + 1
                covered_concepts.add(cid)
            for cid in ref.component_ids:
                coverage_counts[f"comp:{cid}"] = coverage_counts.get(f"comp:{cid}", 0) + 1
                covered_components.add(cid)
            for aid in ref.assessment_item_ids:
                coverage_counts[f"ass:{aid}"] = coverage_counts.get(f"ass:{aid}", 0) + 1
                covered_assessments.add(aid)

    duplicate_warnings = tuple(
        f"{key} covered {count} times"
        for key, count in sorted(coverage_counts.items())
        if count > 1
    )

    return ModalityCoverageReport(
        covered_objective_ids=tuple(sorted(covered_objectives & required_objectives)),
        covered_concept_ids=tuple(sorted(covered_concepts & required_concepts)),
        covered_component_ids=tuple(sorted(covered_components & required_components)),
        covered_assessment_ids=tuple(sorted(covered_assessments & required_assessments)),
        uncovered_objective_ids=tuple(sorted(required_objectives - covered_objectives)),
        uncovered_concept_ids=tuple(sorted(required_concepts - covered_concepts)),
        uncovered_component_ids=tuple(sorted(required_components - covered_components)),
        uncovered_assessment_ids=tuple(sorted(required_assessments - covered_assessments)),
        duplicate_coverage_warnings=duplicate_warnings,
    )


def check_ordering_from_plan(plan: ModalityPlan, blueprint: CourseBlueprint) -> None:
    """Validate RLO teaching order in the plan matches blueprint ordering."""
    sorted_refs = sorted(blueprint.ordered_rlo_refs, key=lambda r: r.order)
    rlo_blueprint_pos: dict[str, int] = {
        ref.rlo_id: i for i, ref in enumerate(sorted_refs)
    }
    first_scene_idx: dict[str, int] = {}
    for scene_idx, scene in enumerate(plan.scenes):
        for ref in scene.source_content:
            if ref.rlo_id not in first_scene_idx:
                first_scene_idx[ref.rlo_id] = scene_idx

    present_rlo_ids = [
        ref.rlo_id for ref in sorted_refs if ref.rlo_id in first_scene_idx
    ]
    for i in range(1, len(present_rlo_ids)):
        prior_rlo = present_rlo_ids[i - 1]
        current_rlo = present_rlo_ids[i]
        if first_scene_idx[current_rlo] < first_scene_idx[prior_rlo]:
            raise ValueError(
                f"Plan ordering violates blueprint: '{current_rlo}' first appears in scene "
                f"{first_scene_idx[current_rlo]} before '{prior_rlo}' first appears in scene "
                f"{first_scene_idx[prior_rlo]}"
            )


def check_duration_from_plan(plan: ModalityPlan, blueprint: CourseBlueprint) -> None:
    """Validate that scene duration targets fit within an explicit learner limit.

    Only enforces when learner.duration_limit_minutes is explicitly set.
    blueprint.estimated_duration_minutes is a content-complexity signal, not a hard ceiling.
    """
    explicit_limit = blueprint.learner.duration_limit_minutes
    if explicit_limit is None:
        return

    total_seconds = sum(s.target_duration_seconds or 0 for s in plan.scenes)
    limit_seconds = explicit_limit * 60

    if total_seconds > limit_seconds:
        raise ValueError(
            f"Plan duration {total_seconds}s exceeds learner limit {limit_seconds}s"
        )
