CREATE TABLE IF NOT EXISTS source_objective_model_checkpoints (
    job_id TEXT NOT NULL REFERENCES source_objective_jobs(job_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    model_alias TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    input_sha256 TEXT,
    output_schema TEXT NOT NULL,
    output_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, operation)
);
