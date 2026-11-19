# Agentic Content Production Plan

## Objective

Evolve content production from a one-shot structured generation call into a
bounded agentic workflow that can inspect its assignment, plan its work, use
approved tools, critique its output, revise it, and resume safely from persisted
working memory.

The agent must still operate inside the framework already established by the
pipeline. It does not select RLOs, choose a modality, reorder scenes, add screens,
or change production capabilities.

The initial implementation target is `elearning.course.author`. Podcast scripts
and Manim narration should adopt the pattern only after the e-learning workflow
passes its evaluation gates.

## Product-level content charter

Every content-producing agent should receive the following invariant:

> Produce polished Deloitte corporate-training content that teaches the approved
> subject matter directly to the learner. Planning metadata and pedagogical
> rationale may shape the experience, but must not appear in learner-facing
> content unless the approved subject matter itself explicitly discusses them.

The agent must distinguish four kinds of information:

1. **Subject matter** — approved facts, concepts, examples, scenarios, rules,
   assessments, and guidance that may be presented to the learner.
2. **Production direction** — instructions about sequence, screen type, media,
   accessibility, interaction, and emphasis. These shape the output but are not
   themselves learner-facing copy.
3. **Internal rationale** — explanations of why an instructional technique was
   selected, such as recall load, scaffolding, engagement, pedagogy, Bloom level,
   or teaching-pattern rationale. This remains internal unless it is itself the
   approved topic.
4. **Learner-facing content** — publication-ready copy that speaks directly about
   the subject and the learner's task, decision, or practice.

Example transformation:

- Internal rationale: "Grouping eight items into three phases reduces recall
  load."
- Learner-facing copy: "Use the three phase headings to reconstruct the eight
  steps in order."

## Current-state findings

### What should remain unchanged

- Curriculum assembly owns RLO selection, tailoring, and sequencing.
- Modality planning owns the learning experience and pedagogical affordances.
- Workflow planning owns screen requirements, media slots, and production order.
- `ProductionCompiler` and `BuildPlan` remain the executable authority.
- `DAGRunner` remains a deterministic task scheduler; it does not become an
  autonomous planning agent.
- Existing screen schemas, slot preservation, source-scene lineage, artifact
  storage, worker capability routing, and bundle assembly remain authoritative.

### What is currently called agentic but is not yet an agent loop

`RealElearningCourseAuthorExecutor` currently:

- builds one large authoring payload;
- makes one structured generation call;
- retries provider or parse failures with `repair_feedback`;
- validates and publishes the resulting draft;
- stores one draft as an idempotency cache.

It does not currently:

- create an internal writing plan;
- call content-inspection or validation tools;
- distinguish source content from internal instructional rationale;
- critique publishability or grounding;
- revise valid-but-poor content;
- persist a resumable working state;
- use its configured internal-tool budget (`max_internal_tool_calls` is zero).

### Existing patterns to reuse

`ManimGenerationController` already supplies the main implementation pattern:

- a bounded state machine;
- explicit model-call and repair budgets;
- typed failure classes;
- stage checkpoints in the artifact store;
- input-hash-based idempotency;
- resume from the latest valid checkpoint;
- accumulated usage and cost accounting;
- a final structured trace.

The authoring workflow should follow this pattern rather than introducing a
second orchestration framework.

### Source of the current rationale leakage

The context resolvers flatten structured RLO component content into a plain text
`ResolvedContentItem`. Keys such as `reasoning` remain in the same content string
as learner-facing fields such as `setup` and `grouping`.

The modality planner can then promote that reasoning into `content_direction`,
the workflow planner can restate it as an explicit screen instruction, and the
course author is currently told to respect that instruction. There is no final
publishability review that distinguishes an instructional-design reason from
the subject being taught.

Agentic revision helps at the final boundary, but the shared charter must also be
applied upstream so each stage preserves the distinction.

### Adjacent correctness issues to resolve before agentic rollout

- `PlanningContextResolver` currently serializes assessment option text and the
  correctness flag but omits each option's diagnostic feedback. The authoring
  prompt nevertheless requires that feedback to be copied exactly. The resolved
  context must carry the approved feedback before an agent is allowed to author
  or revise assessment screens.
- When image generation is disabled, the real author executor currently publishes
  a transparent placeholder PNG for model-requested assets. The real agent must
  either be prohibited from requesting images or use an implemented real image
  capability; it must fail closed rather than silently publishing a placeholder.
- SDK-level automatic retries are not reflected in the current semantic
  `model_call_count`. Agentic budgets must distinguish provider transport retries
  from semantic agent turns and account for both accurately.
- The current persisted draft is reused based on an input hash that includes
  `_DEFAULT_POLICY` rather than the actual injected policy. Workspace cache keys
  must use the effective configuration.

## Target architecture

```text
Existing ElearningAuthoringBrief (immutable assignment)
                         |
                         v
              AuthoringAgentController
                         |
        +----------------+----------------+
        |                |                |
        v                v                v
  scoped context     screen schema    policy/quality
      tools              tools             tools
        |                |                |
        +----------------+----------------+
                         |
                         v
              persisted AgentWorkspace
                         |
       plan -> draft -> validate -> review -> revise
                         |
                         v
       existing deterministic CourseContent builder
                         |
                         v
               existing bundle assembler
```

The agent controller lives inside `elearning.course.author`. To the workflow
compiler and DAG runner, the task type and output contract remain unchanged.

## Agent authority and non-goals

The agent may:

- inspect only the resolved scenes assigned to each required screen;
- inspect the schema for a required screen type;
- create an internal content intent for each required screen;
- draft the required content fields;
- validate schema, lineage, grounding, tone, and publishability;
- revise only screens that fail review;
- persist checkpoints and finalize a validated course draft.

The agent may not:

- select, remove, or reorder RLOs or modality scenes;
- add, remove, rename, reorder, or change the type of a required screen;
- add or remove video slots;
- change learning objectives or assessment answers;
- call arbitrary network, filesystem, shell, or provider tools;
- browse for additional instructional content;
- modify the `BuildPlan` or invoke another production capability;
- finalize while a required validation finding remains unresolved.

## Working memory

Working memory should be structured external state, not an indefinitely growing
chat transcript. Executor-private Pydantic models are appropriate; no new
cross-stage planning contract is required.

Suggested `AuthoringWorkspace` fields:

- workflow ID, task ID, input hash, and workspace version;
- immutable assignment summary and required screen order;
- shared content-charter version;
- per-screen source IDs and extracted source ledger;
- per-screen content intent;
- explicit internal-only notes and rationale exclusions;
- current draft revision;
- validation and review findings;
- resolved findings and revision history;
- model/tool call counts, tokens, cost, and elapsed time;
- current state and allowed next actions;
- artifact URIs for every persisted checkpoint.

Persist artifacts under the existing namespace:

```text
artifact://elearning/{workflow_id}/
    {deliverable_id}-workspace.json
    {deliverable_id}-intent-plan.json
    {deliverable_id}-draft-r1.json
    {deliverable_id}-review-r1.json
    {deliverable_id}-draft-r2.json
    {deliverable_id}-completed.json
    {deliverable_id}.authoring-trace.json
```

The workspace input hash must include:

- the complete `ElearningAuthoringBrief`;
- resolved-context hash;
- authoring prompt version;
- content-charter version;
- review-rubric version;
- actual configured policy values;
- content-builder version.

This corrects the current use of `_DEFAULT_POLICY` in the input hash when a
different policy is injected.

## Bounded tool set

Tools are read-only or write only inside the task's artifact namespace.

### `inspect_assignment`

Returns the immutable screen requirements, authoring direction, screen order,
brand constraints, accessibility requirements, and policy limits.

### `inspect_scene_context`

Accepts only scene IDs assigned to the current screen. Returns a scoped source
ledger containing source IDs and approved instructional material. It also labels
planning-only fields and likely internal rationale for the agent's attention;
it does not silently delete source material.

### `inspect_screen_schema`

Returns the required and optional content fields for the already-selected screen
type, including assessment exact-copy rules and cross-reference constraints.

### `validate_draft`

Runs existing deterministic validation:

- `ElearningCourseAuthorDraft` parsing;
- expected screen IDs, types, and order;
- required content fields;
- unsafe-content checks;
- `ElearningCourseContentBuilder` validation;
- slot preservation;
- assessment-answer preservation;
- source-scene lineage.

It returns structured findings instead of throwing away useful repair context.

### `review_publishability`

Runs the versioned content-quality rubric against each screen. It identifies:

- pedagogical or production rationale exposed as learner copy;
- unsupported instructional claims, examples, or conclusions;
- planning labels, internal IDs, or implementation terminology;
- unnecessary repetition or field padding;
- tone inconsistent with Deloitte corporate learning;
- copy that describes what learners generally do instead of teaching the
  assigned learner;
- mismatch between the screen's learning objective and its actual content.

The first version should combine deterministic signals with a bounded semantic
review. A word blacklist alone is not sufficient because courses can legitimately
teach pedagogy, cognition, or learning design.

### `save_checkpoint`

Persists the current validated workspace revision atomically. The controller,
not the model, selects the namespace and filename.

### `finalize`

Available only when deterministic validation passes and no blocking review
findings remain. It hands the draft to the existing builder and publication path.

## Agent state machine

```text
LOAD_ASSIGNMENT
      |
      v
INSPECT_CONTEXT_AND_SCHEMAS
      |
      v
PLAN_SCREEN_INTENTS
      |
      v
DRAFT_REQUIRED_SCREENS
      |
      v
DETERMINISTIC_VALIDATION ---- structural failure ----> REVISE
      |
      v
PUBLISHABILITY_REVIEW ------- blocking finding ------> REVISE
      |                                              ^
      +---------------- bounded loop ----------------+
      |
      v
FINALIZE_AND_PUBLISH
```

The controller enforces legal transitions. The model may select among the tools
available in the current state but cannot skip gates or manufacture a successful
tool result.

Recommended initial bounds:

- maximum 4 semantic model calls: intent plan, initial draft, review, revision;
- maximum 12 internal tool calls;
- maximum 2 revision cycles;
- one task-level timeout and one cumulative cost ceiling;
- fail closed when any budget is exhausted.

These values should remain explicit `AgenticExecutionPolicy` configuration and
be adjusted from evaluation evidence, not hidden environment switches.

## Client and model integration

Keep LiteLLM as the only model gateway and retain the functional alias
`elearning-course-authoring` initially.

Before implementation, run a small compatibility spike to confirm that the
current LiteLLM/OpenAI Responses path supports:

- function/tool calling;
- typed tool arguments;
- structured final output parsing;
- usage reporting across multiple turns;
- cancellation and timeout behavior.

If native tool calls and structured final parsing cannot be combined reliably,
the controller should orchestrate typed model steps explicitly. It must not fall
back to an unconstrained conversational loop.

Do not add separate model aliases for every internal step until usage data shows
that different models or reasoning settings are warranted.

## Prompt organization

Add one versioned shared prompt fragment for the product-level content charter
and publication boundary. Compose it into:

- e-learning modality planning;
- e-learning workflow planning;
- e-learning course authoring and review;
- podcast script writing;
- Manim narration/script writing where the model authors learner-facing text.

Stage prompts then add role-specific instructions:

- modality planning uses rationale to choose experience but does not place it in
  learner-facing `content_direction`;
- workflow planning describes what a screen should communicate, not why the
  selected pedagogy works;
- authoring treats all upstream direction as production guidance until it has
  translated it into publishable subject-matter copy;
- reviewing checks the final output, not just schema conformance.

## Implementation layout

Suggested files:

```text
src/learning_pipeline/prompts/shared/
    learner_facing_content_v1.md

src/learning_pipeline/prompts/elearning_author/
    course_author_agent_v1.md
    course_review_v1.md

src/learning_pipeline/tools/elearning_bundle/
    _authoring_controller.py
    _authoring_workspace.py
    _authoring_tools.py
    _authoring_review.py
```

Primary files to update:

- `_authoring_client.py` — support bounded agent turns/tool calls and cumulative
  usage rather than one final draft call;
- `executor_real_author.py` — delegate orchestration to the new controller while
  preserving the existing executor input/output contract;
- `_author_contracts.py` — add executor-private workspace, finding, action, and
  trace models without changing the production-plan contract;
- `_agentic_policy.py` — enforce cumulative tool, model, repair, timeout, token,
  and cost limits;
- `course_author_v1.md`, modality prompt, and workflow prompt — compose the shared
  charter and clarify publishable versus internal guidance;
- commissioning job APIs/UI — expose authoring trace and review summary after the
  core workflow is stable.

## Phased delivery

### Phase 1 — Charter and regression baseline

- [x] Add the versioned shared learner-facing content charter.
- [x] Apply it to the e-learning modality, workflow, and author prompts.
- [x] Capture the rationale-leak failure mode as a topic-neutral regression test.
- [x] Add examples where pedagogical terms are genuinely the subject matter so
      the policy does not become a crude terminology ban.
- [x] Include approved assessment feedback in the resolved planning context and
      add exact-copy coverage tests.
- [x] Reject generated asset requests in real authoring until a real image
      capability is wired; remove the transparent-placeholder behavior from the
      real execution path.
- [ ] Establish baseline outputs, model calls, latency, and cost.

Exit gate: the one-shot author no longer publishes the known recall-load leakage
in the regression fixture, and existing structural tests remain green.

### Phase 2 — Workspace and deterministic tools

- [x] Add executor-private workspace and review-finding models.
- [x] Implement assignment, scoped-context, schema, validation, checkpoint, and
      finalize tools.
- [x] Persist and reload workspace checkpoints using `ArtifactStore`.
- [x] Include actual policy and prompt versions in the idempotency hash.
- [x] Add resume, corrupt-checkpoint, and input-mismatch tests.

Exit gate: a fake client can execute and resume the complete state machine with
zero live model calls.

### Phase 3 — Bounded agent controller

- [x] Implement legal states and allowed actions.
- [x] Enforce cumulative model/tool/cost/token/time budgets.
- [x] Add typed failure categories for policy, tool, validation, review, and
      infrastructure failures.
- [x] Accumulate full trace data across all turns and revisions.
- [x] Ensure rerunning a failed workflow resumes from the latest compatible
      checkpoint.

Exit gate: tests prove the agent cannot alter screen scope, skip validation,
exceed budgets, or finalize with blocking findings.

### Phase 4 — Semantic review and revision

- [x] Implement the versioned publication-readiness rubric.
- [x] Add per-screen review with evidence and a concrete revision request.
- [x] Revise only failing screens while preserving approved screens exactly.
- [x] Re-run deterministic validation after every revision.
- [x] Preserve assessment wording and correct answers through revision.

Exit gate: all curated leakage, grounding, tone, and repetition cases pass, with
no regression in schema or lineage validation.

### Phase 5 — Real client integration

- [ ] Complete the LiteLLM tool-calling compatibility spike.
- [x] Implement real agent turns using `elearning-course-authoring`.
- [x] Record cumulative usage and estimated cost.
- [ ] Exercise timeout, malformed tool call, provider failure, and cancellation
      paths.
- [ ] Compare agentic output against the existing one-shot author across a broad
      topic set.

Exit gate: the agentic path produces consistently publishable courses within the
agreed cost and latency envelope.

### Phase 6 — Observability and operator experience

- [x] Add review status and revision count to the authoring trace.
- [ ] Expose workspace summary, findings, and trace from the job detail API.
- [ ] Add a job-detail view showing assignment, decisions, revisions, and final
      validation without exposing hidden model chain-of-thought.
- [ ] Include trace artifacts under "Other files" for completed jobs.
- [ ] Make rerun behavior show whether a checkpoint was reused.

Exit gate: an operator can explain why content was revised and what source
material supports the final result.

### Phase 7 — Controlled expansion

- [ ] Move podcast spoken-copy generation out of the one-call workflow planner
      into a bounded script-authoring executor while leaving segment requirements
      and order under workflow planning.
- [ ] Apply the shared charter and review tooling to podcast dialogue.
- [ ] Apply the review boundary to Manim narration; retain the existing render
      repair controller for code/render failures.
- [ ] Evaluate each capability independently before enabling the next.

Exit gate: each new content-producing capability passes the same publication,
grounding, budget, trace, and resume requirements.

## Evaluation suite

The evaluation set should cover broad topics and include at least:

- the Kotter three-phase memory-aid leakage case;
- source content containing explicit instructional-design rationale;
- a course whose actual subject is learning science or pedagogy;
- exact-copy assessment questions and feedback;
- scenarios with only partial source support;
- highly technical material where simplification could introduce false claims;
- compliance or policy material requiring conservative wording;
- overlapping RLOs that invite repetition;
- mixed authored-screen and Manim-slot courses;
- a failed run resumed after draft, review, and revision checkpoints.

Score each output on:

- source grounding and lineage;
- learner-facing versus internal-rationale separation;
- objective coverage;
- required screen and assessment fidelity;
- Deloitte corporate-learning tone;
- concision and non-repetition;
- accessibility;
- schema and bundle validity;
- model calls, tool calls, latency, and cost;
- retry and resume behavior.

## Definition of done

The first agentic authoring release is complete when:

- the external `elearning.course.author` contract and BuildPlan remain unchanged;
- the agent cannot alter upstream selection, sequence, modality, or screen scope;
- every final draft passes deterministic validation and semantic publication
  review;
- pedagogical rationale is used internally without leaking into learner-facing
  content, except when it is explicitly the approved subject;
- working memory is persisted, inspectable, versioned, and safely resumable;
- all loops have enforced model/tool/revision/time/token/cost bounds;
- traces explain tool use, findings, revisions, source lineage, and usage without
  storing private chain-of-thought;
- the current test suite and the new evaluation suite pass;
- no reference/fake content path is introduced into the real agent workflow.
