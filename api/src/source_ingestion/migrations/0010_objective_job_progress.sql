ALTER TABLE source_objective_jobs
    ADD COLUMN IF NOT EXISTS current_operation TEXT;

ALTER TABLE source_objective_jobs
    ADD COLUMN IF NOT EXISTS completed_operations INTEGER NOT NULL DEFAULT 0;

ALTER TABLE source_objective_jobs
    ADD COLUMN IF NOT EXISTS progress_detail JSONB NOT NULL DEFAULT '{}'::jsonb;
