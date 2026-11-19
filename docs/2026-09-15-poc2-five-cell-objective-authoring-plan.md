# POC2 Five-Cell Objective and RLO Authoring Plan

## Scope decision

POC2 will create and author RLOs for exactly these Content-Type × Bloom cells:

| Content type | Bloom level | Intended learner performance |
| --- | --- | --- |
| Fact | Remember | Retrieve a precise fact from an appropriate cue. |
| Concept | Understand | Explain or distinguish a concept using its critical attributes. |
| Concept | Apply | Classify a novel, unambiguous case using the concept's attributes. |
| Process | Understand | Explain or reconstruct stages, actors, dependencies, and transitions. |
| Procedure | Apply | Execute supported steps and decision points in a novel standard case. |

This is narrower than the previously implemented thirteen-cell matrix. The active
POC2 prompts, methodology profiles, review controls, and authoring validators should
only contain instructions for these five cells.

An objective must not be forced into one of the five cells merely to keep it in the
pipeline. If its actual performance does not fit, the system should preserve it for
review as outside the POC2 authoring scope and stop before approval or authoring model
calls.

## Current baseline

- Objective classification accepts thirteen cells.
- RLO target planning and observed classification use the same thirteen-cell rules.
- Authoring methodology contains thirteen profiles and sends the selected profile to
  generation and review operations.
- Current local objective candidates occupy eight distinct cells. One of those,
  Concept × Analyze, is outside the new scope.
- The nine current local RLO drafts use four of the five selected cells: Fact ×
  Remember, Concept × Understand, Concept × Apply, and Procedure × Apply. There is no
  current Process × Understand draft.
- Existing stored objectives and drafts must remain readable; this change must not
  delete or rewrite historical records.

## Observable outcome

After implementation:

1. Objective discovery is directed toward performances that can land in one of the
   five POC2 cells.
2. Classification returns one of those five cells or an explicit outside-scope
   result. It never substitutes a permitted cell for a materially different
   performance.
3. A reviewer can see why an objective is outside scope but cannot approve it for RLO
   generation.
4. Batch creation and workers deterministically reject an outside-scope objective
   before any authoring model call.
5. Suggested, Target, and Observed classification all use the same five-cell policy.
6. RLO authoring receives guidance only for the selected five cells.
7. Existing out-of-scope records remain available for audit and export but cannot be
   newly generated, repaired, approved, or published in POC2.

## Implementation approach

### 1. Define one deterministic POC2 cell policy

Add a small shared policy module containing the five canonical string pairs and a
membership check. Use it everywhere the application makes an eligibility decision.

Do not remove historical enum values from persisted contracts or the versioned RLO
schema. They are needed to deserialize existing records. The new policy controls what
POC2 may create and author; backward-compatible parsing does not make the other cells
executable.

The policy must not be configurable through a new environment variable. POC2 has one
agreed scope, and every service in this repository should apply it consistently.

### 2. Narrow objective discovery without making it classify prematurely

Update the active candidate-formation, related-objective-discovery, and coverage-gap
instructions with a short POC2 performance boundary:

- precise fact retrieval;
- concept explanation or distinction;
- concept classification in a novel clear case;
- explanation or reconstruction of a multi-actor process; and
- execution of a learner procedure in a novel standard case.

Continue to form objectives from supported learner performance rather than keywords.
These operations should not assign the final Kind/Bloom cell. They should avoid
proposing work whose defining demand is argumentation, diagnosis, tailoring,
principle-based judgment, evaluation, or another performance outside the five-cell
boundary.

This is a generation preference rather than the only enforcement point. The
deterministic classification and approval gates below remain responsible for scope
control.

### 3. Replace the active classification rubric with the five-cell rubric

Rewrite the shared production classification asset so it defines only:

- Fact and Remember as Fact × Remember;
- Concept and Understand/Apply as Concept × Understand or Concept × Apply;
- Process and Understand as Process × Understand; and
- Procedure and Apply as Procedure × Apply.

Retain only boundary rules needed to distinguish these cells, including:

- a Fact is discrete retrieval, while a Concept depends on attributes;
- Concept × Understand explains or distinguishes familiar cases;
- Concept × Apply classifies a novel, unambiguous case;
- a Process is a multi-actor flow, while a Procedure is the learner's own execution;
- workplace context alone does not establish Apply; and
- classification follows actual required practice, not a surface verb.

Remove production instructions for Fact × Understand, all Analyze or Evaluate cells,
Process × Apply, Procedure × Analyze, and all Principle cells. Bump the prompt asset
versions and update the prompt catalog and prompt-integrity tests.

Change the classification response so it can represent either:

- `supported`, with exactly one of the five classifications; or
- `outside_poc2_scope`, with no executable classification and a concise reason tied
  to the objective's actual performance.

The repair call may repair malformed output once, as it does now. It must not turn an
outside-scope result into a permitted cell unless the original objective actually
meets that cell definition.

### 4. Preserve outside-scope candidates visibly

Store a candidate's POC2 eligibility separately from confidence and source support.
Outside-scope is a capability boundary, not low confidence, weak evidence, or a model
failure.

In objective review:

- label the candidate `Outside POC2 authoring scope`;
- display the classifier's short reason;
- disable approval and explain that no RLO generation will start;
- continue to allow rejection or objective revision; and
- never silently omit the candidate from review merely because it is outside scope.

When a revision changes the actual objective performance, classification must run
again before the candidate can become eligible. Do not let a reviewer manually attach
an unsupported cell to unchanged objective wording.

### 5. Enforce the boundary before authoring

Add deterministic checks at both transition points:

1. The objective approval endpoint refuses approval when the current classification
   is absent or outside the five-cell policy.
2. Generation-batch and draft-job creation independently validate eligibility so an
   older client, stale review, or existing database row cannot bypass the endpoint.

The response should identify the objective and say that its Content-Type × Bloom cell
is outside POC2 scope. This stop must occur before target classification or any other
RLO authoring operation is recorded.

If an out-of-scope job was already queued before deployment, the worker should mark it
non-retryable with the same scope reason without making a model call. It should not
fail the other objectives in the batch.

### 6. Reduce authoring methodology to five profiles

Keep only these methodology profiles in the active profile registry:

- `fact-remember`;
- `concept-understand`;
- `concept-apply`;
- `process-understand`; and
- `procedure-apply`.

Remove the other eight profiles and their cell-specific generation instructions from
the active code and compressed authoring guidance. Keep shared seven-part guidance
that applies to all five cells.

The five retained profiles should remain prioritized creative briefs rather than
literal checklists. Source integrity, coherent instruction, and supported assessment
remain more important than accumulating every preferred activity shape.

Update the human-readable authoring reference so it lists only the five accepted
cells and their relevant guidance. Preserve the two supplied `.docx` files unchanged
as source artifacts; they are not production prompt assets or accepted POC2 scope.

### 7. Constrain Target and Observed classification

RLO target planning must receive only the five profiles. Its output contract must
reject any other cell before generation proceeds.

Pedagogy review and observed classification must use the same five-cell rubric. If the
authored experience drifts outside its approved target, report a classification
mismatch. Do not repair that mismatch by introducing instructions from one of the
excluded cells.

The bounded revision workflow may repair content within an approved five-cell target,
but cannot change the target to an excluded cell or reopen unrestricted
classification analysis.

### 8. Handle existing records without destructive migration

Do not rewrite stored workspace revisions, objective decisions, drafts, published RLO
documents, or prompt snapshots.

On read, derive current POC2 eligibility from the stored classification. Historical
records outside scope remain visible. For an existing out-of-scope draft:

- allow viewing, provenance inspection, history, and export;
- disable retry, scoped model revision, approval, and publication; and
- show that the record predates or falls outside the current POC2 cell policy.

No current local authored draft requires this treatment, but the behavior must be
covered for deployments with different data.

## Documentation changes

Update these maintained references during implementation:

- `docs/rlo-authoring-guidance-by-content-type-and-bloom.md`: replace the thirteen-cell
  scope and cell briefs with the five accepted cells.
- `docs/rlo-generation-rules-reference.md`: state the five-cell POC2 decision clearly
  and remove language presenting thirteen cells as the accepted implementation scope.
- `docs/prompt-catalog.md`: update the exact active classification and methodology
  instructions and their versions.
- Objective-extraction and RLO-generation prompt READMEs: record the new scope,
  response contract, and prompt versions.

The original `.docx` files under `examples/RLO Generation Rules/` remain unchanged.

## Verification plan

### Contract and policy tests

- [x] Assert that the central POC2 policy contains exactly the five agreed cells.
- [x] Assert each of the five cells is accepted by objective, Target, methodology, and
  Observed contracts.
- [x] Assert each of the other eight formerly valid cells is non-executable.
- [x] Assert historical contracts can still deserialize persisted out-of-scope values.

### Prompt tests

- [x] Assert every active classification prompt names the same five cells.
- [x] Assert active production instructions contain no cell guidance for the excluded
  eight combinations.
- [x] Assert candidate discovery describes the five eligible performance families without
  assigning classifications itself.
- [x] Assert prompt versions, filenames, hashes, and catalog entries remain consistent.

### Objective workflow tests

- [x] Generate representative supported candidates for all five cells, including Process
  × Understand, which has no current local draft coverage.
- [x] Produce an outside-scope candidate and verify it remains visible but cannot be
  approved.
- [x] Verify revising an objective reruns eligibility and classification.
- [x] Verify one outside-scope candidate does not block review or generation of supported
  siblings.

### Authoring workflow tests

- [x] Verify an approved candidate in each of the five cells resolves to the correct
  methodology profile.
- [x] Verify an out-of-scope candidate creates no target-classification or authoring prompt
  run.
- [x] Verify target and observed classification cannot leave the five-cell set.
- [x] Verify existing out-of-scope drafts are read-only and exportable.
- [x] Verify bounded revisions preserve the approved cell.

### Container and UI verification

- [x] Run the focused objective, repository, RLO-generation, revision, API, and UI tests in
  the repository's test containers.
- [x] Run the full source-content test suite in containers.
- [x] Rebuild the API, source worker, and RLO worker containers.
- [ ] In the running application, review one supported candidate and one outside-scope
  candidate, then confirm only the supported candidate can start RLO generation.
- [ ] Author one Process × Understand RLO as the missing five-cell smoke case.

## Implementation checklist

- [x] Add the shared five-cell policy and eligibility contracts.
- [x] Narrow discovery prompts to the five eligible performance families.
- [x] Replace the active classification rubric and response with the five-cell scope.
- [x] Add objective review and approval enforcement.
- [x] Add generation-batch and worker enforcement before model calls.
- [x] Reduce methodology profiles and authoring guidance to five cells.
- [x] Constrain Target and Observed classification to the five-cell policy.
- [x] Make historical out-of-scope objectives and drafts visible but non-executable.
- [x] Update maintained prompt and authoring documentation.
- [ ] Complete every verification checkbox above.
- [x] Checkpoint the implementation on `feature/poc2-five-cell-scope` before deployment.

## Non-goals

- Do not design substitute activities for the eight excluded combinations.
- Do not retain excluded-cell instructions in production prompts for possible future
  use.
- Do not reclassify an objective inaccurately to make it authorable.
- Do not delete or rewrite historical data.
- Do not change source grounding, enrichment, model aliases, model-call budgets,
  commissioning retrieval, or content-production capabilities as part of this work.
- Do not combine the VM restart-policy work with this instructional-scope change.
