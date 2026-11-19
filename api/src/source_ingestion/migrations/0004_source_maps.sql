CREATE TABLE IF NOT EXISTS source_map_artifacts (
    map_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    hierarchy_key TEXT NOT NULL,
    map_revision TEXT NOT NULL,
    model_alias TEXT NOT NULL,
    prompt_template TEXT NOT NULL,
    input_node_ids JSONB NOT NULL,
    token_usage JSONB NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope_kind, scope_id, hierarchy_key, map_revision)
);

CREATE INDEX IF NOT EXISTS source_map_artifacts_scope_idx
    ON source_map_artifacts (scope_kind, scope_id, map_revision);
