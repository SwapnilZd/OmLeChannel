ALTER TABLE source_processing_runs
    ADD COLUMN IF NOT EXISTS retryable BOOLEAN;
