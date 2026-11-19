CREATE TABLE IF NOT EXISTS source_documents (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    current_version_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_versions (
    source_version_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_documents(source_id) ON DELETE CASCADE,
    checksum TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    uploader TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    original_object_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_processing_runs (
    run_id TEXT PRIMARY KEY,
    source_version_id TEXT NOT NULL REFERENCES source_versions(source_version_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    worker_id TEXT,
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    retryable BOOLEAN,
    format_metadata JSONB,
    artifact_manifest_object_key TEXT,
    UNIQUE (source_version_id, stage, attempt)
);

CREATE INDEX IF NOT EXISTS source_processing_runs_claim_idx
    ON source_processing_runs (status, created_at);
