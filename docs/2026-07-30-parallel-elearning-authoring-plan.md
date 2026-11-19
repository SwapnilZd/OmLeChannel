# Parallel E-Learning Authoring Plan

Date: 2026-07-30
Branch: `feature/heygen-captions`

## Objective

Reduce e-learning course-authoring wall time by generating independent initial
screen batches concurrently, without changing course scope, screen order,
review quality, cost accounting, or checkpoint recovery.

The semantic review and repair loop will remain sequential because each of those
steps depends on the result of the preceding step.

## Current state and baseline

- [x] Confirm initial authoring batches receive disjoint screen IDs and scoped
  source context.
- [x] Confirm initial batches do not consume another batch's generated copy.
- [x] Confirm the controller currently mutates and checkpoints one shared
  `AuthoringWorkspace` after every sequential batch.
- [x] Confirm media tasks already use workflow dependencies and are outside this
  controller change.
- [x] Record a representative baseline: the recent five authoring batches took
  approximately 132 seconds in total; the complete authoring task took
  approximately 182 seconds.

## Scope decisions

- Parallelize only initial authoring batches in the first implementation.
- Keep intent planning, deterministic validation, semantic review, revisions,
  hydration, finalization, and bundle assembly ordered.
- Use a private controller concurrency limit of three for the POC. Do not add a
  new workflow or content contract solely for this setting.
- Keep one coordinator responsible for workspace mutation, usage aggregation,
  deterministic merging, and checkpoint writes. Concurrent batch calls return
  immutable results and never write the shared workspace directly.
- Preserve LiteLLM as the owner of provider retries and timeouts.
- Preserve the existing screen batch size of eight.

## Implementation progress

### 1. Establish stable batch identities

- [x] Build canonical batches from the complete ordered set of authorable screen
  IDs, rather than rebatching only the currently missing IDs.
- [x] On checkpoint resume, remove already-authored screens from their canonical
  batch while retaining the original batch number and order.
- [x] Skip a canonical batch when all of its screens are already present.
- [x] Continue using the approved requirement order as the sole authority for
  final screen order.

Verification:

- [x] A partial checkpoint resumes only missing screens without changing batch
  identity.
- [x] Out-of-order completion cannot change final screen order.

### 2. Add bounded concurrent generation

- [x] Extract the provider call for one initial batch into an async operation
  that receives an immutable workspace snapshot and returns its batch identity,
  response, and elapsed time.
- [x] Launch at most three batch operations concurrently.
- [x] Wait for all launched operations to settle so successful paid responses
  can be retained even when another batch fails.
- [x] Do not parallelize semantic review or any repair call.
- [x] Keep the existing client interface and structured response models.

Verification:

- [x] A test client records more than one active batch call.
- [x] Peak active calls never exceeds three.
- [x] Review begins only after every required initial batch has completed and
  merged successfully.

### 3. Preserve model and cost policy

- [x] Before launching a wave, verify the model-call budget can admit every call
  in that wave while reserving the required semantic-review call.
- [x] Count each completed response exactly once when the coordinator records
  usage.
- [x] Aggregate input tokens, output tokens, and estimated cost in canonical
  batch order for deterministic traces.
- [x] Retain the existing hard failure when returned usage exceeds a configured
  budget.
- [x] Run initial batches sequentially when a hard per-task input-token,
  output-token, or cost ceiling is configured; concurrent in-flight provider
  calls cannot be reliably cancelled after such a ceiling is crossed.

Verification:

- [x] Insufficient call budget fails before any parallel provider call starts.
- [x] Parallel and sequential execution report identical call counts and summed
  usage for the same fake responses.
- [x] Configured token or cost ceilings select the sequential path.

### 4. Merge and checkpoint safely

- [x] Merge successful responses through the existing protected-structure merge
  logic in canonical batch order, regardless of completion order.
- [x] Hydrate approved assessments and deterministic scenario navigation after
  each coordinator merge, as the sequential flow does today.
- [x] Persist a uniquely named checkpoint for each successfully merged canonical
  batch.
- [x] Update the mutable workspace checkpoint only from the coordinator.
- [x] If one or more calls fail, first checkpoint every successful response and
  then raise the first actionable failure.
- [x] On task retry, reuse successful batches and call the model only for screens
  that remain missing.

Verification:

- [x] A deliberately delayed earlier batch still appears before a faster later
  batch in the finished course.
- [x] A mixed success/failure wave leaves a valid resumable checkpoint.
- [x] Retrying that wave does not regenerate or recharge completed batches.
- [x] Concurrent execution never creates a partial or corrupt workspace JSON
  file.

### 5. Improve operational visibility

- [x] Log canonical batch number, screen IDs, queue/start/completion timing, and
  active concurrency for each batch.
- [x] Preserve workflow ID, task ID, model alias, and job/session metadata on
  every LiteLLM/Langfuse call.
- [x] Add trace fields for sequential versus parallel mode, peak concurrency,
  and total initial-batch wall time.
- [x] Avoid logging prompts, credentials, or full generated learner copy.

Verification:

- [ ] One job can be filtered in Langfuse and shows all batch calls under the
  same workflow/job metadata.
- [ ] Worker logs make batch overlap and the critical path visible without
  exposing content.

### 6. Automated verification

- [x] Add controller tests for bounded overlap, deterministic merge order, and
  review-after-join behavior.
- [x] Add checkpoint tests for out-of-order success, one-batch failure, and
  retrying only missing screens.
- [x] Add budget tests for admission control, exact usage aggregation, and
  sequential fallback under hard token/cost ceilings.
- [x] Retain tests proving a full course passes deterministic validation and
  semantic review after parallel drafting.
- [x] Run all e-learning authoring and bundle tests (`478 passed`).
- [x] Run the full repository test suite (`2051 passed, 14 skipped`).

### 7. Runtime acceptance

- [x] Rebuild the real e-learning worker.
- [ ] Run one representative course with at least four initial authoring batches.
- [ ] Confirm model-call count and generated screen membership match sequential
  behavior.
- [ ] Confirm screen order, assessments, video slots, and final package remain
  correct.
- [ ] Confirm no duplicate LiteLLM calls occur during checkpoint resume.
- [ ] Compare initial-batch and total authoring wall time with the recorded
  baseline.
- [ ] Target at least a 40% reduction in initial-batch wall time without an
  increase in model-call count.

## Failure semantics

- A provider failure in one batch must not discard successful sibling batches.
- A batch response that violates its screen contract must fail that batch and
  must not alter the shared draft.
- Budget admission failure must occur before launching a wave.
- Post-response budget failure remains blocking and retains completed usage in
  the diagnostic checkpoint.
- Semantic findings continue through the existing bounded sequential repair
  loop; parallel drafting does not weaken publication review.

## Definition of done

Initial authoring batches execute with a maximum concurrency of three, merge in
approved order, preserve exact usage accounting and resumable checkpoints, and
produce a course that passes the existing deterministic and semantic gates. A
representative real run demonstrates at least a 40% reduction in initial-batch
wall time with no additional model calls or content omissions.
