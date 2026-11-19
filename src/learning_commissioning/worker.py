"""Polling worker for confirmed learning-commission assembly jobs."""

from __future__ import annotations

import asyncio
import os
import socket
import uuid

from .repository import PostgresPreviewRepository
from .services.assembly_runner import AssemblyJobRunner
from .services.retrieval import CatalogClient
from learning_pipeline.runtime.artifact_store import create_artifact_store


async def run_worker() -> None:
    repository = await PostgresPreviewRepository.create(os.environ["DATABASE_URL"])
    catalog = CatalogClient(os.getenv("RLO_CATALOG_URL", "http://api:8000"))
    runner = AssemblyJobRunner(
        repository,
        catalog,
        artifact_store=create_artifact_store(),
        mode=os.getenv("COMMISSIONING_ASSEMBLY_MODE", "reference"),
    )
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    poll_seconds = float(os.getenv("COMMISSIONING_WORKER_POLL_SECONDS", "1"))
    try:
        backfilled = await repository.ensure_jobs_for_confirmations()
        if backfilled:
            print(f"[commissioning-worker] queued {backfilled} existing confirmation(s)")
        while True:
            job = await repository.claim_next_job(worker_id)
            if job is None:
                await asyncio.sleep(poll_seconds)
                continue
            await runner.run(job)
    finally:
        await catalog.client.aclose()
        await repository.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
