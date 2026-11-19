UPDATE source_processing_runs
SET status = 'ready',
    completed_at = COALESCE(completed_at, now()),
    lease_expires_at = NULL
WHERE status = 'extraction_review'
  AND artifact_manifest_object_key IS NOT NULL;
