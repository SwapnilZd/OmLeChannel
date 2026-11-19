# Learning Commissioning Entrypoint — Implementation Plan

Last updated: 2026-07-22

Status: Phases 0–5 implemented; operational hardening remains.

## Outcome

Build a browser-based commissioning entrypoint where a Growth and Development
employee or manager describes a learning need for a cohort. The system will:

1. interpret the request into a focused, auditable search intent;
2. retrieve relevant, approved, versioned RLO candidates;
3. explain candidate relevance and identify content gaps;
4. require the requester to confirm or adjust the candidate set; and
5. use the confirmed candidates to produce a `CourseBlueprint`.

The first release stops after curriculum assembly. It does not select a
delivery format, create a modality plan, compile a `BuildPlan`, or execute
production tools.

## Confirmed Product Decisions

- [x] Requests target a cohort or audience archetype, not an individual learner.
- [x] Candidate RLOs are shown to the requester before curriculum assembly.
- [x] The requester can include, exclude, or require candidates before confirming.
- [x] Insufficient relevant content is a first-class outcome shown in the UI.
- [x] The system must not generate a low-confidence blueprint merely because
  some RLOs exist in the database.
- [x] The first release produces a `CourseBlueprint` and assembly audit artifacts.
- [x] This is a separate commissioning workstream that feeds the existing
  `learning_pipeline` contracts and services.
- [x] Avoid changes under `src/learning_pipeline/` while another developer is
  actively working there.

## Ownership Boundary

New feature code should live in a sibling package:

```text
src/
  learning_commissioning/
    api/
    contracts/
    discovery/
    interpretation/
    orchestration/
    persistence/
    templates/
```

Existing code under `src/learning_pipeline/` is treated as a downstream public
dependency. The commissioning package may import documented public contracts
and services, but it must not change their implementation as part of this
workstream.

Expected existing dependencies:

- `learning_pipeline.contracts.CourseAssemblyRequest`
- `learning_pipeline.contracts.CourseAssemblyConstraints`
- `learning_pipeline.contracts.AssemblyRLOCandidate`
- `learning_pipeline.contracts.LearnerContext`
- `learning_pipeline.contracts.CourseBlueprint`
- `learning_pipeline.planners.curriculum.service.CourseAssemblyService`
- `learning_pipeline.repository.RLORepository`

If a genuine compatibility problem is found in `src/learning_pipeline/`, record
it as an integration issue and coordinate it separately. Do not silently expand
this feature into a refactor of the orchestration package.

## System Boundary

```text
Commissioning UI
    │
    ▼
LearningCommissionRequest
    │
    ▼
Request Interpreter ───────► LearningSearchIntent + interpretation trace
    │
    ▼
Versioned RLO Retrieval ───► RLOCandidateSet + ContentGapReport
    │
    ▼
Human Confirmation
    │
    ▼
ConfirmedLearningRequest
    │ deterministic adapter
    ▼
CourseAssemblyRequest       existing learning_pipeline contract
    │
    ▼
CourseAssemblyService       existing learning_pipeline service
    │
    ▼
CourseBlueprint + report + trace
```

The model interprets semantic intent. Deterministic code owns filters, version
selection, score fusion, sufficiency decisions, candidate snapshots, contract
construction, and state transitions.

## Proposed Commissioning Contracts

These contracts belong under `src/learning_commissioning/contracts/`, not
`src/learning_pipeline/contracts/`.

### `AudienceProfile`

Represents the target cohort without implying that it is one named learner.

- `roles: tuple[str, ...]`
- `deloitte_levels: tuple[Literal[25, 35, 45, 55, 65], ...]`
- `current_proficiency: TopicProficiency`
- `target_proficiency: TopicProficiency`
- `industries: tuple[str, ...]`
- `service_lines: tuple[str, ...]`
- `business_context: dict[str, str]`
- `language: str`
- `locale: str`

The deterministic assembly adapter will project this cohort profile into the
existing `LearnerContext` as an audience archetype. The projection policy must
be explicit and versioned.

### `LearningCommissionRequest`

Authoritative user input. Inferred model fields must never be written back into
this contract as though the user supplied them.

- `request_id`
- `request_text`
- `audience: AudienceProfile`
- `stated_goals`
- `duration_limit_minutes`
- `required_rlo_ids`
- `excluded_rlo_ids`
- `minimum_target_proficiency`
- `brand_contract`

### `LearningSearchIntent`

Structured output from the request interpreter.

- `primary_subject`
- `subject_facets` — one to four focused semantic subjects
- `skills`
- `desired_outcomes`
- `required_concepts`
- `excluded_concepts`
- `ambiguities`
- `search_queries` — one normalized query per subject facet

The model must not set governance filters, score thresholds, Qdrant fields,
candidate limits, RLO IDs, or RLO versions.

### `SearchInterpretationTrace`

- request and intent hashes;
- prompt version and model alias;
- provider request ID;
- token/cost metadata when available;
- warnings and deterministic fallback reason.

### `RLOCandidateMatch`

- exact `rlo_id` and `rlo_version`;
- title, topic, domain, level, duration, and governance state;
- vector score by subject facet;
- reciprocal-rank-fusion score;
- deterministic facet boosts;
- final normalized score or relevance band;
- match reasons;
- source query IDs;
- storage reference and index revision.

### `ContentGap`

- subject facet or required outcome that lacks sufficient support;
- severity: `blocking` or `warning`;
- nearest weak matches, if any;
- filters that removed otherwise related content;
- human-readable recommendation to add or revise RLOs.

### `ContentGapReport`

- `sufficient: bool`;
- covered subject facets and goals;
- gaps;
- retrieval-policy version;
- explanation suitable for the UI.

### `LearningRequestPreview`

- original commission request;
- interpreted search intent;
- ranked candidates;
- content-gap report;
- interpretation and retrieval traces;
- `confirmation_allowed` derived deterministically from the gap report.

### `ConfirmedLearningRequest`

- preview ID and immutable preview hash;
- selected candidate ID/version pairs;
- candidates explicitly marked required;
- excluded candidate ID/version pairs;
- confirmation actor and timestamp;
- optional requester notes.

### `CommissioningJobRecord`

- job ID and request ID;
- immutable confirmed-request hash;
- state;
- generated `CourseAssemblyRequest` snapshot;
- blueprint/report/trace artifact references;
- error code and safe error summary;
- timestamps.

Initial states:

```text
draft
interpreting
retrieving
awaiting_confirmation
blocked_content_gap
queued_for_assembly
assembling
succeeded
failed
```

## RLO Catalog Prerequisites

The current catalog overwrites documents and vectors by `rlo_id`, while the
assembly contracts require exact ID/version snapshots. Version-safe catalog
behavior is a release prerequisite.

- [x] Store RLO objects under a versioned key such as
  `rlos/{rlo_id}/{rlo_version}.json`.
- [x] Preserve a deterministic current-version pointer or policy without
  deleting historical versions.
- [x] Key Qdrant points by `(rlo_id, rlo_version)` rather than `rlo_id` alone.
- [x] Add `rlo_version`, `language`, `locale`, governance state, duration,
  audience, competency, industry, role, service-line, and regulatory metadata
  to the retrieval payload.
- [x] Create Qdrant payload indexes for every hard-filter field.
- [x] Define how deprecated, archived, draft, and superseded RLOs behave.
- [x] Default production discovery to approved and active RLO versions.
- [x] Provide exact-version retrieval through the catalog API.
- [x] Provide a migration/reindex command for existing stored RLOs.
- [x] Verify every indexed ID/version can be hydrated and validated.

Implemented catalog policy: the highest semver-like release is current; older
versions remain exact-addressable but are inactive. Discovery defaults to
`approved` plus active. Draft, deprecated, and archived content is therefore
excluded unless a caller explicitly requests that state. A failed write of a
new current vector deactivates stale versions rather than silently serving an
older version as current.

## Schema Compatibility Prerequisite

The ingestion service validates `rlo_schema.RLO`, while curriculum assembly
loads `learning_pipeline.contracts.RLODocument`. This feature must cross that
boundary without modifying either package casually.

- [x] Implement a commissioning-owned adapter from stored `rlo_schema.RLO`
  JSON to the existing `RLODocument` public contract.
- [x] Preserve open-shaped `canonical_content` values without topic-specific
  assumptions.
- [x] Validate every stored RLO through the adapter in Docker.
- [x] Return a typed compatibility error for indexed documents that cannot be
  used by curriculum assembly.
- [x] Exclude incompatible RLOs from confirmation and report the reason.

Longer term, the schema packages should converge, but that refactor is outside
this workstream.

## Search and Retrieval Policy

### Query interpretation

- [x] Use one structured LiteLLM call to extract subject facets, skills, and
  outcomes from the free-text request.
- [x] Keep cohort metadata separate from the semantic subject query.
- [x] Limit interpretation to one to four focused search queries.
- [x] Treat all user text as untrusted data, not prompt instructions.
- [x] Validate structured output and use a deterministic raw-text fallback if
  interpretation is unavailable.
- [x] Cache by normalized request hash, prompt version, and model alias.

### Retrieval

- [x] Batch-embed the normalized subject queries through the LiteLLM
  `rlo-catalog-embedding` alias.
- [x] Search each subject facet independently.
- [x] Hard-filter by approved governance, active version, language/locale,
  compatibility, and explicit exclusions.
- [x] Over-fetch a bounded result set per facet.
- [x] Fuse facet results deterministically using reciprocal-rank fusion.
- [x] Apply deterministic boosts for industry, role, service line,
  competency, regulatory context, level, and proficiency compatibility.
- [x] Treat industry as a soft boost unless the requester explicitly marks it
  as a hard requirement.
- [x] Select at most one active version of the same logical RLO.
- [x] Return a bounded candidate set suitable for the assembly context budget.
- [x] Hydrate full RLO documents only after ranking and eligibility checks.

### Relevance and sufficiency

Raw cosine score alone is not a sufficient content policy. Thresholds must be
calibrated against a judged retrieval set.

- [x] Create synthetic and representative request-to-RLO relevance judgments.
- [x] Label expected, acceptable, weak, and forbidden candidates.
- [x] Define relevance bands from evaluated retrieval behavior.
- [x] Require at least one acceptable candidate for every required subject
  facet or outcome.
- [x] Produce a blocking gap when a required facet has no acceptable match.
- [x] Produce a warning for partial coverage or weak audience/context fit.
- [x] Do not use a simple minimum candidate count as the sufficiency rule; one
  strong, composable RLO may legitimately satisfy a narrow request.
- [x] Disable confirmation when blocking gaps exist.
- [x] Show: “The catalog does not contain sufficient approved RLO content for
  this request. Add or revise RLOs before creating a course blueprint.”

## Catalog Search API

The RLO catalog service owns storage and the Qdrant collection. It should expose
retrieval primitives; the commissioning service owns request interpretation,
fusion policy, confirmation, and assembly orchestration.

- [x] Add an exact-version RLO endpoint.
- [x] Add a filtered semantic search endpoint that accepts normalized query
  text and typed filter fields.
- [x] Return compact search hits, not full RLO bodies.
- [x] Support batch queries so one commissioning request does not make one HTTP
  round trip per subject facet.
- [x] Include index revision and embedding-model alias in responses.
- [x] Do not expose raw vectors.
- [ ] Add service-to-service authentication as a deployment concern before
  production release.

Proposed endpoints:

```text
POST /api/rlo-search/batch
GET  /api/rlos/{rlo_id}/versions/{rlo_version}
GET  /api/rlos/{rlo_id}/versions
```

## Smart Candidate Curation

Vector ranking supplies recall and deterministic relevance evidence; it does
not make the final instructional-design decision.

- [x] Hydrate the top ten exact candidate versions for a bounded smart review.
- [x] Send objectives, concepts, performance context, framework evidence, and
  retrieval scores through the OpenAI-compatible LiteLLM endpoint.
- [x] Use the purpose-specific `commissioning-candidate-curation` alias; its
  provider model is selected only in `litellm/config.yaml`.
- [x] Require one strict include/optional/exclude decision for every reviewed
  ID/version and reject identity drift.
- [x] Direct the curator to distinguish related frameworks and levels of
  analysis rather than combining them based on topical similarity.
- [x] Preserve deterministic exclusion for candidates below the weak relevance
  threshold.
- [x] Persist the curation strategy, framework approach, per-candidate
  rationale, model trace, and token usage with the preview.
- [x] Use recommendations only as UI defaults; allow the requester to override
  include/exclude choices for every non-forbidden candidate.
- [x] Provide a deterministic relevance-band fallback when smart curation is
  unavailable or returns invalid identities.

Live Docker verification on 2026-07-22 reviewed ten exact profiles using
GPT-5.5 with no fallback (the call used the earlier generic alias before the
purpose-specific alias was introduced). The model recommended the two ADKAR
barrier-diagnosis/intervention RLOs and excluded every Kotter candidate,
explicitly identifying Kotter as a different framework and level of analysis.
The selected ADKAR set then passed exact-version confirmation.

## Commissioning API

The commissioning service should be independently deployable and should not be
added to the deterministic execution API.

```text
POST /api/learning-requests/preview
GET  /api/learning-requests/previews/{preview_id}
POST /api/learning-requests/previews/{preview_id}/confirm
GET  /api/commissioning-jobs/{job_id}
GET  /api/commissioning-jobs/{job_id}/blueprint
GET  /api/commissioning-jobs/{job_id}/report
```

- [x] Make preview creation idempotent for identical normalized requests.
- [x] Reject confirmation if the preview is stale relative to catalog versions
  or retrieval policy.
- [x] Revalidate every confirmed RLO ID/version before assembly.
- [ ] Convert confirmed input into `CourseAssemblyRequest` deterministically.
- [ ] Persist the exact assembly request used for the run.
- [ ] Run curriculum assembly asynchronously.
- [ ] Persist the blueprint, assembly report, and planning trace.
- [ ] Return typed, safe failure states to the UI.
- [ ] Do not create a `BuildPlan` in this release.

## Assembly Adapter

The adapter is the only component allowed to convert commissioning contracts
into the downstream assembly contract.

- [x] Map the audience archetype to `LearnerContext` using a versioned policy.
- [x] Map confirmed exact versions to `AssemblyRLOCandidate`.
- [x] Preserve user-required RLOs as `required=True` and in
  `CourseAssemblyConstraints.required_rlo_ids`.
- [x] Preserve exclusions and duration limits.
- [x] Map target proficiency without deriving it from Deloitte level.
- [x] Keep the original request text available as the course goal source, but
  produce a concise normalized `course_goal` for assembly.
- [x] Record every inferred/defaulted field in an adapter trace.
- [x] Validate the resulting `CourseAssemblyRequest` before queueing assembly.

## UI Plan

Serve the new interface from the commissioning service and link to it from the
existing RLO explorer. This keeps the feature visually adjacent without moving
commissioning logic into the ingestion application.

### Request page

- [ ] Add `/request-learning`.
- [ ] Free-text “What learning does this audience need?” field.
- [ ] Multi-value target roles.
- [ ] Deloitte levels.
- [ ] Current and target proficiency as independent fields.
- [ ] Industries and service lines.
- [ ] Business context.
- [ ] Explicit learning goals.
- [ ] Duration limit.
- [ ] Language and locale.
- [ ] Advanced include/exclude RLO controls.
- [ ] Clear disclosure that the request is for a cohort profile.

### Preview page

- [ ] Show the normalized subject interpretation before confirmation.
- [ ] Show ambiguities and allow the requester to revise the request.
- [ ] Show candidate title, objective, level, duration, version, governance,
  match reasons, and relevance band.
- [ ] Allow include, exclude, and required states.
- [ ] Show blocking content gaps prominently.
- [ ] Disable “Create course blueprint” for blocking gaps.
- [ ] Link content-gap users back to the RLO ingestion page.
- [ ] Make all controls keyboard accessible and screen-reader labeled.

### Job status/result page

- [ ] Show the current commissioning/assembly stage.
- [ ] Show typed failures without leaking prompts, credentials, or raw model
  payloads.
- [ ] On success, show blueprint title, outcomes, ordered RLOs, proficiency
  progression, duration, and assembly warnings.
- [ ] Allow downloading the blueprint, assembly report, and trace JSON.

## Persistence

Do not use `workflow_runs` for this phase: those records begin with a validated
`BuildPlan`, which does not yet exist here.

- [ ] Add commissioning-owned tables for requests, previews, candidate
  snapshots, confirmations, jobs, and artifact references.
- [ ] Store hashes and compact metadata separately from potentially sensitive
  request text.
- [ ] Define retention and deletion behavior for free-text requests.
- [ ] Use optimistic or explicit version checks when confirming a preview.
- [ ] Prevent duplicate assembly runs for the same confirmed snapshot.
- [ ] Record actor identity when authentication is available.

## Package and Deployment Layout

Proposed additions:

```text
src/learning_commissioning/
tests/commissioning/
commissioning/Dockerfile
commissioning/templates/
commissioning/static/
```

Compose services:

```text
commissioning-api
commissioning-worker
commissioning-postgres
```

- [x] Add services under a `commissioning` Docker Compose profile.
- [x] Give the API/worker catalog-service and LiteLLM configuration only.
- [x] Do not give the browser or templates provider credentials.
- [x] Use OpenAI-compatible calls through LiteLLM only.
- [x] Ensure reference/fake mode works without external model calls.
- [x] Keep all automated verification runnable in Docker.

## Implementation Phases

### Phase 0 — Contracts and Fixtures

- [x] Create `learning_commissioning` package skeleton.
- [x] Implement the commissioning contracts above.
- [x] Add representative cohort request fixtures.
- [x] Add sufficient, partially sufficient, and insufficient catalog fixtures.
- [x] Implement the cohort-to-`LearnerContext` projection policy.
- [x] Implement and verify the RLO schema adapter.

Exit gate: fixtures validate and a confirmed request deterministically produces
a valid `CourseAssemblyRequest` without network access.

### Phase 1 — Version-Safe Catalog

- [x] Implement versioned storage keys.
- [x] Implement versioned Qdrant IDs and payloads.
- [x] Add payload indexes and migration/reindex command.
- [x] Add exact-version retrieval endpoints.
- [x] Add batch semantic-search endpoint.
- [x] Preserve the existing ingestion and catalog-explorer behavior.

Docker verification on 2026-07-22 migrated all 22 stored RLOs, reindexed all
22 exact versions, removed the 22 legacy ID-only Qdrant points, and hydrated
every resulting search point through the exact-version API. The batch search
returned five bounded candidates for a representative change-leadership query.

Exit gate: multiple versions can coexist, and every search hit resolves to the
exact indexed document.

### Phase 2 — Request Interpretation and Retrieval

- [x] Implement structured request interpretation.
- [x] Implement deterministic fallback interpretation.
- [x] Implement batch embedding, filtered search, rank fusion, and boosts.
- [x] Implement compatibility filtering and hydration.
- [x] Implement content-gap analysis.
- [x] Build and evaluate the judged retrieval set.

Initial Docker calibration on 2026-07-22 achieved 100% expected recall@10
across six judged requests. Expected raw cosine scores ranged 0.549–0.797;
the unsupported request topped out at 0.233, while a labeled forbidden near
match reached 0.478. `retrieval-v1` therefore uses raw semantic score (before
context boosts) with bands: strong >= 0.65, acceptable >= 0.52, weak >= 0.35,
and forbidden below 0.35. The judged set must expand as the catalog diversifies.

Exit gate: relevant RLOs are retrieved for supported requests, and unsupported
requests reliably return a blocking content-gap report.

### Phase 3 — Preview and Confirmation API

- [x] Implement preview creation and retrieval.
- [x] Persist immutable candidate snapshots.
- [x] Implement confirmation with staleness and sufficiency validation.
- [x] Implement include/exclude/required candidate choices.
- [x] Add typed API errors and idempotency behavior.

The reference API is available as the Docker `commissioning-api` service on
port 8010. Commissioning-owned Postgres tables persist immutable previews and
confirmations; recreating the API container and retrieving the same preview
verified durability. A live request against the 22-RLO local catalog produced
an immutable blocked preview with three subject gaps, and its confirmation
endpoint returned a typed 409 rejection because all stored RLOs are currently
draft rather than approved.

Exit gate: a user can confirm only a sufficient, current, exact-version
candidate set.

### Phase 4 — Commissioning UI

- [x] Build request, preview, content-gap, and confirmation views.
- [x] Link the existing RLO explorer and commissioning UI.
- [x] Add accessible validation and loading states.
- [x] Add a deterministic component/demo fixture for UI review.

The existing ingestion UI now links to `/commission`, whose pre-populated
cohort scenario exercises interpretation, coverage gaps, candidate review, and
confirmation. The registry page also includes a direct semantic-search tester
with governance status and result-limit controls. It defaults to `approved`
to match both the local seed catalog and production commissioning policy.

The candidate review now displays the GPT-5.5 strategy, framework rationale,
per-RLO recommendation and rationale, while keeping include/required/exclude
controls editable for the requester.

Exit gate: a non-technical requester can understand the interpreted request,
candidate choices, and reasons a request is blocked.

### Phase 5 — Asynchronous Blueprint Assembly

- [x] Add commissioning job persistence and worker claiming.
- [x] Build and persist `CourseAssemblyRequest`.
- [x] Compose the existing `CourseAssemblyService` without modifying it.
- [x] Add a catalog-backed `RLORepository` implementation owned by the
  commissioning package.
- [x] Persist blueprint, report, and trace artifacts.
- [x] Implement status/result endpoints and UI.

The commissioning worker runs under the Compose `commissioning` profile. It
uses deterministic reference assembly by default and can use the existing
LiteLLM-compatible curriculum agent with
`COMMISSIONING_ASSEMBLY_MODE=real`. Visible artifacts are written beneath
`generated/commissioning/jobs/<job-id>/`.

Every commissioning model function uses a purpose-specific LiteLLM alias for
feature-level usage and cost attribution: `commissioning-request-interpretation`,
`commissioning-candidate-curation`, and `commissioning-course-assembly`.
Application code never selects the underlying provider model directly.

The canonical catalog and Qdrant governance state is `approved`. The shared
schema still accepts legacy `signed` documents during migration, and the
index/assembly adapters normalize that legacy value to `approved`. Catalog
availability failures remain operational errors and are not mislabeled as
missing RLOs.

Docker portability verification removes forced host architecture declarations,
mounts the optional Google Cloud configuration directory rather than assuming
an ADC file exists, and uses repository-root build contexts. Clean, no-cache
builds pass for the API, commissioning API, commissioning worker, and shared
test image.

Exit gate: a confirmed request produces an auditable `CourseBlueprint` or a
typed terminal failure.

### Phase 6 — Operational Hardening

- [ ] Add authentication and role-based authorization.
- [ ] Add request-content privacy and retention controls.
- [ ] Add structured logs, metrics, latency, model usage, and retrieval quality.
- [ ] Add rate limits and bounded model/search retries.
- [ ] Add stale-job recovery.
- [ ] Add production deployment documentation.

## Next Phase

The follow-on implementation that connects a confirmed commissioning job to
format selection, modality planning, workflow execution, a persistent Jobs UI,
and downloadable deliverables is specified in
[`commissioning-generation-pipeline-plan.md`](commissioning-generation-pipeline-plan.md).

## Verification Checklist

- [x] All commissioning contracts reject unknown fields.
- [x] Model output cannot set Qdrant filters or candidate IDs.
- [x] Cohort level does not silently determine topic proficiency.
- [ ] Industry affects ranking without hiding reusable content by default.
- [ ] Draft, archived, deprecated, incompatible, or superseded RLOs cannot be
  confirmed under the default policy.
- [x] Every candidate and blueprint reference contains an exact RLO version.
- [x] Required subject facets without acceptable candidates block confirmation.
- [x] A narrow request may succeed with one strong RLO.
- [x] A broad request with several weak matches still reports insufficient
  coverage.
- [x] Confirmed snapshots cannot change underneath an assembly run.
- [x] The generated payload validates as the existing `CourseAssemblyRequest`.
- [x] The existing `CourseAssemblyService` produces the blueprint.
- [x] No `BuildPlan` or production workflow is created in this release.
- [x] Existing RLO ingestion and explorer behavior remains operational.
- [x] Existing `learning_pipeline` tests remain unchanged and green.
- [x] Commissioning tests run in Docker without live providers.

## Definition of Done

- [x] A cohort requester can describe a learning need in the browser.
- [x] The system displays a focused interpretation rather than embedding the
  entire mixed request verbatim.
- [x] The system returns explainable, approved, exact-version RLO candidates.
- [x] The requester must confirm the candidate set.
- [x] Missing catalog coverage produces a clear, blocking authoring message.
- [x] A confirmed sufficient request produces a valid, auditable
  `CourseBlueprint`.
- [x] New implementation remains outside `src/learning_pipeline/` except for
  separately coordinated compatibility changes.
