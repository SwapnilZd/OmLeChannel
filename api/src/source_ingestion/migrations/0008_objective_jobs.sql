CREATE TABLE IF NOT EXISTS source_objective_jobs (
    job_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL REFERENCES source_processing_runs(run_id) ON DELETE RESTRICT,
    collection_id TEXT NOT NULL REFERENCES source_collections(collection_id) ON DELETE RESTRICT,
    workspace_id TEXT,
    workspace_revision INTEGER,
    workflow_stage TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    instructions JSONB,
    created_by TEXT,
    worker_id TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    retryable BOOLEAN,
    error_message TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS source_objective_jobs_queue_idx
    ON source_objective_jobs(processing_status, created_at);

CREATE TABLE IF NOT EXISTS source_objective_job_events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES source_objective_jobs(job_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT,
    actor TEXT,
    note TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_objective_job_events_job_idx
    ON source_objective_job_events(job_id, created_at);

CREATE TABLE IF NOT EXISTS source_objective_job_reviews (
    review_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES source_objective_jobs(job_id) ON DELETE CASCADE,
    workspace_revision INTEGER NOT NULL CHECK (workspace_revision >= 1),
    candidate_id TEXT NOT NULL,
    review_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    decided_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_objective_job_reviews_job_idx
    ON source_objective_job_reviews(job_id, review_kind, created_at);

CREATE TABLE IF NOT EXISTS source_objective_prompt_runs (
    prompt_run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES source_objective_jobs(job_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    prompt_filename TEXT NOT NULL,
    prompt_snapshot TEXT NOT NULL,
    model_alias TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    input_snapshot TEXT NOT NULL,
    input_artifact_ref TEXT,
    output_schema TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_objective_prompt_runs_job_idx
    ON source_objective_prompt_runs(job_id, created_at);
