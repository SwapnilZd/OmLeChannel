# Bounded RLO Revision Controls Plan

Date: 2026-09-14

## Problem

The current RLO workflow validates a complete draft, automatically attempts up to two
repairs, and then exposes whatever findings remain. This keeps generation bounded, but
the repair step has too little control and the review page gives too little information
about what changed, why a repair failed, or what another attempt would cost.

`rlo-REL-01` makes the limitation visible. The validators correctly identified that its
Practice and Check activities did not demonstrate the approved Procedure × Apply
performance. Two repair passes replaced those activities, but both stayed within the
same multiple-choice interaction constraint and continued to present complete answers
for recognition. Repeating the same broad repair would spend more without changing the
underlying capability constraint.

The revision workflow should therefore support deliberate, reviewer-directed changes.
It should not automatically re-run every author and validator until something passes.

## Goals

- Give a reviewer enough information to decide whether a finding is material, a false
  positive, a local content problem, or a capability limitation.
- Allow a reviewer to select the exact findings and content areas to revise.
- Show the maximum model-call impact before a revision starts.
- Reuse all compatible generation and validation checkpoints.
- Stop immediately on a repeated finding, a no-op patch, or an exhausted budget.
- Preserve the best complete draft throughout the process.
- Keep immutable objective, source, evidence, claim-origin, and Target decisions outside
  an ordinary content-revision operation.

## Non-goals

- Do not add an unbounded autonomous critique-and-repair loop.
- Do not retry the entire RLO because one element is defective.
- Do not let a repair silently reclassify an objective or change its evidence boundary.
- Do not spend model calls fixing punctuation or other advisory preferences.
- Do not treat every validator suggestion as a publication blocker.
- Do not add richer interaction types as part of this revision-control work. The new
  controls should identify that requirement clearly rather than asking the model to
  improvise an unsupported interaction.

## Focused implementation checkpoint

The first vertical slice now provides selectable repairable findings, a zero-call scope
preview, a hard two-call ceiling, reviewer direction, element-bound patch enforcement,
one responsible validator, checkpoint reuse, token/call history, and no-op or repeated-
finding stops. Classification/capability findings and advisory writing notes are shown
as non-executable so they cannot accidentally consume revision calls.

Full re-analysis, manual field editing, false-positive disposition, richer interaction
types, and before/after visual diffs remain deferred. They are not implicit fallbacks
from the focused workflow.

## Reviewer Experience

### 1. Explain each finding

Each finding shown in RLO Review should include:

- a stable finding ID and plain-language title;
- blocking, review-needed, or advisory status;
- the responsible area: content, assessment, provenance, classification, deterministic
  structure, or review-system behavior;
- the affected part, element, and learner-facing excerpt;
- the rule or Target performance the finding is measured against;
- why the previous repair did or did not resolve it;
- whether the affected field is editable in an RLO revision; and
- the recommended next action.

Raw codes, JSON paths, prompt runs, and validator details remain available under
technical details but are not the primary explanation.

### 2. Show revision history as a comparison

Add a revision-history panel that records each generation and repair attempt. For each
attempt, show:

- the findings selected for repair;
- the parts and element IDs the model was allowed to change;
- the model operations and actual token usage;
- a concise before/after content diff;
- findings resolved, repeated, introduced, or reclassified; and
- the reason the loop stopped.

This history must be durable. Refreshing the page or restarting a worker must not lose
the explanation.

### 3. Provide bounded actions

The default action is **Revise selected issues**. The reviewer selects one or more
compatible findings, optionally supplies direction, and sees the proposed scope before
confirming.

Initial revision actions:

| Action | Allowed change | Maximum model calls | Revalidation |
|---|---|---:|---|
| Edit wording | Selected learner-facing fields in one element | 1 | Deterministic checks only unless the finding concerns meaning |
| Repair one content element | One named element | 2 | One repair plus its responsible semantic validator |
| Repair Practice and Check | Named assessment elements only | 3 | One repair, pedagogy review, and provenance review when claim references changed |
| Repair provenance references | Origin and claim references on named elements | 2 | One repair plus provenance review |
| Re-run one validator | No authoring change | 1 | The selected validator only |
| Full RLO re-analysis | No immediate authoring change | 3 | Grounding, provenance, and pedagogy; advanced action with an explicit warning |

The UI must never silently promote a scoped action into full re-analysis. When selected
findings require different owners or scopes, ask the reviewer to run separate revisions
rather than combining them into an ambiguous broad call.

### 4. Expose non-model decisions

Some findings cannot be repaired by another authoring call. Present the appropriate
decision instead:

- **Accept advisory note** records a reviewer disposition and spends no calls.
- **Mark as false positive** requires a note and preserves the original finding and
  validator output for audit; it does not apply to deterministic schema failures.
- **Return to objective review** is required to change the objective or Target
  classification.
- **Interaction capability required** explains when the approved performance cannot be
  demonstrated with the currently supported components.
- **Edit manually** uses the existing structured authoring artifact with the same
  immutable-field checks and scoped revalidation rules.

## Finding and Revision Contracts

Extend the finding model with workflow metadata rather than inferring behavior from
message text:

```text
finding_id
signature
owner
publication_impact
affected_part
affected_element_ids
editable_paths
rule_reference
recommended_action
confidence
introduced_by_operation
```

`signature` should be deterministic from the validator, rule, affected identity, and
normalized defect. It is used to detect repeated findings across revisions.

Add a durable revision request containing:

```text
revision_id
job_id
base_authoring_revision_id
selected_finding_ids
action
reviewer_instruction
allowed_parts
allowed_element_ids
allowed_paths
required_validators
max_model_calls
status
```

The service, not the model, derives the editable scope and required validators. The
model receives no authority to widen it.

## Revision Execution

### Deterministic planning

Before any model call:

1. Confirm that the selected findings still apply to the current authoring revision.
2. Resolve each finding to an owner and allowed action.
3. Reject mixed or unsupported repair scopes with a useful explanation.
4. Run a capability check for the approved Content-Type × Bloom target and available
   interaction types.
5. Calculate the maximum call count and estimated input/output token envelope.
6. Show the plan to the reviewer and require explicit confirmation.

Planning itself must not call a model.

### Scoped repair payload

A repair call receives only:

- the approved objective and Target classification;
- the selected findings;
- the affected elements and the minimum neighboring context needed for coherence;
- applicable source and LLM-domain claims;
- allowed element IDs and editable fields; and
- the reviewer's instruction.

The response is a patch, not another complete RLO. Apply it deterministically and reject
protected-field changes. Unselected parts, claims, evidence, classifications, and
provenance records remain byte-equivalent.

### Scoped revalidation

Always run deterministic schema, reference, and provenance invariants after applying a
patch. Model validators run only when their ownership is relevant:

- content meaning or source fidelity: grounding review;
- claim origin or attribution: provenance review;
- objective performance or assessment quality: pedagogy review;
- punctuation and other non-material style: no automatic model review.

Cross-part classification review is justified after a Practice/Check redesign, but not
after an isolated wording edit. Each action's required validators are shown before the
reviewer confirms it.

### Stopping rules

Stop without another model call when:

- the patch makes no material change;
- the same finding signature survives the allowed repair;
- the repair introduces an out-of-scope mutation;
- the available interaction set cannot demonstrate the Target performance;
- the selected call budget is exhausted; or
- the next action would require changing an immutable objective, claim, or source
  decision.

The stopped job remains reviewable and retains the last complete valid artifact. Show a
specific next decision rather than a generic retry button.

## Cost Controls and Telemetry

- Default to one repair call and one responsible validator call.
- Cap a normal reviewer-directed revision at three model calls.
- Require a separate, explicit advanced action for full re-analysis.
- Never retry a successful operation whose prompt, input, output contract, and scope are
  still compatible.
- Include the prompt hash, output-contract version, and revision scope in checkpoint
  compatibility. A changed prompt must not reuse an incompatible result, while an
  unchanged part must not be regenerated.
- Record estimated calls before confirmation and actual calls, tokens, latency, and
  provider-reported cost afterward.
- Permit only one active revision for an RLO.
- Separate infrastructure retries from semantic revision attempts. A transport failure
  may retry the same call; it must not start a new analysis cycle.

The review page should summarize cost as, for example:

```text
Planned: up to 2 model calls
Scope: Check / generated-07-check-001
Will reuse: source mapping, enrichment, Teach, Show, Practice, and prior provenance review
Will run: targeted assessment repair and pedagogy review
```

## Applying the Design to `rlo-REL-01`

| Current finding | Owner | Appropriate action |
|---|---|---|
| Target/Observed classification mismatch | Assessment capability | Do not repeatedly rewrite multiple-choice options. Report that the current interaction set cannot demonstrate independent recommendation construction. Offer return to objective review or a future structured assembly interaction. |
| Check finding underdetermines the gap | Assessment content | Allow a one-element Check repair followed by one pedagogy review. |
| Mixed-origin rule in Set-up | Provenance | Repair the Set-up claim references/origin and run provenance review only. |
| Source-synthesis basis mismatch | Claim ledger | Do not patch learner copy. Require a claim/provenance decision with the relevant source claims shown. |
| Em-dash warning | Advisory style | Allow manual edit or accept the note. Spend no model calls. |

This would prevent the system from spending two broad repair cycles on an interaction it
cannot currently produce while still allowing the local Check and Set-up defects to be
fixed independently.

## Implementation Phases

### Phase 1: Durable diagnostics

- [ ] Add stable finding identity, ownership, impact, editable scope, and operation
  provenance.
- [ ] Persist revision attempts, selected findings, patches, call usage, and stop reason.
- [ ] Backfill a read-only projection for existing findings without rewriting stored
  validator output.
- [ ] Show repair history and before/after diffs in RLO Review.

**Exit criterion:** A reviewer can explain what each `rlo-REL-01` repair attempted and
why it stopped without reading prompt JSON.

### Phase 2: Planning and controls

- [ ] Add a deterministic revision planner and capability check.
- [ ] Add selected-finding, action, instruction, and maximum-call controls to the API.
- [ ] Add the confirmation summary and cost envelope to RLO Review.
- [ ] Replace the generic retry action for semantic failures with scoped actions.

**Exit criterion:** No revision model call starts until a reviewer confirms its exact
scope and maximum call count.

### Phase 3: Scoped patches

- [ ] Define element- and field-level patch contracts.
- [ ] Enforce allowed IDs and paths during patch application.
- [ ] Preserve unselected content and immutable ledgers exactly.
- [ ] Add no-op, repeated-finding, and out-of-scope mutation stops.

**Exit criterion:** Repairing one Check cannot change Teach, claims, classification, or
another assessment.

### Phase 4: Scoped validation and checkpoint compatibility

- [ ] Route findings to grounding, provenance, pedagogy, deterministic, or capability
  ownership.
- [ ] Run only the validators required by the confirmed action.
- [ ] Include prompt hash, output contract, and revision scope in checkpoint identity.
- [ ] Record planned and actual call/token/cost telemetry.

**Exit criterion:** A local Check repair uses no more than two calls and does not rerun
source discovery, mapping, enrichment, or unrelated authoring.

### Phase 5: Commissioning evaluation

- [ ] Exercise wording, content, assessment, provenance, false-positive, and unsupported
  capability paths with generic fixtures.
- [ ] Revisit `rlo-REL-01` using separate scoped actions.
- [ ] Measure resolution rate, repeated-finding rate, new-finding rate, calls, tokens,
  cost, and reviewer decisions.
- [ ] Decide whether any second automatic repair produces enough measured benefit to
  retain it.

**Exit criterion:** Reviewers can improve a source-partial RLO predictably without an
unbounded loop, and the recorded cost never exceeds the confirmed ceiling.

## Verification

Container tests should cover:

- stable finding signatures and owner routing;
- stale revision and mixed-scope rejection before any model call;
- exact preservation of unselected elements and protected fields;
- one-element and Practice/Check patch application;
- scoped validator selection;
- prompt/contract/scope-aware checkpoint reuse;
- no-op and repeated-finding stops;
- budget exhaustion with a reviewable artifact;
- transport retry without semantic-loop expansion; and
- API/UI summaries of planned and actual model usage.

A commissioning run is successful when the reviewer can see the original problem,
choose a bounded action, predict the maximum calls, inspect the resulting diff, and
understand the stop reason without opening Advanced authoring JSON.
