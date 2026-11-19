CREATE TABLE IF NOT EXISTS source_collections (
    collection_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_collection_members (
    collection_id TEXT NOT NULL REFERENCES source_collections(collection_id) ON DELETE CASCADE,
    source_version_id TEXT NOT NULL REFERENCES source_versions(source_version_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    authority_note TEXT,
    PRIMARY KEY (collection_id, source_version_id),
    UNIQUE (collection_id, ordinal)
);
