# Learning Objective Extraction and Review Plan

**Status:** Draft for discussion

**Branch:** `feature/learning-objective-decomposition`

**Delivery slice:** Enabling-objective discovery, source-feature inventory, LDS
review, and workflow management

**Related plan:** `2026-08-31-learning-objective-decomposition-plan.md`

## Goal

Deliver the first usable source-to-learning-objective workflow. From one source
collection, the system should find all supported, practitioner-relevant enabling
objectives; show the source lineage and useful content already present for each;
let an LDS Instructional Designer edit, add, reject, and approve objectives; and
manage the work as a durable job through two lightweight review cycles.

This slice does not author an RLO. It identifies and refines the enabling objective
and records what source material may later help build the RLO.

## Scope

### Included

- Extracting an uncapped set of candidate enabling objectives from hierarchical
  source content using bounded model calls.
- Prioritizing realistic Deloitte practitioner tasks, decisions, risks, and
  performance needs.
- Applying the supplied Layer 1 decomposition rules and showing which signals and
  evidence produced each candidate.
- Recording a preliminary inventory of useful source features, such as definitions,
  explanations, examples, procedures, activities, assessments, and visuals.
- Showing exact source lineage at file, page/slide/section, and node level.
- Allowing an LDS Instructional Designer to edit, add, reject, approve, or return an
  objective for revision.
- Managing a durable job from initial draft through objective approval, detail
  enrichment, a second review, and completion.
- Preserving candidate versions, review decisions, and job history.
- Keeping every model prompt in an obvious, versioned Markdown file and making the
  exact prompt versions used by a job inspectable.

### Excluded

- Committing an objective to a final content-type × Bloom-level cell.
- Performing full Layer 3 mapping against a cell-specific RLO schema.
- Generating instruction, worked examples, practice, assessments, feedback, or
  transfer content.
- Producing or publishing a complete RLO.
- Requiring human review of Docling extraction quality.
- Complex separation-of-duties or multi-reviewer approval controls.

## Working definitions

### Enabling objective

The atomic performance statement around which one future RLO may be built. It must:

- describe one observable learner behavior;
- identify the content or performance boundary;
- connect to a realistic Deloitte practitioner task, decision, risk, or stated
  priority;
- remain grounded in objective-defining source evidence;
- separate supporting context from what may legitimately be assessed;
- be small enough to plausibly support a focused learning object, with the 5–15
  minute guideline treated as a review heuristic rather than a hard rejection rule.

An RLO does not own a broad terminal objective. A terminal outcome stated in the
source may be retained as optional course/pathway context and linked to the enabling
objectives beneath it.

### Source-feature inventory

A cited inventory of potentially useful instructional material already present in
the source. At this stage, a feature may be `observed`, `uncertain`, or `not_found`.
`not_found` means the full-coverage process did not surface it; it is not a claim
that the content can never exist.

This is intentionally shallower than RLO mapping. Without a committed cell and its
schema, this phase must not claim that an RLO section is pedagogically complete.
It can say “a worked case was found” or “no assessment item was found,” but Layer 3
later decides whether that material satisfies the selected RLO schema.

### Objective job

The durable workflow container for one immutable source-collection/map revision,
an optional practitioner brief, the extracted candidates and source features, and
all LDS review activity. A later change to the source revision creates a new run or
explicit reprocessing revision rather than silently changing completed evidence.

## Proposed job workflow

| Stage | Purpose | Exit condition |
|---|---|---|
| `draft` | The system decomposes source material and assembles the candidate inventory. | Processing succeeds and every candidate has resolvable lineage or an explicit error. |
| `objective_review` | LDS reviews objective wording, atomicity, practitioner relevance, and assessment boundary. | Every candidate has an LDS disposition; added objectives have evidence or are clearly marked as LDS-authored. |
| `objectives_approved` | Snapshot the accepted enabling-objective set. | LDS advances the job. |
| `detail_enrichment` | The system adds structured details and the preliminary source-feature inventory for accepted objectives. | Enrichment succeeds or unresolved fields are explicitly flagged. |
| `detail_review` | LDS reviews lineage, rationale, objective components, relationships, and “already present versus likely needed” indicators. | Each accepted objective receives a detail-review disposition. |
| `details_approved` | Snapshot the approved objective packages. | LDS advances the job. |
| `complete` | Mark the package ready for the future Classification stage. | Completion event and immutable handoff snapshot are stored. |

The same LDS reviewer may perform both reviews. The workflow is a visible organizing
device, not an enterprise approval barrier.

Technical processing state is separate from editorial workflow stage:
`idle`, `queued`, `running`, `succeeded`, or `failed`. A failed model call does not
silently move an editorial job backward, and a retry resumes persisted work.

## Objective package at completion

Each completed objective should contain:

- stable objective identity and immutable revision;
- current standard-form statement;
- observable behavior, content boundary, and performance context;
- practitioner role plus the task, decision, risk, or priority establishing value;
- objective-defining evidence and supporting-context evidence kept separate;
- exact source citations and human-readable locators;
- derivation signals and decomposition rule IDs;
- confidence with a structured rationale;
- assumptions, conflicts, currency indicators, and granularity flags;
- optional terminal-outcome anchor;
- prerequisites, postconditions, and related-objective links when supported;
- preliminary content-type and Bloom-level hints, explicitly uncommitted;
- preliminary source-feature inventory;
- an “already present” summary and a “likely downstream gap” summary;
- LDS edits, decisions, notes, authorship, and timestamps.

## Preliminary source features

| Feature | What is recorded now | Deferred decision |
|---|---|---|
| Explicit learning objective | Exact stated objective and whether it appears terminal or enabling | Whether its wording is retained in the RLO |
| Core substance | Definitions, facts, explanations, rules, steps, decisions, and qualifications | Whether it completes the cell-specific teach section |
| Worked example or case | Scenario, visible reasoning, and outcome that are actually present | Whether it satisfies the required worked-instance methodology |
| Practice/activity | Prompt, learner action, feedback, and repetition that are actually present | Whether it aligns with the committed Bloom level |
| Assessment | Item, criterion, rubric, answer, and feedback that are actually present | Whether it validly assesses the approved objective |
| Structured visual | Table, diagram, flow, matrix, or decision tree plus its written explanation | How it is used instructionally |
| Prerequisite/transfer cue | Prior knowledge, next step, spacing, or on-the-job prompt | Final sequencing and transfer design |
| Currency signal | Edition, effective date, named standard, or possible supersession cue | Authoritative currency determination and refresh policy |

Every observed or uncertain feature must cite source nodes. Features may be reused
across objectives; reuse is recorded rather than forced into exclusive ownership.

## Extraction approach

1. Snapshot the selected collection map and optional practitioner instructions.
2. Create or infer a small number of explicit practitioner lenses.
3. Build hierarchy-aware planning units under the configured source-content token
   limit. Token limits constrain individual calls, not source size or candidate count.
4. Detect decomposition signals and preliminary source features in every planning
   unit, persisting each unit before continuing.
5. Form atomic enabling-objective candidates iteratively. Each follow-up pass receives
   a compact memory of prior statements, behaviors, preliminary content-type/Bloom
   hints, and cited claims, then seeks materially different supported objectives.
6. Continue until a follow-up pass adds no new objective, with a finite four-pass
   safety bound. Candidate count is an outcome of supported discovery, not a target.
7. Combine candidates across planning units while preserving review-worthy overlap;
   only exact repeated statements are suppressed deterministically.
8. Resolve source lineage and persist the broad candidate list for LDS review. Defer
   model critique, reconciliation, and pedagogical detail enrichment until after the
   human has selected the objective set.

Low-confidence, duplicate, broad, narrow, supplementary-only, and ambiguous
candidates remain visible. They receive flags rather than being removed from the
inventory.

## Prompt organization and reviewability

Prompts are product behavior and must be reviewable without reading Python service
code. The current source-objective prototype keeps several prompts as inline Python
constants; this work should move them into a dedicated directory:

```text
api/src/source_authoring/prompts/objective_extraction/
├── README.md
├── practitioner_lenses.md
├── structured_signal_detection.md
├── sme_signal_detection.md
├── candidate_formation.md
├── candidate_reconciliation.md
├── evidence_verification.md
├── source_feature_inventory.md
└── detail_enrichment.md
```

The inventory may become smaller if two operations genuinely share one prompt, but
a single catch-all prompt should not obscure materially different responsibilities.
Deterministic operations should remain code and should not acquire unnecessary
prompts.

Each prompt file should contain:

- a unique prompt ID and explicit version in its header;
- its purpose and the pipeline operation that loads it;
- the model's role and strict behavioral rules;
- the input fields it receives and their trust boundary;
- the structured output contract it must return;
- the decomposition rule IDs implemented by the prompt;
- clear exclusions and ownership boundaries with other stages.

The directory `README.md` should act as the local index: prompt ID, filename,
calling operation, LiteLLM model alias, input contract, output contract, and current
version. The repository-wide `docs/prompt-catalog.md` must also inventory these
prompts using its existing convention.

Application code should load prompt text from these files through one narrow loader.
Service modules may reference prompt IDs and paths, but must not carry alternate
inline production prompts or silent fallback prompt text. Editing prompt wording
should require changing the Markdown asset and its version, not changing orchestration
code.

For reproducibility, every model call should record:

- prompt ID, version, and SHA-256 hash;
- the exact system-prompt snapshot used for that call;
- user-payload template/contract version and an input artifact reference;
- LiteLLM alias, operation, job ID, and planning-unit ID;
- structured-output schema version;
- token usage and Langfuse trace identifier when available.

The job interface should include a read-only **Prompts used** view listing every
prompt/version involved in the job. A reviewer can open the exact prompt snapshot
and input artifact for an individual operation. This view must use persisted run
metadata rather than showing whatever prompt happens to be current in the working
tree.

Prompt editing should remain source-controlled for this delivery slice. An in-product
prompt editor would introduce runtime configuration, permissions, draft/publish
semantics, and reproducibility concerns unrelated to objective review. It can be
added later if source-controlled editing is insufficient.

## Draft UI branch assessment

The draft `origin/feature/learning_objective_list` branch contains two static design
variants. Useful concepts to retain are:

- a source/job list with reviewed counts and progress;
- All, Pending, Approved, and Rejected filters;
- focused one-objective-at-a-time review;
- previous/next and direct objective navigation;
- visible statement, behavior, context, confidence, and evidence;
- add, edit, reject, approve, and undo interactions.

The branch should not be merged wholesale:

- all objective data and decisions are hard-coded in browser JavaScript;
- evidence is bibliographic rather than node-level lineage;
- it has no durable job workflow, APIs, concurrency handling, or revision history;
- it has two competing full-page templates rather than one maintained interface;
- unrelated backend edits restore a SQLite fallback, contrary to the Postgres-only
  architecture.

We should port the useful interaction model into repository-standard templates,
shared styles, real APIs, and Postgres-backed state.

## Phased build plan

### Phase 0 — Freeze the focused contracts

- [x] Confirm that `detail_enrichment` means objective metadata, lineage, relationships,
  and preliminary source-feature inventory—not RLO authoring.
- [x] Define the objective-job, candidate revision, feature, evidence, review, and
  transition contracts.
- [x] Define which fields LDS may edit at first review versus detail review.
- [x] Define the completed handoff contract for the future Classification stage.
- [x] Approve the prompt inventory, prompt IDs, operation boundaries, and file naming
  convention.
- [x] Remove the fixed 12-candidate assumption from the Layer 1 contract and tests.
- [x] Define deterministic transition requirements without multi-reviewer guardrails.

**Exit gate:** The job state machine and completed objective package are agreed.

### Phase 1 — Separate decomposition from downstream filtering

- [x] Move source-objective prompts out of inline Python constants and into the
  dedicated, versioned Markdown prompt directory.
- [x] Add the local prompt index and update `docs/prompt-catalog.md`.
- [x] Add one prompt loader with no hidden fallback prompts.
- [x] Refactor the initial objective service into explicit planning, signal detection,
  source-feature inventory, and broad candidate formation steps.
- [x] Stop before reconciliation and evidence verification; reserve those prompts for
  a later stage after LDS approval of the broad objective list.
- [x] Preserve overlapping, low-confidence, and debatable candidates for LDS review
  instead of converting them into hidden rejections.
- [x] Require a practitioner-value statement for every model-proposed candidate.
- [x] Keep LDS-added candidates and their authorship distinct from model-proposed
  candidates.
- [x] Preserve optional terminal outcomes as external anchors, not RLO objectives.
- [x] Add purpose-specific model aliases only in `litellm/config.yaml` and route all
  model calls through the existing LiteLLM configuration.
- [x] Persist prompt ID, version, hash, exact snapshot, input artifact reference, and
  output-schema version for every model call.

**Exit gate:** One source collection produces an uncapped, fully cited draft
inventory with no silent candidate loss.

### Phase 2 — Add preliminary source-feature extraction

- [x] Define the source-feature taxonomy and `observed` / `uncertain` / `not_found`
  semantics.
- [x] Extract source features alongside decomposition signals so the source is not
  repeatedly scanned without need.
- [x] Associate features with zero, one, or many candidates.
- [x] Preserve unmatched features at job level because they may reveal a missed
  objective during LDS review.
- [x] Generate per-objective “already present” and “likely downstream gap” summaries
  without claiming schema completeness.
- [x] Validate that every observed/uncertain feature resolves to exact source nodes.

**Exit gate:** LDS can see what useful material exists and what was not found without
the system prematurely performing Layer 3 mapping.

### Phase 3 — Implement durable jobs and transitions

- [x] Add idempotent Postgres migrations for objective jobs, runs, candidate revisions,
  features, evidence links, review decisions, and workflow events.
- [x] Store immutable source/map revision references and model/rule/prompt versions.
- [x] Store immutable prompt snapshots separately from the current editable prompt
  assets so historical jobs remain reproducible after prompt changes.
- [x] Implement the seven editorial stages and separate processing states.
- [x] Define transition commands with optimistic concurrency/version checks.
- [ ] Support retry/resume from persisted planning-unit results.
- [x] Retain rejected candidates and prior edits in history.
- [x] Add paginated queries and summary counts suitable for jobs with many candidates.

**Exit gate:** A job survives process restarts, rejects stale updates, and retains a
complete audit trail through `complete`.

### Phase 4 — Add APIs and worker orchestration

- [x] Add endpoints to create, list, inspect, retry, and advance objective jobs.
- [x] Add paginated/filterable candidate and source-feature endpoints.
- [x] Add commands to edit, split, merge, add, reject, approve, request revision, and
  undo/replace a prior decision.
- [x] Add an evidence endpoint that returns excerpts and original-document deep links.
- [x] Move compute-heavy extraction and enrichment through the durable worker queue.
- [x] Expose stage, candidate counts, current operation, completed model-operation
  count, last activity, and failure details for progress polling.
- [ ] Expose a bounded total/unit count where the pipeline can determine one before
  processing completes.
- [x] Emit Langfuse traces and model usage metadata for each model-backed operation.
- [x] Add APIs to list the prompts used by a job and retrieve a specific persisted
  prompt/input snapshot for inspection.

**Exit gate:** All workflow behavior is available through authenticated APIs and a
failed long job resumes without repeating completed units.

### Phase 5 — Build the LDS review interface

- [x] Add an Objective Jobs page showing source collection, editorial stage,
  processing state, counts, progress, last activity, and failures.
- [x] Add a job timeline for Draft → Objective Review → Objectives Approved → Detail
  Enrichment → Detail Review → Details Approved → Complete.
- [x] Port the draft branch's candidate filters and focused review navigation.
- [x] Show objective components, practitioner relevance, confidence, flags, and the
  model's decomposition rationale without overwhelming the primary review action.
- [x] Show exact lineage and allow a reviewer to open the relevant page/slide/section
  in source context.
- [x] Show source features as “observed,” “uncertain,” or “not found,” including
  unmatched job-level features.
- [x] Add a read-only **Prompts used** panel with prompt ID, version, operation, model
  alias, and links to exact persisted prompt and input snapshots.
- [x] Support LDS edit, add, split, merge, reject, approve, revision request, note,
  and undo/replace workflows.
- [x] Preserve keyboard navigation, visible focus, semantic headings, accessible
  status updates, and text alternatives for visual evidence.
- [ ] Verify desktop and narrow layouts against the running containerized application.

**Exit gate:** An LDS Instructional Designer can take a real job from first review
through completion without editing JSON or manually copying source citations.

### Phase 6 — Verify the vertical slice

- [ ] Add contract and transition-table tests for every allowed and forbidden state
  change.
- [ ] Add repository tests for candidate revisions, audit history, concurrency,
  pagination, and retry/resume.
- [ ] Add deterministic fake-model tests for explicit objectives, inferred enabling
  objectives, terminal-outcome decomposition, visuals, examples, assessments,
  supporting context, duplicates, and low-confidence candidates.
- [x] Add tests that every production model operation resolves to one cataloged
  prompt file, the version appears in its header, hashes change when content changes,
  and no inline or fallback production prompt bypasses the catalog.
- [x] Verify that a historical job continues to display its original prompt snapshot
  after the current prompt file is changed.
- [ ] Test a generated multi-million-token hierarchy for bounded calls, full coverage,
  resumability, and uncapped total candidate persistence.
- [x] Add API and accessible UI smoke tests in containers.
- [ ] Conduct one representative LDS review and record missed objectives, irrelevant
  candidates, inappropriate assessment boundaries, lineage usability, and workflow
  friction.
- [ ] Tune prompts and confidence based on observed review results without creating a
  subjective automated quality harness.

**Exit gate:** Observable system guarantees pass in containers, and one LDS reviewer
can efficiently complete a representative job.

## Success measures for the POC

- No fixed total candidate limit and no silent truncation.
- Every model-proposed objective states a Deloitte practitioner need.
- Every model-proposed objective has verifiable objective-defining evidence.
- Supporting context cannot expand the assessment boundary.
- Every source node is processed or has an explicit coverage disposition.
- Every objective-model result identifies an inspectable prompt version and immutable
  prompt/input snapshot.
- Production prompts are editable as clearly named Markdown assets without changing
  service orchestration code.
- Every observed source feature has lineage; `not_found` remains an honest search
  result rather than a fabricated certainty.
- LDS can change an objective without losing its original wording or evidence history.
- Rejected objectives remain auditable and do not enter enrichment.
- A retried job reuses completed source maps and a completed objective workspace;
  finer-grained objective planning-unit checkpoints remain backlog hardening.
- The completed package is versioned and ready for future Classification, but no RLO
  content has been authored.

## POC implementation decisions

1. **Detail enrichment ownership:** The system proposes the details
   and source-feature inventory, and LDS reviews/edits them during the second review.
2. **Approval granularity:** Decisions remain per objective, while the
   job stage advances the accepted set as a batch once no candidate is undecided.
3. **LDS-added objectives:** Label them as LDS-authored and require source lineage.
   The current UI starts a related objective from an existing candidate's evidence;
   it does not permit an uncited objective to appear source-grounded.
4. **Completed destination:** `complete` means the objective package
   is frozen and ready for the future Classification stage, not that an RLO exists.
5. **Source-feature gap wording:** Use “not found in source” and
   “likely downstream gap,” not “missing” or “must generate,” until Classification
   and schema-specific Mapping are complete.
6. **Prompt editing surface:** Prompts are edited and reviewed as
   versioned Markdown in source control, while the application provides read-only
   inspection of the exact snapshots used. Defer in-product prompt editing unless a
   concrete non-developer authoring need emerges.
