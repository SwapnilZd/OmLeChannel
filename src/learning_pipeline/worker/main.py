"""
Background worker — Phase 6 / Phase 7.

Polls PostgreSQL for pending workflows, claims one at a time, executes it,
and persists the result.

Lifecycle
---------
  Start
    → read PIPELINE_MODE (default: reference)
    → connect to PostgreSQL
    → register SIGTERM / SIGINT handlers
    → poll loop:
        claim_next_pending
        if none: sleep WORKER_POLL_INTERVAL_SECONDS
        else:
          deserialize BuildPlan
          validate plan
          run DAGRunner (fake or real executors)
          mark succeeded / failed
          loop immediately (don't sleep)
    → on signal: drain current task, stop claiming new work

Constraints
-----------
* No LLM calls.
* No runtime replanning.
* PIPELINE_MODE=reference — no credentials required (default).
* PIPELINE_MODE=real — reads LITE_LLM_BASE_URL, LITE_LLM_API_KEY, etc. at startup;
  fails immediately if any required variable is absent.
* Validates the plan again before execution (defensive, not redundant).
* Continues processing after a failed workflow.
* Persists a concise failure message — never the full stack-trace in DB.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import time

import asyncpg

from learning_pipeline.config import REGISTERED_TASK_TYPES
from learning_pipeline.contracts import BuildPlan
from learning_pipeline.db.connection import create_pool
from learning_pipeline.db.repository import PersistentWorkflowStatus, WorkflowRepository
from learning_pipeline.db.run_state import PostgresRunStateStore
from learning_pipeline.runtime.runner import DAGRunner, WorkflowExecutionError
from learning_pipeline.validation import PlanValidationError, validate_build_plan

log = logging.getLogger(__name__)


class WorkerLoop:
    """
    Stateless polling worker.

    All dependencies (repo, state_store, registry) are injected so the loop
    can be unit-tested without a real database.
    """

    def __init__(
        self,
        repo: WorkflowRepository,
        state_store: object,          # FileRunStateStore or PostgresRunStateStore
        registry: object,             # ExecutorRegistry
        worker_id: str,
        poll_interval: float = 1.0,
        supported_modalities: frozenset[str] | None = None,
        heartbeat_interval_seconds: float = 15.0,
    ) -> None:
        self._repo = repo
        self._state_store = state_store
        self._registry = registry
        self._worker_id = worker_id
        self._poll_interval = poll_interval
        self._supported_modalities = supported_modalities
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stopping = False

    def request_stop(self) -> None:
        self._stopping = True

    async def run_once(self) -> bool:
        """
        Claim and execute one pending workflow.

        Returns True when a workflow was claimed (regardless of outcome),
        False when the queue was empty.
        """
        supported = frozenset(self._registry.registered_task_types)
        record = await self._repo.claim_next_pending(
            self._worker_id, supported, self._supported_modalities
        )
        if record is None:
            return False

        wid = record.workflow_id
        log.info("[worker:%s] claimed workflow %s", self._worker_id, wid)
        workflow_started = time.monotonic()

        try:
            plan = BuildPlan.model_validate_json(record.plan_json)
            validate_build_plan(plan, REGISTERED_TASK_TYPES)
            runner = DAGRunner(self._registry, self._state_store)
            execution = asyncio.create_task(runner.run(plan))
            result = None
            next_heartbeat = time.monotonic() + self._heartbeat_interval_seconds
            next_progress_log = time.monotonic() + 60.0
            while not execution.done():
                await asyncio.wait({execution}, timeout=min(self._poll_interval, 0.5))
                now = time.monotonic()
                if now >= next_heartbeat:
                    try:
                        await self._repo.heartbeat(wid)
                    except Exception as heartbeat_exc:
                        # Observability must never abort otherwise healthy work.
                        log.warning(
                            "[worker:%s] workflow %s heartbeat failed: %s",
                            self._worker_id,
                            wid,
                            heartbeat_exc,
                        )
                    next_heartbeat = now + self._heartbeat_interval_seconds
                if now >= next_progress_log:
                    log.info(
                        "[worker:%s] workflow %s active elapsed_seconds=%.1f",
                        self._worker_id,
                        wid,
                        now - workflow_started,
                    )
                    next_progress_log = now + 60.0
                latest = await self._repo.get(wid)
                if (
                    latest is not None
                    and latest.status == PersistentWorkflowStatus.CANCEL_REQUESTED
                ):
                    await runner.cancel()
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                    await self._repo.mark_canceled(wid)
                    log.info("[worker:%s] workflow %s canceled", self._worker_id, wid)
                    return True
            result = execution.result()
            await self._repo.mark_succeeded(wid, result)
            log.info(
                "[worker:%s] workflow %s succeeded elapsed_seconds=%.1f",
                self._worker_id,
                wid,
                time.monotonic() - workflow_started,
            )
        except (PlanValidationError, WorkflowExecutionError, Exception) as exc:
            # Preserve compact structured-validation details while never storing
            # a traceback or an unbounded multi-line provider response.
            short = " ".join(str(exc).split())[:500] or exc.__class__.__name__
            log.warning("[worker:%s] workflow %s failed: %s", self._worker_id, wid, short)
            try:
                await self._repo.mark_failed(wid, short)
            except Exception as mark_exc:
                log.error(
                    "[worker:%s] could not mark %s failed: %s",
                    self._worker_id, wid, mark_exc,
                )
        return True

    async def run_forever(self) -> None:
        """Poll until stop is requested."""
        log.info("[worker:%s] starting", self._worker_id)
        while not self._stopping:
            try:
                claimed = await self.run_once()
                if not claimed:
                    await asyncio.sleep(self._poll_interval)
            except Exception as exc:
                log.error("[worker:%s] unexpected error: %s", self._worker_id, exc)
                await asyncio.sleep(self._poll_interval)
        log.info("[worker:%s] stopped", self._worker_id)


def _worker_id() -> str:
    hostname = socket.gethostname()
    pid = os.getpid()
    return f"worker-{hostname}-{pid}"


def _worker_profile() -> str:
    """Resolve an explicit worker profile with PIPELINE_MODE compatibility."""
    configured = os.environ.get("WORKER_PROFILE", "").strip().lower()
    if configured:
        return configured
    pipeline_mode = os.environ.get("PIPELINE_MODE", "reference").strip().lower()
    return "podcast-real" if pipeline_mode == "real" else "reference"


async def _main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")

    poll_interval = float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "1"))
    wid = _worker_id()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    profile = _worker_profile()
    from learning_pipeline.runtime.artifact_store import create_artifact_store
    artifact_store = create_artifact_store()
    if profile == "reference":
        from learning_pipeline.config import build_elearning_reference_registry
        registry = build_elearning_reference_registry(artifact_store)
        supported_modalities = frozenset({"video"})
    elif profile == "podcast-real":
        from learning_pipeline.config import build_real_registry, load_tts_settings
        registry = build_real_registry(
            settings=load_tts_settings(), artifact_store=artifact_store
        )
        supported_modalities = frozenset({"podcast"})
    elif profile == "video-real":
        from learning_pipeline.config import build_video_real_registry
        registry = build_video_real_registry(artifact_store=artifact_store)
        supported_modalities = frozenset({"video"})
    elif profile == "elearning-real":
        from learning_pipeline.config import (
            build_elearning_real_author_registry,
            load_elearning_author_settings,
        )
        registry = build_elearning_real_author_registry(
            artifact_store, load_elearning_author_settings()
        )
        supported_modalities = frozenset({"elearning"})
    elif profile == "elearning-real-manim":
        from learning_pipeline.config import (
            build_elearning_real_manim_registry,
            load_elearning_author_settings,
            load_manim_settings,
        )
        registry = build_elearning_real_manim_registry(
            artifact_store,
            load_elearning_author_settings(),
            load_manim_settings(),
        )
        supported_modalities = frozenset({"elearning"})
    else:
        raise SystemExit(
            "WORKER_PROFILE must be reference, podcast-real, video-real, "
            "elearning-real, or elearning-real-manim"
        )
    log.info("[worker] profile=%s capabilities=%s", profile, sorted(registry.task_types))

    pool: asyncpg.Pool = await create_pool(dsn)
    from learning_pipeline.db.migrate import run_migrations
    await run_migrations(pool)
    from learning_pipeline.db.repository import PostgresWorkflowRepository
    repo = PostgresWorkflowRepository(pool)
    state_store = PostgresRunStateStore(pool)

    loop = WorkerLoop(
        repo, state_store, registry, wid, poll_interval, supported_modalities
    )

    def _handle_signal(sig: int, _frame: object) -> None:
        log.info("[worker:%s] received signal %s — stopping after current task", wid, sig)
        loop.request_stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        await loop.run_forever()
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_main())
