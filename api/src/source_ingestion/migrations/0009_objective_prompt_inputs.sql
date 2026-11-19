ALTER TABLE source_objective_prompt_runs
    ADD COLUMN IF NOT EXISTS input_snapshot TEXT;

UPDATE source_objective_prompt_runs
SET input_snapshot = '{}'
WHERE input_snapshot IS NULL;

ALTER TABLE source_objective_prompt_runs
    ALTER COLUMN input_snapshot SET NOT NULL;
