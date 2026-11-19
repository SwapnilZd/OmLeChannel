-- Phase 6 initial schema
-- workflow_runs: persistent record of every submitted BuildPlan
-- workflow_run_state: latest RunSnapshot produced by WorkflowRunner

CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_id   TEXT PRIMARY KEY,
    plan_json     TEXT NOT NULL,
    plan_hash     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    result_json   TEXT,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at    TIMESTAMPTZ,
    claimed_by    TEXT,
    completed_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS workflow_run_state (
    workflow_id   TEXT PRIMARY KEY REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    snapshot_json TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
