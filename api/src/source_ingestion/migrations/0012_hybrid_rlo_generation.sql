ALTER TABLE source_rlo_generation_batches
    ADD COLUMN IF NOT EXISTS finalized INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS collection_validation_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS collection_validated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS source_rlo_generation_collection_queue_idx
    ON source_rlo_generation_batches(finalized, state, collection_validated_at);
