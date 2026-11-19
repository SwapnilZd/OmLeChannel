"""
WorkflowPlanningService — Phase 9 / Phase 13B.

Orchestrates a full workflow planning pipeline (podcast or video):
  1. Resolves instructional content via PlanningContextResolver.
  2. Calls the modality-specific WorkflowPlanner for one structured model call.
  3. Compiles the ModalityProductionPlan into a BuildPlan.
  4. Persists the planning trace and plans to disk.
  5. Enforces idempotency: same input hash → cached result, no second LLM call.

Idempotency key
---------------
The input hash is SHA-256 of the UTF-8 JSON of the ResolvedPlanningContext.
Two planning requests that produce the same resolved context will share the
same cache entry regardless of caller-provided IDs.

Trace directory layout
-----------------------
{trace_root}/{input_hash}/
    production_plan.json
    build_plan.json
    trace.json

If trace_root is None, results are returned but not persisted.

Planner protocol
----------------
The ``planner`` argument is duck-typed.  Any object implementing:

    async def plan(context: ResolvedPlanningContext, modality_plan: ModalityPlan)
        -> ModalityProductionPlan

and exposing public ``prompt_version: str`` and ``model: str`` properties
(or attributes) is accepted.  Both PodcastWorkflowPlanner and
VideoWorkflowPlanner satisfy this contract.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from learning_pipeline.contracts import (
    BuildPlan,
    CourseBlueprint,
    ModalityPlan,
    ModalityProductionPlan,
)
from learning_pipeline.contracts.planning import (
    PlanningTrace,
    ResolvedPlanningContext,
    WorkflowPlanningResult,
)
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.production import ProductionCompiler



def _context_hash(context: ResolvedPlanningContext) -> str:
    return hashlib.sha256(
        context.model_dump_json().encode("utf-8")
    ).hexdigest()


def _plan_hash(plan: ModalityProductionPlan | BuildPlan) -> str:
    return hashlib.sha256(
        plan.model_dump_json().encode("utf-8")
    ).hexdigest()


class PlanningCacheError(RuntimeError):
    """Raised when a cached plan cannot be loaded."""


class WorkflowPlanningService:
    """Orchestrate one full podcast planning run with idempotency.

    Parameters
    ----------
    resolver:
        Resolves RLO content into a self-contained planning context.
    planner:
        Podcast-specific planner that makes one LLM call.
    compiler:
        Deterministically compiles a ModalityProductionPlan into a BuildPlan.
    catalog_hash:
        Pre-computed SHA-256 of the capability catalog used in this session.
        Recorded in the trace for reproducibility.  Callers should compute this
        once at startup (e.g. from ``build_tool_catalog()``).
    trace_root:
        Directory under which planning traces and plans are persisted.
        Pass ``None`` to disable persistence (useful in tests).
    """

    def __init__(
        self,
        resolver: PlanningContextResolver,
        planner,  # duck-typed: any planner with plan() + prompt_version + model
        compiler: ProductionCompiler,
        *,
        catalog_hash: str = "unknown",
        trace_root: Path | None = None,
    ) -> None:
        self._resolver = resolver
        self._planner = planner
        self._compiler = compiler
        self._catalog_hash = catalog_hash
        self._trace_root = Path(trace_root) if trace_root else None

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _cache_dir(self, input_hash: str) -> Path | None:
        if self._trace_root is None:
            return None
        return self._trace_root / input_hash

    def _load_cached(
        self, cache_dir: Path
    ) -> WorkflowPlanningResult | None:
        """Return a cached result if all three files exist and are valid."""
        prod_path = cache_dir / "production_plan.json"
        build_path = cache_dir / "build_plan.json"
        trace_path = cache_dir / "trace.json"
        if not (prod_path.exists() and build_path.exists() and trace_path.exists()):
            return None
        try:
            production_plan = ModalityProductionPlan.model_validate_json(
                prod_path.read_text(encoding="utf-8")
            )
            build_plan = BuildPlan.model_validate_json(
                build_path.read_text(encoding="utf-8")
            )
            trace = PlanningTrace.model_validate_json(
                trace_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise PlanningCacheError(
                f"Corrupt planning cache at '{cache_dir}': {exc}"
            ) from exc
        return WorkflowPlanningResult(
            production_plan=production_plan,
            build_plan=build_plan,
            trace=trace,
            from_cache=True,
        )

    def _save(
        self,
        cache_dir: Path,
        production_plan: ModalityProductionPlan,
        build_plan: BuildPlan,
        trace: PlanningTrace,
    ) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "production_plan.json").write_text(
            production_plan.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "build_plan.json").write_text(
            build_plan.model_dump_json(indent=2), encoding="utf-8"
        )
        (cache_dir / "trace.json").write_text(
            trace.model_dump_json(indent=2), encoding="utf-8"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def plan(
        self,
        blueprint: CourseBlueprint,
        modality_plan: ModalityPlan,
        *,
        planning_request_id: str | None = None,
        workflow_id: str | None = None,
    ) -> WorkflowPlanningResult:
        """Resolve, plan, compile, and cache one planning run.

        If an identical resolved context was planned before (same input hash)
        and the trace root is set, returns the cached result without calling
        the LLM.

        Parameters
        ----------
        blueprint:
            Course blueprint; used for RLO loading and learner context.
        modality_plan:
            Modality plan; constrains capability selection and scene coverage.
        planning_request_id:
            Caller-provided ID for the trace.  A UUID is generated if omitted.
        workflow_id:
            ID to use when compiling the build plan.  Defaults to the
            planning_request_id.

        Returns
        -------
        WorkflowPlanningResult
            Contains the production plan, build plan, and trace.
        """
        request_id = planning_request_id or str(uuid.uuid4())
        wf_id = workflow_id or request_id

        # 1. Resolve context (deterministic; no LLM)
        context: ResolvedPlanningContext = await self._resolver.resolve(
            blueprint, modality_plan
        )
        input_hash = _context_hash(context)

        # 2. Check cache
        cache_dir = self._cache_dir(input_hash)
        if cache_dir is not None:
            cached = self._load_cached(cache_dir)
            if cached is not None:
                return cached

        # 3. Plan (one LLM call via planner)
        production_plan: ModalityProductionPlan = await self._planner.plan(
            context, modality_plan
        )

        # 4. Compile
        build_plan: BuildPlan = self._compiler.compile(wf_id, production_plan)

        # 5. Build trace
        trace = PlanningTrace(
            planning_request_id=request_id,
            planner_type=type(self._planner).__name__,
            modality=modality_plan.modality,
            prompt_version=getattr(
                self._planner,
                "prompt_version",
                getattr(getattr(self._planner, "_prompt_path", None), "stem", "unknown"),
            ),
            model=getattr(self._planner, "model", getattr(self._planner, "_model", None)),
            input_hash=input_hash,
            capability_catalog_hash=self._catalog_hash,
            production_plan_hash=_plan_hash(production_plan),
            build_plan_hash=_plan_hash(build_plan),
            provider_request_id=None,
            input_tokens=None,
            output_tokens=None,
            estimated_cost_usd=None,
        )

        # 6. Persist (if trace_root configured)
        if cache_dir is not None:
            self._save(cache_dir, production_plan, build_plan, trace)

        return WorkflowPlanningResult(
            production_plan=production_plan,
            build_plan=build_plan,
            trace=trace,
            from_cache=False,
        )
