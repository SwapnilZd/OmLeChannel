-- Route workflow plans only to workers that can execute every required task.
ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS required_task_types TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS workflow_runs_pending_capabilities_idx
    ON workflow_runs (created_at)
    WHERE status = 'pending';
