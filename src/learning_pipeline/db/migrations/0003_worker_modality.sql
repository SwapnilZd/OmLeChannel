-- Keep specialized workers within their declared top-level modality even when
-- their executor registry contains shared capabilities.
ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS modality TEXT;

UPDATE workflow_runs
SET required_task_types = ARRAY(
        SELECT DISTINCT task->>'task_type'
        FROM jsonb_array_elements(plan_json::jsonb->'tasks') AS task
        ORDER BY task->>'task_type'
    ),
    modality = COALESCE(modality, plan_json::jsonb->>'modality')
WHERE cardinality(required_task_types) = 0 OR modality IS NULL;
