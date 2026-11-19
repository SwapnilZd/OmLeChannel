"""Continuously process durable seven-part RLO generation jobs."""

from __future__ import annotations

import logging
import os
import time

from src.source_ingestion.repository import init_db

from . import draft_repository
from .generation import RLOGenerationService


logger = logging.getLogger(__name__)
POLL_SECONDS = float(os.environ.get("RLO_WORKER_POLL_SECONDS", "1"))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    logger.info("[rlo-generation] Worker started")
    service = RLOGenerationService()
    while True:
        try:
            job = draft_repository.claim_next_draft_job()
            if job is not None:
                logger.info("[rlo-generation] Processing %s", job.job_id)
                service.process(job.job_id)
                continue
            batch = draft_repository.claim_next_collection_validation_batch()
            if batch is not None:
                logger.info(
                    "[rlo-generation] Validating finalized batch %s", batch.batch_id
                )
                service.process_collection(batch.batch_id)
                continue
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            return
        except Exception:
            logger.exception("[rlo-generation] Worker iteration failed")


if __name__ == "__main__":
    main()
