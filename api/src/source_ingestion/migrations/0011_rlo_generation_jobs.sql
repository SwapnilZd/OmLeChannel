CREATE TABLE IF NOT EXISTS source_rlo_generation_batches (
    batch_id TEXT PRIMARY KEY,
    objective_job_id TEXT NOT NULL UNIQUE REFERENCES source_objective_jobs(job_id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    workspace_revision INTEGER NOT NULL,
    collection_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE source_rlo_draft_jobs
    ADD COLUMN IF NOT EXISTS batch_id TEXT REFERENCES source_rlo_generation_batches(batch_id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS current_operation TEXT,
    ADD COLUMN IF NOT EXISTS completed_operations INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS error_message TEXT;

CREATE INDEX IF NOT EXISTS source_rlo_draft_queue_idx
    ON source_rlo_draft_jobs(state, created_at);

CREATE TABLE IF NOT EXISTS source_rlo_generation_checkpoints (
    job_id TEXT NOT NULL REFERENCES source_rlo_draft_jobs(job_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (job_id, operation)
);

CREATE TABLE IF NOT EXISTS source_rlo_generation_prompt_runs (
    prompt_run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES source_rlo_draft_jobs(job_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    prompt_filename TEXT NOT NULL,
    prompt_snapshot TEXT NOT NULL,
    model_alias TEXT NOT NULL,
    input_snapshot TEXT NOT NULL,
    output_schema TEXT NOT NULL,
    output_snapshot TEXT NOT NULL,
    usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS source_rlo_generation_prompt_runs_job_idx
    ON source_rlo_generation_prompt_runs(job_id, created_at);
