# Domain-Focused Curriculum Gap Discovery Plan

**Date:** 2026-09-04

**Status:** Implemented; held-out model evaluation pending

**Delivery slice:** Improve the bounded curriculum gap-discovery operation without
adding another LDS approval gate or an open-ended model loop

## Goal

Change curriculum gap discovery from one broad request covering all gaps into one
bounded sweep that examines each eligible curriculum domain independently. This should
give underrepresented domains enough attention while preserving source grounding,
high-recall objective discovery, and the existing Objective Review workflow.

## Current behavior and observed limitation

The current workflow sends all `partial` and `missing` core domains into one gap request.
A single request can distribute attention unevenly: domains with abundant or easily
expressed evidence may receive several candidates while other defensible gaps receive no
focused consideration.

The core-only selection rule can also exclude a supporting domain that provides an
important mechanism, context, or bridge required to fulfill the source's central
purpose. The system needs a source-agnostic way to identify that relationship without
treating every supporting topic as mandatory curriculum.

## Design principles

- Run one fixed sweep over eligible domains, not repeated generation until every domain
  appears adequate.
- Give each eligible domain a focused model operation with only its relevant source
  claims and compact objective memory.
- Continue to permit the model to return no objective when the source is insufficient.
- Do not impose objective-count, domain-count, Kind, or Bloom quotas.
- Keep source claims and resolved node citations authoritative.
- Treat domain importance and gap eligibility as inspectable model recommendations.
- Preserve all defensible candidates for LDS review rather than silently deleting
  semantic overlaps.
- Use the existing LiteLLM model alias and prompt-audit mechanism.
- Run evidence resolution and provisional classification through the same paths used by
  ordinary objective candidates.

## Target workflow

```text
Initial grounded objective candidates
  -> initial set-level curriculum coverage review
  -> select eligible curriculum gaps once
  -> examine domain 1 with relevant claims and existing candidate memory
  -> add accepted domain 1 candidates to compact memory
  -> examine domain 2 with relevant claims and updated memory
  -> continue once through the fixed eligible-domain list
  -> resolve evidence and classify all new candidates
  -> deterministic exact-duplicate removal
  -> one final set-level curriculum coverage review
  -> existing LDS Objective Review
```

The eligible-domain list is fixed from the initial coverage report. The final review
does not initiate another gap sweep.

## Gap eligibility

Extend each domain coverage finding with:

- `gap_discovery_warranted`: whether a focused objective search would materially help
  represent the source's central purpose;
- `gap_discovery_rationale`: why another search is or is not warranted; and
- the existing coverage state and missing-performance descriptions.

Selection rules:

1. Include a `core` domain when it is `partial` or `missing` and gap discovery is
   warranted.
2. Include a `supporting` domain when it is `partial` or `missing`, gap discovery is
   warranted, and the coverage reviewer explains how it enables the central purpose.
3. Exclude `adequate`, `source_insufficient`, and automatically peripheral domains.
4. Preserve the blueprint's source order, with core domains evaluated before supporting
   domains when ordinals otherwise conflict.
5. Do not interpret eligibility as a requirement to produce an objective.

This allows an important supporting mechanism to enter gap discovery when it is
necessary to use the source as intended, without treating every supporting topic as
mandatory curriculum.

## Per-domain request

Each focused request receives only:

- the shared curriculum blueprint identity, central purpose, and intended use;
- the selected domain and its coverage finding;
- the domain's missing performances;
- claims associated with that domain;
- relationships among those claims;
- the learning brief;
- compact memory for all existing and previously accepted gap candidates; and
- explicit instructions permitting an empty result.

The request must not receive unrelated source claims merely to fill context. If one
domain's claims exceed the configured request ceiling, use the existing adaptive claim
batching behavior within that domain and combine its proposals before moving to the next
domain.

## Audit record

Persist a small record for each partial or missing domain containing:

- domain ID and initial coverage state;
- eligibility rationale;
- prompt-run IDs;
- proposed candidate IDs;
- accepted and rejected candidate IDs;
- rejection reasons from normal evidence resolution; and
- whether no defensible candidate was found.

Continue to expose exact prompt text, version, hash, model alias, structured input, and
operation name through the existing prompt audit interface.

## Phase 1: Contracts and prompt revisions

- [x] Add gap eligibility and rationale fields to domain coverage findings.
- [x] Add a strict per-domain gap-discovery audit record.
- [x] Add the audit records to the persisted curriculum coverage artifact.
- [x] Revise `objective_set_coverage_review.md` so supporting domains can be marked
  eligible only when they materially enable the source's central purpose.
- [x] Revise `coverage_gap_discovery.md` for one named domain per operation.
- [x] Require an explicit empty result when no complete, source-supported performance
  can be proposed.
- [x] Increment prompt versions and update both prompt catalogs.

### Verification

- [x] Invalid domain IDs and unknown candidate IDs fail contract validation.
- [x] `source_insufficient` findings cannot be selected for gap discovery.
- [x] Prompt tests preserve grounding, atomicity, and no-quota rules.

## Phase 2: Select the fixed domain sweep

- [x] Replace the current core-only selection with the explicit eligibility rules.
- [x] Freeze the eligible-domain list before the first focused operation.
- [x] Preserve deterministic domain ordering.
- [x] Record why every partial or missing domain was selected or skipped.
- [x] Ensure a final coverage result cannot trigger another sweep.

### Verification

- [x] Partial and missing core domains are selected when warranted.
- [x] A supporting domain can be selected only with a central-purpose rationale.
- [x] Adequate, peripheral, and source-insufficient domains are skipped.
- [x] Each selected domain is visited at most once.

## Phase 3: Execute focused domain discovery

- [x] Submit one domain, its relevant claims, and its missing performances per focused
  operation.
- [x] Include compact memory of initial candidates and gap candidates accepted from
  earlier domains.
- [x] Allow integrative candidates when all parts of the performance are supported and
  the named domain remains the primary reason for discovery.
- [x] Use adaptive claim batching only when one domain exceeds the configured request
  ceiling.
- [x] Reject claim references outside the selected domain's supplied claim set.
- [x] Publish operation progress using the domain title so admins can see what the
  worker is examining.

### Verification

- [x] Each request contains only known claims for its selected domain.
- [x] Later domain requests contain compact memory of earlier accepted gap candidates.
- [x] An empty model result advances to the next domain without failure.
- [x] Oversized domains split into bounded claim batches without creating another
  domain sweep.

## Phase 4: Resolve, reconcile, and review once

- [x] Resolve evidence and provisionally classify focused proposals through the existing
  candidate pipeline.
- [x] Remove exact normalized duplicates deterministically.
- [x] Retain defensible semantic overlaps for LDS review and final fragmentation
  analysis.
- [x] Persist domain-of-origin audit records for every gap-generated candidate.
- [x] Run exactly one final set-level coverage review after the sweep.
- [x] Preserve unresolved gaps and source-insufficiency findings honestly.

### Verification

- [x] Unsupported proposals are rejected with the normal evidence-resolution reasons.
- [x] No candidate can enter Objective Review without objective-defining evidence.
- [x] The complete workflow performs one initial and one final coverage review.
- [x] Repeated execution does not append exact duplicate candidates.

## Phase 5: Review UI and export

- [x] Show which curriculum domain initiated each gap-generated objective.
- [x] Show per-domain discovery status: candidates added, no candidate found, or source
  insufficient.
- [x] Display the eligibility rationale with the existing coverage finding.
- [x] Keep all coverage findings advisory and preserve existing objective review actions.
- [x] Add domain-of-origin and gap-discovery status to the Excel export.
- [x] Keep exact focused prompts available in the existing Prompts Used tab.

### Verification

- [x] Reviewers can distinguish initial candidates from focused gap candidates.
- [x] The UI does not imply that every missing domain must receive an objective.
- [x] Keyboard and screen-reader users can access the new status information.
- [x] The updated page is smoke-tested in the containerized application.

## Phase 6: Evaluation

- [ ] Run the same source before and after the change and compare domain attention,
  defensible gap candidates, and unresolved coverage states.
- [ ] Confirm that every partial or missing domain receives an independent eligibility
  decision regardless of its subject matter or position in the source.
- [ ] Review whether focused discovery adds defensible candidates for remaining
  source-supported gaps without favoring domains that contain more claims.
- [ ] Confirm that unsupported gaps remain visible rather than being filled with invented
  objectives.
- [ ] Run at least two held-out sources with materially different subject matter,
  hierarchy, length, and instructional purpose.
- [ ] Record objective count, gap-generated count, remaining coverage states,
  unsupported proposal count, and LDS usefulness feedback.

Model quality remains an evaluation result, not a deterministic unit-test assertion.

## Observable acceptance criteria

- Every initially eligible curriculum domain is examined exactly once.
- Supporting domains enter the sweep only when they materially enable the source's
  central purpose.
- Every focused request contains only the selected domain's grounded claims.
- Newly accepted candidates become compact memory for later domain requests.
- The workflow terminates after one final coverage review.
- Missing and source-insufficient areas remain visible when no defensible objective can
  be generated.
- Objective approval remains solely an LDS decision in the existing review stage.
- Evaluation across unrelated sources shows that evidence-rich domains do not prevent
  other eligible domains from receiving focused consideration.

## Explicitly deferred

- Repeating gap discovery until all domains are adequate.
- Automatically changing model-recommended domain importance.
- Requiring one objective per curriculum domain.
- Enforcing a balanced Bloom or content-kind distribution.
- Automatically rejecting semantic overlaps without LDS review.
- Building RLO content for newly approved objectives as part of this change.
