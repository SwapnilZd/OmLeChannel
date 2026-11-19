# Commissioning-to-Generation Pipeline Implementation Plan

## Goal

Connect the existing commissioning UI to the production pipeline so that one
confirmed learning request becomes one durable, observable generation job.
Users must be able to:

- submit and confirm a learning request once;
- see the job move through blueprint assembly, production planning, and execution;
- revisit a list of active, completed, and failed jobs;
- see meaningful live status while work is in progress; and
- download the primary generated deliverable after completion.

The backend remains authoritative. The browser never resubmits a generated
`CourseBlueprint`, `BuildPlan`, artifact URI, or workflow result.

## Current State

The implemented path currently stops after curriculum assembly:

```text
LearningCommissionRequest
  -> LearningRequestPreview
  -> ConfirmedLearningRequest
  -> CourseAssemblyRequest
  -> CourseBlueprint
  -> stop
```

The remaining production stages already exist independently:

```text
CourseBlueprint
  -> FormatSelectionResult
  -> ModalityPlan
  -> ModalityProductionPlan
  -> BuildPlan
  -> WorkflowResult
```

The work is primarily composition, persistence, worker routing, API read models,
artifact delivery, and UI integration. It does not require another instructional
planning contract.

## Architectural Decisions

### One end-to-end job identity

Continue using the existing `CommissioningJobRecord` and `commissioning_jobs`
row as the parent job. Add a nullable `workflow_id` when a `BuildPlan` is
submitted. Do not create a second unrelated browser-facing job identity.

The commissioning row owns request interpretation, confirmation, blueprint
assembly, and production planning. `workflow_runs` remains the source of truth
for deterministic execution. Job APIs join the two records into one read model.

### Automatic backend handoff

Confirmation continues to enqueue the existing commissioning job. After the
blueprint is persisted, the same asynchronous orchestration continues into
format selection, modality planning, and workflow planning. No second upload of
the contract is required.

The first implementation uses `FormatSelectionMode.AUTO`. An explicit format
control can later be added to the UI using the existing
`FormatSelectionRequest`; it must not introduce a parallel modality contract.

### Reuse existing pipeline contracts

Reuse these contracts without wrapping their instructional content in new
models:

- `CourseBlueprint`
- `FormatSelectionRequest` and `FormatSelectionResult`
- `ModalityPlan`
- `ModalityProductionPlan`
- `BuildPlan`
- `WorkflowResult`

New types are limited to operational API read models such as a paginated job
summary and downloadable-deliverable descriptor.

### Asynchronous planning and execution

Do not make the confirmation HTTP request wait for several model calls and
content-generation tasks. Confirmation returns the durable job immediately.
Workers advance the job, and the UI polls a read endpoint.

### Secure downloads

Download endpoints derive allowed files from the completed
`WorkflowResult.deliverables`. They never accept an arbitrary filesystem path or
`artifact://` URI from the browser. Every download is re-resolved server-side,
checked against the job, and read through `ArtifactStore`.

## Target Flow

```text
Commission UI
  -> POST confirmation
  -> commissioning job: queued_for_assembly

Commissioning/planning worker
  -> assembling_blueprint
  -> selecting_format
  -> planning_modality
  -> planning_workflow
  -> persist planning artifacts
  -> submit BuildPlan
  -> queued_for_execution

Compatible execution worker
  -> executing (task progress available)
  -> completed | failed

Jobs UI
  -> polls job list/detail
  -> shows current stage and task progress
  -> exposes download when completed
```

## Job State Model

Expand `CommissioningJobState` to describe pre-execution work:

| State | Meaning |
|---|---|
| `queued_for_assembly` | Confirmation is durable and waiting for a planning worker. |
| `assembling_blueprint` | The confirmed RLO snapshot is becoming a `CourseBlueprint`. |
| `selecting_format` | The backend is selecting a feasible delivery modality. |
| `planning_modality` | The selected modality's instructional scene plan is being created. |
| `planning_workflow` | The production plan and executable DAG are being created. |
| `queued_for_execution` | A validated `BuildPlan` exists in `workflow_runs`. |
| `failed` | Assembly or planning failed before workflow execution. |

Execution states are derived from the linked `workflow_runs` row:

| Workflow status | Public job status |
|---|---|
| `pending` | `queued_for_execution` |
| `running` | `executing` |
| `succeeded` | `completed` |
| `failed` | `failed` |

Do not copy workflow status into two tables on every transition. The job query
should join or load both sources and compute the public state consistently.

For running workflows, derive task progress from `workflow_run_state`:

- completed task count;
- total task count;
- currently runnable/running task names when available; and
- latest update time.

Do not fabricate percentage completion from task counts because tasks have very
different durations. Display `3 of 7 tasks complete` and the named stage.

## Persistence Changes

### Commissioning job columns

Add idempotent migrations for these nullable columns:

- `selected_modality TEXT`
- `format_selection JSONB`
- `modality_plan JSONB`
- `modality_trace JSONB`
- `production_plan JSONB`
- `build_plan JSONB`
- `workflow_planning_trace JSONB`
- `workflow_id TEXT UNIQUE`
- `planning_started_at TIMESTAMPTZ`
- `execution_submitted_at TIMESTAMPTZ`

Retain the existing blueprint, report, and assembly trace columns. Persist each
stage before advancing to the next so a failure is diagnosable and completed
planning artifacts remain auditable.

Add repository operations that update exactly one transition at a time:

- `mark_blueprint_completed(...)`
- `mark_format_selected(...)`
- `mark_modality_planned(...)`
- `mark_workflow_planned(...)`
- `link_workflow(...)`
- `list_jobs(...)`
- `get_job_view(...)`

Every transition must assert the expected prior state in its `UPDATE` clause.
Unexpected or duplicate transitions must not silently overwrite artifacts.

### Workflow capability routing

Add `required_task_types TEXT[]` to `workflow_runs`. Populate it from the
validated `BuildPlan` at submission time and index it for claiming.

Each worker declares a profile and its supported task types, for example:

- `reference`
- `podcast-real`
- `video-real`
- `elearning-real`

`claim_next_pending` must claim only rows whose required task types are a subset
of the worker's supported task types. This prevents a podcast worker from
claiming an e-learning job and prevents multiple specialized workers from racing
for incompatible plans.

The worker must build its executor registry from its declared profile. Remove
the current assumption that every `PIPELINE_MODE=real` worker is a podcast TTS
worker.

## Backend Composition

### Generation planning service

Create a service under `src/learning_pipeline/services/` with one public method:

```python
async def plan_generation(
    blueprint: CourseBlueprint,
    *,
    request_id: str,
) -> GenerationPlanningResult:
    ...
```

`GenerationPlanningResult` may be an internal dataclass holding the already
existing result contracts. It is not a new persisted instructional contract.

Responsibilities:

1. Build an automatic `FormatSelectionRequest` for the supplied blueprint.
2. Run `FormatSelectionService` using capabilities available in the deployment.
3. Dispatch to the selected podcast, video, or e-learning modality planner.
4. Run the matching workflow planner.
5. Compile and validate the `BuildPlan`.
6. Return all stage results for atomic persistence at their respective
   boundaries.

Use `CatalogRLORepository` so every context resolver loads the exact RLO
versions already locked into the blueprint. Do not reload candidates or rerun
commissioning retrieval.

Extract planner and resolver construction from CLI-only code into shared
composition factories. The CLI and commissioning worker should call the same
factories rather than maintaining separate planner wiring.

In reference mode, use deterministic format selection and fake planners. In
real mode, use the configured LiteLLM aliases and real planners. Provider model
selection remains exclusively in `litellm/config.yaml`.

### Commissioning job runner

Refactor `AssemblyJobRunner` into an end-to-end planning runner, or introduce a
coordinator used by it:

1. load the immutable preview and confirmation;
2. assemble and persist the blueprint;
3. run and persist generation planning stages;
4. validate the resulting `BuildPlan`;
5. create the pending `workflow_runs` row idempotently;
6. link `commissioning_jobs.workflow_id`; and
7. set `queued_for_execution`.

Use stable IDs derived from the commissioning job ID:

- planning request ID: `planning-{job_id}`
- workflow ID: `workflow-{job_id}`

This makes retries converge on the same cache and workflow record.

## API Plan

Keep the existing preview, confirmation, blueprint, report, and trace endpoints.
Add the following endpoints to the commissioning API.

### List jobs

```http
GET /api/commissioning-jobs?scope=all|active|completed|failed&limit=50&cursor=...
```

Return newest first with:

- job ID and request ID;
- course title or confirmed goal;
- created and updated timestamps;
- selected modality, when known;
- public status and current stage label;
- task counts for executing jobs;
- concise safe error summary for failed jobs; and
- whether downloadable content is available.

Use cursor pagination based on `(created_at, job_id)`, not an unbounded table
scan.

### Job detail and polling

Extend the existing endpoint:

```http
GET /api/commissioning-jobs/{job_id}
```

Return the joined planning/execution view. Include a `poll_after_ms` hint while
the job is active and omit it for terminal jobs. A two-second default is
appropriate locally; use bounded exponential backoff after repeated unchanged
responses.

### Deliverable listing

```http
GET /api/commissioning-jobs/{job_id}/deliverables
```

Only return entries derived from `WorkflowResult.deliverables`. Each entry has:

- an opaque or server-derived deliverable ID;
- display filename;
- media type;
- size when available;
- primary/secondary designation; and
- a backend download URL.

Primary mappings:

- podcast: `audio_uri` (`audio/wav`);
- video: `video_uri` (`video/mp4`);
- e-learning: `bundle_zip.uri` (`application/zip`).

Secondary outputs such as captions, cost reports, manifests, course JSON, and
standalone HTML may also be listed, but the primary content appears first.

### Download

```http
GET /api/commissioning-jobs/{job_id}/deliverables/{deliverable_id}/download
```

Requirements:

- reject non-terminal jobs with `409`;
- return `404` if the derived deliverable ID is not part of that job's result;
- resolve only `artifact://` references through the configured artifact store;
- stream the response instead of reading large videos fully into API memory;
- set `Content-Type`, `Content-Length` when known, and a safe
  `Content-Disposition: attachment` filename;
- prevent path traversal through the existing artifact-store boundary; and
- never expose the local artifact root in API responses.

The commissioning API and execution workers share the MinIO-backed
`ArtifactStore`. No host artifact volume is mounted; downloads resolve logical
artifact references from the configured object bucket.

## UI Plan

### Navigation and jobs page

Add a persistent `Jobs` link beside `RLO Registry` and `Commission Learning`.
Serve a dedicated jobs page, for example `/jobs`, so users can revisit work
after leaving the commissioning form or refreshing the browser.

The jobs page contains:

- **In progress** — queued, assembling, planning, and executing jobs;
- **Completed** — successful jobs with modality and download action;
- **Failed** — failed jobs with a concise error and job ID.

Use accessible tables or cards that collapse cleanly on narrow screens. Status
must be conveyed by text as well as color.

### Live updates

On page load, request all recent jobs. Poll only while at least one visible job
is active:

- poll every two seconds initially;
- update rows in place without resetting focus or scroll position;
- stop polling terminal jobs;
- back off to five and then ten seconds after unchanged responses;
- pause while the page is hidden and refresh immediately when visible again;
- show the last successful refresh time and a recoverable connection warning.

Server-Sent Events can be added later, but polling is the initial implementation
because the APIs and deployment are already request/response based.

### Submission experience

After confirmation:

- show the durable job ID immediately;
- replace the blueprint-only polling copy with the end-to-end stage label;
- link to the jobs page;
- continue showing the blueprint as soon as that intermediate artifact exists;
- do not imply the course is complete when only the blueprint is complete; and
- show the primary download button only after execution succeeds.

The first release uses automatic format selection. Display the selected
modality as soon as it is available.

### Download experience

Completed job rows show one primary action:

- `Download podcast`
- `Download video`
- `Download course package`

A details panel may expose secondary artifacts. If an older/reference result
contains only a `fake://` URI, show `No downloadable artifact` rather than a
broken link.

## Implementation Sequence

### Primary implementation surfaces

The work should be concentrated in these existing areas:

- `src/learning_commissioning/services/assembly_runner.py` for the automatic
  post-blueprint handoff;
- `src/learning_commissioning/repository.py` for parent-job persistence,
  guarded transitions, and the joined job read model;
- `src/learning_commissioning/api/app.py` for job status, deliverable, and
  download endpoints;
- `src/learning_commissioning/worker.py` for end-to-end planning composition;
- `src/learning_pipeline/services/` and `src/learning_pipeline/cli.py` for
  shared planner factories rather than CLI-only wiring;
- `src/learning_pipeline/db/repository.py` and
  `src/learning_pipeline/worker/main.py` for capability-aware execution
  claiming;
- `src/learning_pipeline/runtime/artifact_store.py` for safe streaming access;
- `api/src/app.py` and `api/templates/` for the Jobs route, navigation, and
  browser UI; and
- the Compose configuration for worker profiles and the read-only artifact
  mount used by downloads.

Keep migrations next to the repositories that own their tables and mirror each
change in the existing commissioning, persistence, worker, API, and browser
test suites.

### Phase 1 — Persistence and job read model

- [x] Add idempotent commissioning and workflow migrations.
- [x] Expand `CommissioningJobState` and `CommissioningJobRecord` operational
  fields.
- [x] Add guarded repository transition methods.
- [x] Add capability-aware workflow submission and claiming.
- [x] Add joined job list/detail repository queries.
- [x] Add migration and concurrency tests.

Exit gate: a job can persist every planning stage, link one workflow, and be
read as one coherent status without running a live model.

### Phase 2 — Shared generation planning composition

- [x] Extract modality-specific planner factories from `cli.py`.
- [x] Implement the generation planning service and modality dispatcher.
- [x] Use the catalog-backed exact-version RLO repository.
- [x] Persist format, modality, workflow, and build-plan artifacts.
- [x] Add reference-mode end-to-end tests for all three modalities.
- [x] Add failure tests for infeasible format selection and invalid plans.

Exit gate: a persisted commissioning blueprint produces a validated `BuildPlan`
without shelling out to CLI commands.

### Phase 3 — End-to-end worker handoff

- [x] Continue the commissioning worker through generation planning.
- [x] Submit the `BuildPlan` idempotently and link `workflow_id`.
- [x] Build execution registries from explicit worker profiles.
- [x] Restrict each worker claim to compatible task types.
- [x] Update Compose profiles and health/dependency configuration.
- [x] Add tests proving incompatible workers cannot claim a job.

Exit gate: confirmation produces a queued execution workflow, and exactly one
compatible worker can claim it.

### Phase 4 — Job and download APIs

- [x] Add paginated job listing with active/completed/failed filters.
- [x] Extend job detail with workflow and task progress.
- [x] Add deliverable discovery from `WorkflowResult`.
- [x] Add safe artifact streaming downloads.
- [x] Mount the artifact volume read-only into the API.
- [x] Add API tests for polling, pagination, authorization boundaries, missing
  artifacts, and path traversal.

Exit gate: a completed workflow can be discovered from its commissioning job and
its primary artifact can be downloaded through the API.

### Phase 5 — Jobs UI

- [x] Add the Jobs navigation entry and page.
- [x] Render in-progress, completed, and failed sections.
- [x] Implement visibility-aware polling and in-place updates.
- [x] Show intermediate blueprint availability without marking the job complete.
- [x] Add primary and secondary download actions.
- [x] Add responsive, keyboard, and screen-reader checks.
- [x] Add browser-level tests for submission-to-download behavior.

Exit gate: a user can submit once, leave or refresh the page, return to Jobs,
watch status advance, and download the completed content.

## Verification Matrix

### Contract and planning tests

- Existing contracts still reject unknown instructional fields.
- The persisted blueprint—not browser JSON—is supplied to planning.
- Exact RLO IDs and versions survive every planning stage.
- Automatic format selection chooses only a deployed workflow.
- Each modality produces a valid, matching `BuildPlan`.

### Persistence and concurrency tests

- Duplicate confirmation creates one parent job.
- Planning retry creates one workflow ID and one `workflow_runs` row.
- Concurrent planning workers claim a job once.
- Incompatible execution workers never claim the plan.
- Joined status is correct for every workflow state.

### Download tests

- Podcast WAV, video MP4, and e-learning ZIP download with correct media types.
- A deliverable from one job cannot be downloaded through another job ID.
- Arbitrary URIs, absolute paths, and traversal paths are rejected.
- Missing artifacts return a stable error without leaking filesystem paths.
- In-progress and failed jobs do not expose download actions.

### UI tests

- Newly submitted jobs appear in the in-progress list.
- Polling updates stages without duplicating rows.
- Polling stops after terminal status and pauses on hidden pages.
- Completed jobs move to the completed section and expose the right primary
  download label.
- Refreshing or reopening the page restores jobs from the backend rather than
  browser-local state.

### End-to-end acceptance

At least one reference e-learning run must pass this full path in Docker:

```text
browser confirmation
  -> persisted blueprint
  -> automatic format selection
  -> modality plan
  -> production plan
  -> BuildPlan
  -> compatible worker execution
  -> completed Jobs entry
  -> downloadable ZIP
```

Repeat the same acceptance path for real podcast, video, and e-learning workers
when their provider credentials and infrastructure are available.

## Operational and Security Requirements

- Add authentication and authorization before exposing jobs outside local
  development. Job listing and downloads must be scoped to the requesting user
  or permitted cohort.
- Do not place prompts, full RLO payloads, API keys, or provider responses in job
  list responses or logs.
- Keep concise public errors separate from detailed internal diagnostics.
- Apply retention consistently to database job records and artifact files.
- Record model aliases, prompt versions, input hashes, and plan hashes in the
  existing trace artifacts.
- Use bounded retries and idempotent IDs; do not silently replan during runtime
  execution.

## Explicit Non-Goals

- Replacing the existing RLO, blueprint, modality, production, or execution
  contracts.
- Letting the browser construct or edit a `BuildPlan`.
- Replanning after execution has started.
- Returning provider download URLs directly to the browser.
- Implementing WebSockets or Server-Sent Events in the first jobs UI release.
- Adding cross-job bulk deletion or artifact lifecycle management in this
  implementation.

## Definition of Done

- One confirmation creates one durable end-to-end job.
- The backend automatically hands its persisted blueprint into generation
  planning.
- Every job stage is durable and visible through one status endpoint.
- A jobs page shows active, completed, and failed work after refresh.
- Active jobs update automatically without manual page reload.
- Only compatible workers claim generated plans.
- Completed jobs expose a safe download of the primary generated content.
- The full reference path runs without live provider credentials.
- Existing commissioning and pipeline test suites remain green.
