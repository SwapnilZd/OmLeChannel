CREATE TABLE IF NOT EXISTS source_rlo_draft_jobs (
    job_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES source_objective_workspaces(workspace_id) ON DELETE CASCADE,
    workspace_revision INTEGER NOT NULL CHECK (workspace_revision >= 1),
    candidate_id TEXT NOT NULL,
    rlo_id TEXT NOT NULL,
    rlo_version TEXT NOT NULL,
    state TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, workspace_revision, candidate_id, rlo_id, rlo_version)
);

CREATE TABLE IF NOT EXISTS source_rlo_draft_revisions (
    job_id TEXT NOT NULL REFERENCES source_rlo_draft_jobs(job_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    payload JSONB NOT NULL,
    findings JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, revision)
);

CREATE TABLE IF NOT EXISTS source_rlo_draft_reviews (
    review_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES source_rlo_draft_jobs(job_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    action TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    note TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_published_rlo_dependencies (
    job_id TEXT NOT NULL REFERENCES source_rlo_draft_jobs(job_id) ON DELETE RESTRICT,
    source_version_id TEXT NOT NULL REFERENCES source_versions(source_version_id) ON DELETE RESTRICT,
    rlo_id TEXT NOT NULL,
    rlo_version TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, source_version_id)
);

CREATE INDEX IF NOT EXISTS source_published_rlo_dependencies_version_idx
    ON source_published_rlo_dependencies(source_version_id);
