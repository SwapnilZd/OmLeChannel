# Performance-Targeted Curriculum Gap Discovery Plan

**Date:** 2026-09-04

**Status:** Implemented; source-agnostic model evaluation pending

**Delivery slice:** Improve the precision of the existing bounded curriculum gap sweep
without adding a new LDS approval gate, objective quotas, or an open-ended generation
loop

## Goal

Change focused gap discovery from one search per broad curriculum domain to one search
per explicit missing learner performance. Every search should be grounded in the source
claims that support that performance, and every resulting objective should state which
gap it addresses.

The workflow must continue to return no objective when the source cannot support a
complete, independently learnable, and assessable performance.

## Problem being addressed

The current domain-focused sweep gives underrepresented domains independent attention,
but a domain can contain several related concepts, decisions, processes, and procedures.
A model can therefore propose another defensible objective from the correct domain
without addressing the specific performance that caused the domain to be marked
`partial` or `missing`.

The final coverage review can identify that the original gap remains, but the focused
operation has already spent its opportunity on adjacent material. Missing performances
need stable identities, explicit source evidence, and direct alignment with the
objective proposals they initiate.

## Design principles

- Keep the solution independent of any source, subject, profession, or document format.
- Treat source claims and resolved node citations as authoritative.
- Represent one atomic learner performance per gap target.
- Run one fixed sweep over the targets selected by the initial coverage review.
- Do not repeat the sweep in response to the final coverage review.
- Do not require every gap target to produce an objective.
- Do not impose objective-count, Kind, Bloom, or curriculum-domain quotas.
- Preserve useful source insufficiencies and unresolved gaps for LDS review.
- Keep every model prompt versioned, inspectable, and editable in the prompt directory.
- Use existing LiteLLM aliases; do not add direct provider configuration.
- Reuse the normal evidence-resolution and provisional-classification pipeline.
- Prefer regeneration of prototype workspaces over a compatibility layer for obsolete
  gap structures.

## Target workflow

```text
Initial grounded objective candidates
  -> initial set-level curriculum coverage review
  -> create atomic, source-linked missing-performance targets
  -> freeze the eligible target list
  -> search target 1 using only its supporting claims and objective memory
  -> assess proposal-to-target alignment
  -> add accepted candidates to compact memory
  -> search target 2 with updated memory
  -> continue once through the fixed target list
  -> resolve evidence and classify accepted proposals normally
  -> one final set-level curriculum coverage review
  -> existing LDS Objective Review
```

The final review reports remaining gaps but never initiates another search automatically.

## Proposed data model

### Curriculum gap target

Add a strict persisted `CurriculumGapTarget` containing:

- `target_id`: service-generated stable identifier;
- `domain_id`: owning curriculum domain;
- `performance`: one missing, observable learner performance;
- `rationale`: why the performance matters to the source's central instructional
  purpose;
- `claim_ids`: source claims that could support the complete performance;
- `evidence_sufficiency`: `sufficient` or `insufficient`;
- `sufficiency_rationale`: why the cited claims can or cannot ground an objective; and
- `search_warranted`: whether one focused objective search should be attempted.

The model returns target content but not authoritative IDs. The service assigns
`target_id` deterministically from the blueprint revision, domain ID, normalized
performance, and sorted claim IDs.

### Gap proposal alignment

Add a strict `GapTargetAlignment` result containing:

- `target_id`;
- `candidate_id`;
- `alignment`: `direct`, `supporting`, or `off_target`;
- `rationale`;
- `unsupported_performance_parts`; and
- `claim_ids_used`.

Interpretation:

- `direct`: the candidate's complete performance addresses the named target and may be
  counted as a gap candidate;
- `supporting`: the candidate is defensible and useful but does not resolve the target;
  it may remain available for LDS review without being reported as closing the gap; and
- `off_target`: the proposal does not materially address the target and is rejected
  from this focused operation with an auditable reason.

### Discovery audit record

Extend the existing domain discovery audit with target-level records containing:

- selection and eligibility rationale;
- prompt-run IDs;
- proposed candidate IDs;
- alignment results;
- accepted direct candidate IDs;
- retained supporting candidate IDs;
- rejected candidate IDs and reason codes; and
- explicit empty-result status.

## Phase 1: Gap-target contracts

- [x] Add `CurriculumGapTarget` and its enums to the source-authoring contracts.
- [x] Add strict target-level discovery and alignment audit contracts.
- [x] Replace free-text `missing_performances` as the authoritative representation with
  structured gap targets while preserving a simple display projection for the UI.
- [x] Assign target IDs in application code rather than trusting model-generated IDs.
- [x] Validate that every target references a known curriculum domain and only claims
  assigned to that domain.
- [x] Validate that `search_warranted` requires sufficient evidence and at least one
  supporting claim.
- [x] Validate that adequate domains cannot contain eligible gap targets.
- [x] Require accepted direct and retained supporting candidate IDs to have appeared in
  the corresponding target operation.

### Verification

- [x] Duplicate or unknown target IDs fail validation.
- [x] Unknown domain and claim references fail validation.
- [x] Insufficient targets cannot initiate objective generation.
- [x] Alignment and audit records cannot reference unknown proposals.
- [x] Current coverage artifacts agree with their accepted target-generated candidates.

## Phase 2: Initial coverage prompt

- [x] Revise `objective_set_coverage_review.md` to produce atomic gap targets for each
  `partial` or `missing` domain.
- [x] Define an atomic target as one independently learnable and assessable performance,
  not a topic label or a list of loosely related activities.
- [x] Require claim IDs and an evidence-sufficiency decision for every target.
- [x] Require the reviewer to distinguish missing performance from material that is
  already represented by existing objectives.
- [x] Retain source insufficiency when the desired performance exceeds the supplied
  claims.
- [x] Continue to prohibit Bloom, Kind, and objective-count quotas.
- [x] Increment the prompt version and update both prompt catalogs.

### Verification

- [x] Prompt tests assert atomicity, grounding, sufficiency, and no-quota language.
- [x] The output contract permits multiple targets in one domain without combining
  their performances.
- [x] The output contract permits an incomplete domain with no eligible search target
  when the source is insufficient.

## Phase 3: Fixed target sweep

- [x] Freeze the eligible target list from the initial coverage review before generation
  begins.
- [x] Preserve curriculum-domain order and target order within each domain.
- [x] Run each eligible target at most once.
- [x] Pass only the selected target, its cited claims, bounded relationships among those
  claims, the learning brief, compact curriculum context, and candidate memory.
- [x] Use existing adaptive claim batching only when one target's claim payload exceeds
  the configured request ceiling.
- [x] Include accepted candidates from earlier targets in compact memory to reduce
  repetition.
- [x] Publish progress using the curriculum domain and missing performance.
- [x] Treat an empty candidate list as a successful target result.

### Verification

- [x] Multiple targets from the same domain receive independent model operations.
- [x] A target request never includes claims outside its declared claim set.
- [x] Later requests include compact memory from earlier accepted candidates.
- [x] Empty and insufficient targets do not fail or restart the job.
- [x] The final coverage result cannot add work to the frozen target list.

## Phase 4: Target-aligned proposal generation

- [x] Revise `coverage_gap_discovery.md` to address one named gap target rather than one
  broad domain.
- [x] Require each proposal to return the supplied `target_id`.
- [x] Require the proposal rationale to explain how the complete learner performance
  addresses that target.
- [x] Prohibit proposals that merely discuss adjacent material from the same domain.
- [x] Preserve the option to return no proposal when a complete objective cannot be
  grounded.
- [x] Reject candidate evidence outside the target's supplied claim set.
- [x] Increment the prompt version and update both prompt catalogs.

### Verification

- [x] A proposal with the wrong target ID is rejected deterministically.
- [x] A proposal with an out-of-scope claim is rejected and audited.
- [x] Exact normalized duplicates are removed deterministically.
- [x] Prompt tests continue to require one atomic objective and permit empty results.

## Phase 5: Alignment and ordinary candidate processing

- [x] Add a concise, versioned target-alignment prompt and strict response contract.
- [x] Evaluate the proposed objective's full performance, not verb overlap or exact
  wording similarity.
- [x] Supply the target, proposal, and cited source claims to the alignment review.
- [x] Treat defensible paraphrases and instructional transformations as valid when they
  preserve the supported performance boundary.
- [x] Send direct and retained supporting proposals through normal evidence resolution
  and provisional Kind/Bloom classification.
- [x] Count only direct candidates as resolving the initiating gap target.
- [x] Audit off-target and unsupported proposals without exposing them as valid gap
  candidates.
- [x] Use an existing review-oriented LiteLLM alias.

### Verification

- [x] Direct alignment accepts supported paraphrases rather than requiring source-text
  identity.
- [x] Supporting alignment does not falsely mark a gap as resolved.
- [x] Off-target proposals do not enter the accepted gap-candidate set.
- [x] No candidate enters Objective Review without objective-defining evidence.
- [x] Kind and Bloom remain provisional hints derived from expected learner practice.

## Phase 6: Final coverage review and termination

- [x] Run exactly one final set-level coverage review after all eligible targets finish.
- [x] Include target IDs and alignment outcomes in the final review input.
- [x] Ask the final reviewer whether each target is resolved, remains partial, or is
  source-insufficient.
- [x] Preserve unresolved targets and their rationales for LDS review.
- [x] Prevent final coverage output from initiating another discovery operation.

### Verification

- [x] Every workflow performs one initial and one final coverage review.
- [x] An accepted adjacent objective cannot alone change its target to resolved.
- [x] Remaining gaps are visible without triggering an automatic loop.
- [x] Repeated job execution creates a new deterministic workspace result rather than
  appending candidates to the prior result.

## Phase 7: Objective Review UI, progress, and export

- [x] Show the initiating missing performance on each target-generated objective.
- [x] Distinguish direct, supporting, off-target, and empty target outcomes.
- [x] Show source claims, eligibility rationale, alignment rationale, and prompt-run
  links without adding a new approval screen.
- [x] Show target progress while the worker is running.
- [x] Relabel initial eligibility fields so they are not confused with final coverage
  state.
- [x] Add target ID, missing performance, alignment, and final target status to the Excel
  export.
- [x] Preserve existing keyboard-accessible objective review actions and semantic
  structure.

### Verification

- [x] Reviewers can tell why a focused objective was generated.
- [x] Reviewers can distinguish an objective that resolves a target from useful adjacent
  material.
- [x] Adequate final coverage does not appear to contradict initial gap eligibility.
- [x] Exact prompt and structured-input snapshots remain accessible in Prompts Used.
- [x] The updated pages are smoke-tested in the containerized application.

## Phase 8: Source-agnostic evaluation

- [ ] Re-run the same held-out sources used to evaluate the domain-focused sweep.
- [ ] Add at least two sources with materially different hierarchy, length, subject
  matter, and instructional purpose.
- [ ] Compare target count, generated objective count, direct-alignment rate, supporting
  rate, off-target rate, empty-result rate, and final unresolved target count.
- [ ] Review whether target-level searches improve missing-performance coverage without
  increasing unsupported objectives.
- [ ] Review Bloom and Kind distributions for unexplained concentration without imposing
  a target distribution.
- [ ] Capture LDS usefulness feedback for both the proposed objectives and the stated
  remaining gaps.

Model quality remains an evaluation result, not a deterministic unit-test assertion.

## Observable acceptance criteria

- Every eligible missing performance is represented by a stable, source-linked target.
- Every target is searched at most once in deterministic order.
- Every focused request contains only claims declared for that target.
- Every focused proposal names its initiating target and receives an alignment result.
- Only directly aligned candidates count as resolving a target.
- Supporting or off-target material cannot make coverage appear complete.
- Empty results and source insufficiencies remain valid outcomes.
- One final coverage review terminates the workflow without recursion.
- Prompts, inputs, outputs, alignment decisions, and rejection reasons remain auditable.
- No implementation logic or prompt language depends on a particular source document.

## Deferred considerations

- Human-authored edits to the curriculum blueprint or gap targets before generation.
- Automatic retrieval of additional sources for source-insufficient targets.
- Learner-profile selection and sequencing of approved RLOs.
- Production migration of prototype workspaces created under superseded contracts.
- Model fine-tuning; prompt, contract, and evaluation improvements should be exhausted
  first.
