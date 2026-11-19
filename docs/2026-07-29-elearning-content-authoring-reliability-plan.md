# E-Learning Content Authoring Reliability Revision Plan

**Status:** In progress. Tasks 1–7 completed; Task 8 live evaluation is in progress.

**Goal:** Make e-learning authoring reliably produce faithful, usable learner-facing content without wasting model calls on defects owned by planning, deterministic assembly, assessment hydration, navigation, or rendering.

**Approach:** Keep the existing frozen workflow plan, deterministic DAG, checkpoints, and bounded authoring controller. Narrow the model's responsibility to learner-facing copy, validate plan/component feasibility before authoring, route findings to the subsystem that can actually resolve them, and replace whole-screen regeneration with targeted edits. This is a refinement of the existing system, not a new agent framework.

## Working Rules

These rules apply throughout implementation and reflect `AGENTS.md`:

- State assumptions and unresolved tradeoffs before changing behavior.
- Make the smallest change that proves each phase; do not combine phases into a broad refactor.
- Add a failing generic test before each behavior change, then implement only enough to pass it.
- Do not add tests that depend on Kotter, ADKAR, or any other specific subject matter.
- Preserve existing public pipeline contracts unless a task explicitly identifies an unavoidable contract change.
- Prefer private/internal models for authoring assignments and findings; do not introduce another cross-pipeline contract layer.
- Do not allow an LLM to alter frozen workflow-plan decisions at runtime.
- Do not hand-edit generated course output to conceal a rule or implementation failure.
- Keep model calls, repairs, and elapsed time bounded and observable.
- Touch only the files named by the active task unless a discovered dependency is documented first.
- Complete and verify one task before starting the next, updating its checkbox as work progresses.

## Scope and Assumptions

### In scope

- E-learning workflow-plan feasibility checks that directly affect authorability.
- Authoring assignments, structured responses, deterministic hydration, validation, review, and revision.
- Reviewer authority and finding ownership.
- Authoring telemetry and regression evaluation.
- Upstream e-learning screen planning where it directly drives authoring reliability.

### Out of scope

- Podcast, Manim, video, and commissioning redesigns.
- A general-purpose agent framework or autonomous runtime replanning.
- Changes to RLO facts, approved assessments, or source material.
- Visual polish unrelated to whether content can be authored and rendered correctly.
- Human review tooling beyond exposing actionable failure information.

### Assumptions to validate during Task 1

- The frozen e-learning workflow plan remains the source of truth for screen order and required content.
- Component schemas can describe enough capability to detect impossible learner interactions before authoring.
- Assessment content and scenario navigation can remain deterministically hydrated.
- The course builder can provide a normalized learner-facing representation for semantic review without requiring browser automation.
- One targeted author repair pass is a suitable initial default; evidence, rather than preference, will determine whether a second pass is retained.

## Problem Statement

The current authoring loop sends nearly every blocking finding back to the prose-authoring model. Persisted workspaces show findings involving assessment structure and fidelity, unsupported interactions, missing required fields, navigation, layout values, content completeness, and source fidelity. These do not share one repair mechanism.

The model also writes learner-facing copy and deterministic structure through one broad `ScreenContent` model containing optional fields for all supported screen types. This creates avoidable ambiguity and allows the author to change fields that should be controlled by the workflow plan or builder.

The revision must distinguish four different outcomes:

| Failure class | Correct response |
|---|---|
| Unsupported screen or interaction plan | Reject or repair the affected plan requirement before authoring |
| Invalid IDs, navigation, assessment structure, layout, or provenance | Fix in deterministic code; do not call the author |
| Unsupported, distorted, incomplete, or unusable learner-facing copy | Send a targeted field-level patch to the author |
| Stylistic preference that does not impair learning or fidelity | Record as advisory; do not block publication |

## Target Flow

```text
Frozen e-learning workflow plan
    -> deterministic assignment compiler and feasibility checks
    -> component-specific learner-copy generation
    -> deterministic structure, assessment, and navigation hydration
    -> deterministic validation and course build
    -> semantic audit of normalized learner-facing content
    -> at most one targeted author-owned patch pass
    -> final validation, telemetry, and publication
```

## Global Acceptance Criteria

- Unsupported learner actions are detected before the first authoring call and identify the responsible screen requirement.
- The authoring model cannot change screen IDs, order, type, source lineage, assessment correctness, or navigation.
- Assessment, navigation, schema, and renderer findings never consume an author repair call.
- Every blocking semantic finding identifies a real editable field, source evidence, owner, and repair action.
- Only source fidelity, required-content completeness, unusable learner instructions, and pedagogical-rationale leakage can block semantic publication.
- Advisory tone or repetition findings do not trigger revisions.
- A revision changes only approved learner-facing fields; protected fields remain identical.
- A repeated or no-op repair stops deterministically and reports why instead of exhausting the full model-call budget.
- Tests use generic synthetic content and component capabilities, not assertions about particular RLO topics.
- Existing e-learning authoring, pipeline, and workflow-planning tests continue to pass.
- A representative evaluation set shows completion rate, model calls, cost, repair rate, and findings grouped by owner before rollout.

## File Map

| File or area | Planned responsibility |
|---|---|
| `src/learning_pipeline/tools/elearning_bundle/_authoring_workspace.py` | Finding ownership, repairability, field paths, and workspace-versioned trace data |
| `src/learning_pipeline/tools/elearning_bundle/_authoring_tools.py` | Assignment compilation, deterministic hydration, and validation boundaries |
| `src/learning_pipeline/tools/elearning_bundle/_author_contracts.py` | Private component-specific learner-copy response models |
| `src/learning_pipeline/tools/elearning_bundle/_authoring_controller.py` | Finding routing, bounded patch workflow, checkpoints, and stuck-repair detection |
| `src/learning_pipeline/tools/elearning_bundle/_authoring_client.py` | Structured author, review, and targeted-patch calls |
| `src/learning_pipeline/tools/elearning_bundle/_authoring_review.py` | Deterministic review rules and learner-facing review projection |
| `src/learning_pipeline/prompts/elearning_author/course_author.md` | Learner-copy-only authoring instructions |
| `src/learning_pipeline/prompts/elearning_author/course_review.md` | Narrow blocking rubric and evidence requirements |
| E-learning workflow planner prompts/contracts | Content-driven screen planning and component-capability-compatible directions |
| `tests/tools/elearning/` | Generic unit and controller tests for each authoring boundary |
| `tests/planners/workflow/elearning/` | Generic screen-budget and authorability tests |

---

## Task 1: Capture a Baseline and Confirm Boundaries

**Purpose:** Establish measurable current behavior and validate the assumptions above before changing architecture.

- [x] Record the current branch, commit, relevant environment settings, and targeted test results.
- [x] Convert representative historical failure shapes into generic synthetic regression cases: invalid structural enum, unsupported response mode, assessment mutation, broken navigation, source distortion, missing required content, and advisory style feedback.
- [x] Measure current author calls, review calls, repair attempts, blocking findings, and terminal outcomes for the synthetic cases.
- [x] Confirm which fields the course builder derives deterministically and which remain genuinely author-editable.
- [x] Confirm whether normalized built course JSON contains everything needed for semantic review.
- [x] Document any failed assumption before proceeding; revise later tasks rather than silently expanding scope.

**Verification:**

```bash
python -m pytest tests/tools/elearning -q
python -m pytest tests/planners/workflow/elearning -q
```

**Exit criteria:** Baseline results and generic regression cases exist, with each observed failure assigned provisionally to planner, author, builder, renderer, or source.

### Task 1 execution record

- Baseline branch/commit: `feature/workflow-refinements` at `c254ff5`.
- Runtime route: the real workflow worker uses `LITE_LLM_BASE_URL=http://litellm:4000`; `elearning-course-authoring` is configured with low reasoning effort in `litellm/config.yaml`. The executor policy permits 12 model calls, 12 internal tool calls, and two repair attempts with a 120-second client timeout.
- Targeted baseline: 439 e-learning tool tests passed and 87 e-learning workflow-planner tests passed. The repository has no `python` executable on PATH, so execution uses `.venv/bin/python`; later verification commands should use the same runner.
- Persisted baseline: six authoring workspaces contain 53 historical findings. Finding counts include 10 knowledge-check structure, nine assessment-fidelity, eight interaction-validity, eight missing-required-assessment-item, and four validation findings. All 53 lack an owner. Per-workspace model-call counts are 11, 9, 12, 1, 4, and 3; repair counts are 2, 1, 1, 0, 2, and 0.
- Existing topic-neutral cases cover invalid relationship-diagram positions, open-response assessment rejection, assessment mutation, deterministic scenario navigation, missing required fields, scoped semantic repair, and pedagogical-rationale leakage. Task 3 will add the currently missing component-capability preflight cases before implementing that behavior.
- The builder already owns final screen identity, type enforcement, order, sequence, slot insertion, grouped-assessment expansion, and duration metadata. Assessment hydration and scenario continuation are also deterministic. The model still supplies these fields in its draft, which confirms the redundant-control problem addressed by Task 4.
- The normalized course dictionary contains the complete validated learner-facing screen sequence and is sufficient for semantic review when supplemented with screen purpose and relevant source excerpts.
- Confirmed limitation: content directions are currently opaque strings with no component-capability model. Task 3 will add a minimal private capability check; it will not introduce runtime replanning or a new public contract.

---

## Task 2: Add Finding Ownership and Repair Routing

**Purpose:** Stop sending every blocker to the authoring model.

- [x] Write failing tests for owned findings and routing behavior.
- [x] Extend the private `AuthoringFinding` representation with a stable code, owner, repairability, and optional editable field path.
- [x] Keep human-readable messages and evidence, but do not use message text as routing logic.
- [x] Map existing deterministic findings to `builder`, `renderer`, or `source` as appropriate.
- [x] Accept semantic findings for author repair only when they cite an existing screen and editable field.
- [x] Route planner-owned findings to a clear terminal preflight error in this phase; do not add runtime replanning.
- [x] Persist routed findings and counts by owner in the versioned authoring workspace and trace.
- [x] Add compatibility handling for older persisted workspaces or deliberately invalidate them with an explicit workspace-version message.

**Verification:**

```bash
python -m pytest tests/tools/elearning/test_authoring_review.py -q
python -m pytest tests/tools/elearning/test_real_author_executor.py -q
```

**Exit criteria:** Only author-owned, field-addressable findings can increment `repair_attempt_count` or trigger an author call.

### Task 2 execution record

- Added stable finding codes, owners, repairability routes, and editable field paths to the private authoring workspace model.
- Versioned workspaces as `authoring-workspace-v3` and the review rubric as `course-review-v4`; older checkpoints are regenerated through the existing incompatible-checkpoint path.
- Classified course-build validation as builder-owned, malformed assessment source as source-owned, assessment mismatch after hydration as builder-owned, and rationale signals as author-owned advisory findings.
- The controller now rejects non-author blocking findings rather than spending an author repair call, and semantic author blockers require an exact editable field path.
- Authoring traces now include finding counts grouped by owner.
- Verification: 442 topic-neutral e-learning tests passed with `.venv/bin/python -m pytest tests/tools/elearning -q`.

---

## Task 3: Compile and Preflight Authoring Assignments

**Purpose:** Detect impossible production directions before generating content.

- [x] Write failing tests for directions that request unsupported selection, open response, branch behavior, and assessment behavior.
- [x] Harden the existing deterministic assignment inspection into the preflight compiler instead of adding a second abstraction.
- [x] Compile each workflow requirement into protected structural data plus its explicit learner action; editable field separation remains Task 4.
- [x] Validate requested learner actions against the selected component's actual capabilities.
- [x] Validate scenario graph requirements and assessment-source availability before the first model call. Component item limits remain Task 4 because item counts do not exist in the frozen plan.
- [x] Return stable, actionable planner-owned errors containing the requirement and mismatch.
- [x] Preserve valid frozen workflow-plan choices; only legacy plans without `learner_action` retain the existing unsupported-assessment compatibility conversion.

**Verification:**

```bash
python -m pytest tests/tools/elearning -q -k "assignment or preflight or capability"
python -m pytest tests/planners/workflow/elearning -q
```

**Exit criteria:** Every authoring assignment is feasible for its component, and impossible assignments fail without consuming authoring tokens.

### Task 3 execution record

- Added `learner_action` to `AuthoredScreenRequirement` with four generic values: `consume`, `reveal`, `choose`, and `reflect`.
- New workflow plans must set the action explicitly and match the selected component. Older persisted briefs can derive the natural action from `screen_type`.
- Updated the workflow-planner and course-author prompts, and versioned the workflow-planner prompt as `elearning_v4`.
- Added deterministic preflight for action/component mismatches, incomplete scenario continuation, and knowledge checks without approved assessment source.
- Preflight failures carry stable codes, `owner=planner`, and `repairability=replan`, and occur before the first author call.
- Preserved the legacy knowledge-check-to-takeaways conversion only for older requirements that lack `learner_action`; new invalid plans fail rather than silently changing a frozen screen choice.
- Component item-count feasibility cannot be checked from the current plan because no item count is represented. Rather than add another speculative contract field, Task 4 will enforce exact component-family limits through the typed learner-copy schemas.
- Verification: 1,912 tests passed and 14 skipped with `.venv/bin/python -m pytest -q`.

---

## Task 4: Restrict Model Output to Component-Specific Learner Copy

**Purpose:** Remove deterministic structure from model control and reduce structured-output ambiguity.

- [x] Write failing tests proving the model cannot provide or modify protected fields.
- [x] Identify the smallest useful screen-specific copy shapes based on genuinely different component fields.
- [x] Replace the all-optional author response surface with exact private learner-copy response models.
- [x] Preserve mixed batches without schema ambiguity by generating one exact typed response key per requested screen; no extra calls are introduced.
- [x] Inject screen ID, type, order, source IDs, assessment structure, navigation, nested IDs, layout enums, and other protected fields deterministically.
- [x] Update authoring prompts to describe only the learner-facing fields the model controls.
- [x] Retain generic source-fidelity and Deloitte corporate-training context in every applicable authoring call.
- [x] Verify structured-output parsing failures identify the component family and field without leaking raw payloads or secrets.

**Verification:**

```bash
python -m pytest tests/tools/elearning/test_author_contracts.py -q
python -m pytest tests/tools/elearning/test_authoring_client.py -q
python -m pytest tests/tools/elearning/test_real_author_executor.py -q
```

**Exit criteria:** Model output contains only editable learner-facing content, while deterministic assembly reproduces the required course structure exactly.

### Task 4 execution record

- Replaced the real model's `ElearningCourseAuthorDraft` response schema with a generated learner-copy batch. Each `screen_N` key has the exact schema for its assigned component, while mixed component types remain in one model call.
- The internal `ScreenContent` and `ElearningCourseAuthorDraft` models remain as normalized builder inputs; they are no longer exposed as the model response contract.
- Deterministic compilation injects screen identity, type, source lineage, ordering, title metadata, assessment data placeholders for immediate source hydration, scenario choice IDs, scenario continuation, flip-card IDs, relationship-node IDs, and relationship layout positions.
- Knowledge-check copy schemas contain no fields, preventing the model from transcribing or changing source-controlled assessment content.
- Relationship-diagram copy accepts only labels and learner-facing detail, eliminating the prior prose-in-layout-enum failure.
- Updated the authoring prompt to version 5 and removed instructions to generate protected fields.
- Structured validation errors report response key, component type, field path, and error type without echoing rejected input values.
- Verification: 1,915 tests passed and 14 skipped with `.venv/bin/python -m pytest -q`.

---

## Task 5: Narrow Review to Learner-Visible, Author-Repairable Defects

**Purpose:** Make blocking review rigorous about fidelity and usability without treating preferences or internal structures as release failures.

- [x] Write failing reviewer tests for the permitted blocking policy and advisory tone/repetition cases.
- [x] Build a normalized review projection from the validated course that contains learner-visible content, relevant screen purpose, learner action, editable fields, and scoped source context.
- [x] Exclude internal duplicated assessment representations, protected navigation, layout metadata, video slots, and screens outside the current review scope.
- [x] Limit blocking semantic categories to source contradiction/fabrication, missing required source content, unusable learner instruction, and pedagogical-rationale leakage.
- [x] Require every author-owned blocker to cite the editable field, visible/source evidence, and a concrete correction.
- [x] Treat optional invitations, stylistic preference, and non-material repetition as warnings.
- [x] Reject malformed, misrouted, unknown-screen, or protected-field reviewer output as a review-system error rather than converting it into an authoring defect.

**Verification:**

```bash
python -m pytest tests/tools/elearning/test_authoring_review.py -q
python -m pytest tests/tools/elearning/test_real_author_executor.py -q -k review
```

**Exit criteria:** The reviewer cannot block on hidden or protected data, and every accepted blocker is both learner-visible and author-repairable.

### Task 5 execution record

- Semantic review now receives `learner_view`, a projection of the validated built course containing only author-editable learner-facing fields, screen purpose, and learner action.
- Knowledge checks, source lineage, assessment internals, navigation, metadata, layout values, video slots, and other protected fields are absent from the review projection.
- Review source context and assignment requirements are scoped to the projected screens for both initial and revision reviews, reducing irrelevant input tokens.
- Blocking authority is limited to four stable codes: `SOURCE_FIDELITY`, `REQUIRED_CONTENT_MISSING`, `LEARNER_INSTRUCTION_UNUSABLE`, and `PEDAGOGICAL_RATIONALE_LEAKAGE`.
- Any other model-reported blocker is deterministically downgraded to an advisory warning and cannot trigger revision.
- Author blockers require an editable `content.*` field path, evidence, and a bounded revision instruction. Protected paths and misrouted owners fail as review-system errors.
- Courses or review scopes containing only source-controlled knowledge checks skip the semantic review call entirely.
- Versioned the review rubric as `course-review-v5` and updated the reviewer prompt to its learner-view contract.
- Verification: 1,920 tests passed and 14 skipped with `.venv/bin/python -m pytest -q`.

---

## Task 6: Replace Whole-Screen Revision with Targeted Patches

**Purpose:** Make feedback capable of changing the observed defect without destabilizing a correct screen.

- [x] Write failing tests for a single-field patch, protected-field mutation, no-op patch, repeated finding, and successful scoped re-review.
- [x] Define a private patch response containing screen ID, editable field path, replacement value, and addressed finding IDs.
- [x] Send the author only the relevant screen projection, source evidence, and accepted findings.
- [x] Apply patches deterministically and reject changes outside the allowed fields.
- [x] Re-run hydration and deterministic validation after patch application.
- [x] Re-review only changed learner-facing fields and their relevant source context.
- [x] Detect no material change or recurrence of the same stable finding and stop immediately with an owned, diagnosable failure.
- [x] Start with one targeted repair pass; retain a second only if baseline evaluation demonstrates a material completion-rate benefit.

**Verification:**

```bash
python -m pytest tests/tools/elearning/test_real_author_executor.py -q -k "revision or repair or patch"
python -m pytest tests/tools/elearning -q
```

**Exit criteria:** A semantic repair cannot alter unrelated screens or protected structure, and stuck repairs do not repeatedly consume model calls.

### Task 6 execution record

- Added exact, component-specific patch schemas containing only the top-level learner-copy fields cited by accepted findings. Screen identity and addressed finding IDs are carried in a deterministic response map rather than echoed by the model, preventing the patch response from acquiring structural authority.
- The LiteLLM authoring client now has a dedicated patch operation. It receives only the affected screens, scoped source scenes, accepted findings, and editable paths, then compiles replacements into the checkpointed draft.
- Patch compilation preserves screen identity, type, lineage, neighboring content, scenario branch IDs, diagram IDs/positions, and concept-card IDs. Protected or extra fields and structural list-count changes are rejected.
- The controller rehydrates assessments and scenario navigation, reruns deterministic validation, and projects only changed learner-copy fields into the scoped semantic re-review.
- Added deterministic no-op and stable-finding recurrence stops. Workspace v4 records finding signatures and revised paths so scoped review behavior survives checkpoints.
- Set the production default to one repair pass. A second remains possible only through an explicit policy override for evaluation.
- Verification: 463 e-learning tests passed; the full suite passed with 1,926 tests and 14 skips.

---

## Task 7: Constrain Upstream Screen Volume and Directions

**Purpose:** Reduce cost and fragility caused by excessive screens and directions that do not match components.

- [x] Locate the exact e-learning modality/workflow prompt and contract responsible for per-beat screen expansion.
- [x] Write failing generic planner tests for total screen budgeting and capability-compatible content directions.
- [x] Replace open-ended screens-per-beat guidance with a total course screen budget informed by required content and target duration.
- [x] Permit consolidation into tabs, cards, disclosures, or structured lists only when the selected component supports the required learner action.
- [x] Ensure required RLO content and approved assessments cannot be omitted merely to meet the screen budget.
- [x] Return a clear planning conflict when required content cannot fit, rather than creating an oversized or incomplete plan.

**Verification:**

```bash
python -m pytest tests/planners/workflow/elearning -q
python -m pytest tests/tools/elearning -q
```

**Exit criteria:** Planner outputs have an explicit total screen budget, retain required content, and contain authorable component directions.

### Task 7 execution record

- Located the multiplier in the e-learning workflow-planner prompt, now at `src/learning_pipeline/prompts/workflow_planner/elearning.md`: the former “3–5 screens per instructional beat” guidance scaled screen count with every modality scene.
- Replaced it with a deterministic whole-course budget. The budget uses the learner duration limit when present, otherwise scene duration targets or a 20-minute default, and is bounded to 6–15 learner-facing screens.
- Added the budget and its counting rule to the private planner payload; no new public production contract was introduced. Prompt version is now `elearning_v5`.
- Grouped knowledge checks count once per approved item because deterministic assembly expands them into one learner-facing screen per question.
- Validation requires every assessment-bearing source scene to map to a knowledge-check requirement and preserves existing all-scene coverage. It reports an explicit planning conflict rather than permitting required content to be omitted.
- Consolidation guidance is limited to components whose declared learner action supports the intended behavior; the existing component/action validator remains the deterministic enforcement boundary.
- Updated the deterministic reference workflow to retain its approved assessment under the same rule.
- Verification: 557 focused planner/authoring tests passed; the full suite passed with 1,931 tests and 14 skips.

### Task 7 policy amendment — 2026-07-29

- Live UI evaluation showed the 6–15 screen ceiling was an incorrect course-wide constraint. A broad blueprint selected 20 approved assessment items across ten RLOs; the fixed ceiling rejected the contract before workflow planning even though no learner reported a bloated-course problem.
- Removed the numeric screen budget, duration-derived screen formula, pre-model assessment-count conflict, and post-model maximum-screen validation.
- Retained the safeguards that matter: every modality scene remains covered, every contract-selected assessment remains required, grouped assessments still expand deterministically to one question per learner-facing screen, and the planner is directed to avoid artificial screens or unnatural consolidation.
- Course breadth must be handled during commissioning/content selection or through intentional module splitting, not by silently dropping contracted material or failing against an arbitrary renderer quota.

---

## Task 8: Add Outcome Telemetry and Regression Evaluation

**Purpose:** Prove the revision improves reliability and cost across topics rather than one sample course.

- [x] Emit workflow/task identifiers and existing LiteLLM/Langfuse correlation metadata for every author and review call.
- [x] Record call purpose, screen family, screen count, finding code/owner, repair outcome, tokens, cost, and elapsed time without recording sensitive learner data.
- [x] Build a representative evaluation set spanning simple and complex source shapes, assessments, scenarios, diagrams, and content-only screens.
- [ ] Run the same evaluation cases against the baseline and revised flow.
- [ ] Compare completion rate, model calls, input/output tokens, cost, repair rate, repeated findings, findings by owner, and elapsed time.
- [ ] Perform manual source-fidelity and learner-usability review on the generated outputs.
- [ ] Document remaining failures by owner; fix reusable rules or implementation rather than patching evaluated output.

**Verification:**

```bash
python -m pytest tests/tools/elearning tests/planners/workflow/elearning -q
python -m pytest -q
```

**Exit criteria:** The revised flow improves completion rate and reduces misrouted repairs/model calls without regressing source fidelity or the full test suite.

### Task 8 execution record (in progress)

- Existing workflow/task correlation remains inherited from the runtime telemetry context, grouping author, review, and patch observations under the UI-visible job ID in LiteLLM and Langfuse.
- Added non-sensitive observation attributes for call purpose, screen count/families, deterministic finding codes, author-patch finding codes/owners, and requested repair outcome.
- Extended the persisted authoring trace with elapsed seconds, finding counts by stable code, and resolved repair outcomes; existing token, cost, call-count, and owner metrics remain intact.
- Added an eight-case topic-neutral evaluation matrix covering simple and complex source shapes, grouped assessments, scenarios, diagrams, pedagogy as legitimate subject matter, mixed media, and checkpointed repair.
- Ran a real revised-flow ADKAR reference job through modality planning, workflow planning, course authoring, semantic review, and bundle assembly. It produced eight learner-facing screens and a valid ZIP. Authoring completed in 20.91 seconds with two model calls (draft and review), zero repairs, zero findings, 23,790 input tokens, and 1,017 output tokens.
- The live run surfaced a reusable source-boundary defect before authoring: repository assessments use the generic `multiple_choice` type while fidelity hydration accepted only `multiple_choice_single` or `multiple_choice_multi`. Added topic-neutral normalization based on the number of correct options and resumed the same checkpointed workflow successfully.
- Manual review found no pedagogical-rationale leakage, unsupported claims, assessment mutation, or learner-usability blocker. Both approved questions render separately with four options and one correct answer. A soft course-composition gap remains: the eight-screen budget used every screen for substantive content, leaving no dedicated title or completion screen and therefore no seat-time estimate.
- Directional comparison with the six persisted pre-revision workspaces is favorable but not controlled: the historical workspaces used 1–12 model calls, up to two repair attempts, and contained 53 unowned findings; the revised reference run used two calls, no repairs, and no findings. The remaining matrix cases still require controlled baseline/revised execution before the Task 8 exit criterion can be claimed.
- Langfuse recorded approximately $0.389 for the four live planning/authoring calls: $0.119 modality planning, $0.121 workflow planning, $0.099 author draft, and $0.051 semantic review. Application-side cost remains zero because local configured model-rate fields are zero; Langfuse is currently the authoritative measured-cost view.
- Discovered that request-body metadata reaches Langfuse only as nested proxy metadata, leaving the UI trace name as `litellm_request` and session ID empty. Added first-class `langfuse_*` proxy headers for generation name, trace, session/job ID, tags, and safe trace metadata. Because a learning job crosses newer and legacy executors, this acceptance criterion necessarily expanded telemetry wiring to all existing LiteLLM call paths: planning, commissioning, author/review/patch, Manim generation and TTS, podcast TTS, slide planning/fitting, embeddings, and image generation.
- Unit and focused integration coverage confirms the promoted headers. A post-change live Langfuse check is still pending: the host process does not have the running proxy's authenticated token, and the local development fallback token was rejected. No credential was copied from the running container.
- Current regression boundary: 1,936 tests passed and 14 skipped; `git diff --check` passes.

---

## Task 9: Rollout and Cleanup

**Purpose:** Adopt the revised path safely and remove only code made obsolete by this work.

- [ ] Decide whether rollout requires a temporary feature flag based on evaluation risk; do not add one by default.
- [ ] Version prompts and authoring workspaces so old checkpoints cannot be mistaken for compatible new state.
- [ ] Update prompt catalog and operational documentation for changed author/reviewer responsibilities.
- [ ] Remove only helpers, imports, and fields made unused by completed tasks.
- [ ] Run the complete test suite and one real end-to-end e-learning job.
- [ ] Confirm downloadable output, job status, telemetry correlation, and checkpoint behavior.
- [ ] Record final before/after metrics and any deliberately deferred findings.

**Verification:**

```bash
python -m pytest -q
git diff --check
git status --short
```

**Exit criteria:** The revised flow is the documented default, all tests pass, a real course completes end to end, and no temporary output patches or unrelated refactors are included.

## Progress Summary

- [x] Task 1 — Baseline and boundaries
- [x] Task 2 — Finding ownership and routing
- [x] Task 3 — Assignment compiler and preflight
- [x] Task 4 — Component-specific learner-copy output
- [x] Task 5 — Learner-visible semantic review
- [x] Task 6 — Targeted patch revisions
- [x] Task 7 — Screen volume and planner directions
- [ ] Task 8 — Telemetry and evaluation
- [ ] Task 9 — Rollout and cleanup

Implementation should stop at the end of each task if its exit criteria are not met. Any newly discovered requirement must be added to this document with its rationale before expanding code scope.
