CREATE TABLE IF NOT EXISTS source_learning_briefs (
    brief_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES source_collections(collection_id) ON DELETE CASCADE,
    source_map_revision TEXT NOT NULL,
    brief_revision TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (collection_id, brief_revision)
);

CREATE TABLE IF NOT EXISTS source_objective_workspaces (
    workspace_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES source_collections(collection_id) ON DELETE CASCADE,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_objective_workspace_revisions (
    workspace_id TEXT NOT NULL REFERENCES source_objective_workspaces(workspace_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    brief_id TEXT NOT NULL REFERENCES source_learning_briefs(brief_id),
    payload JSONB NOT NULL,
    model_metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, revision)
);

CREATE TABLE IF NOT EXISTS source_objective_decisions (
    workspace_id TEXT NOT NULL REFERENCES source_objective_workspaces(workspace_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    candidate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    decided_by TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, revision, candidate_id)
);
