# Learning Objective Curriculum Coverage Plan

**Date:** 2026-09-04

**Status:** Core implementation complete; model calibration pending

**Delivery slice:** Document-level planning and set-level coverage analysis for
learning-objective discovery

## Goal

Extend the current high-recall, source-grounded objective-discovery workflow so the
resulting objective set represents the source's central purpose and major
instructional domains, not merely a collection of individually defensible facts.

The workflow must continue to produce atomic, independently reviewable objective
candidates with exact source lineage. The new capability adds a compact curriculum
view before discovery and a set-level coverage review afterward. It does not turn
the source into a course automatically or introduce another human approval gate.

## Problem statement

The current workflow is effective at asking whether a source claim can support an
atomic objective. It does not yet answer whether the complete objective set would
adequately teach the source.

Observed limitations include:

- objective discovery proceeds bottom-up from claims without an explicit account of
  the source's central purpose and major domains;
- uncovered claims are useful for high-recall discovery but do not distinguish core
  recommendations from supporting or peripheral facts;
- bounded claim batches retain candidate memory but lack a stable curriculum frame
  shared across every batch;
- collection-map synthesis can reduce the visibility of source hierarchy and the
  significance of large structured sections;
- each candidate is checked independently, but no final operation evaluates
  completeness, balance, fragmentation, or curricular coherence across the set; and
- atomic objectives are not currently connected by a small number of integrative
  performances that help learners use the source as a whole.

For example, the NIST SP 800-61r3 extraction found useful incident-response facts and
activities, but it did not clearly demonstrate balanced coverage of the publication's
CSF 2.0 Community Profile or its central risk-management purpose.

## Design principles

- Keep source content and exact citations authoritative.
- Preserve high-recall candidate discovery; do not silently remove peripheral,
  overlapping, or low-confidence candidates.
- Treat document importance as an explicit, inspectable model judgment rather than a
  deterministic claim about the source.
- Use source hierarchy, headings, relationships, stated priorities, and repetition as
  evidence of importance. Do not use page count alone.
- Separate source coverage from instructional sufficiency. A source may identify an
  important performance without containing enough material to teach it fully.
- Do not force one objective per section, claim, domain, or Bloom level.
- Require exact source lineage for every newly proposed objective, including
  integrative objectives.
- Keep provisional Kind and Bloom classification separate from curriculum coverage.
- Make all new prompts versioned Markdown assets that are visible in the prompt
  catalog and job audit history.
- Add no new mandatory LDS approval step. Coverage findings support the existing
  Objective Review decision.

## Target workflow

```text
Extracted hierarchy and grounded source maps
  -> practitioner learning brief
  -> document curriculum blueprint
  -> high-recall atomic objective discovery in bounded batches
  -> evidence resolution and provisional classification
  -> set-level curriculum coverage review
  -> one bounded, source-grounded gap-discovery pass
  -> final coverage report
  -> existing LDS Objective Review
```

The curriculum blueprint is shared with every discovery batch. The coverage review
does not approve, reject, or rewrite objectives. It identifies what the candidate set
covers, where it is thin, and which candidates may be peripheral or unnecessarily
fragmented. A bounded gap pass may add candidates, but only when cited evidence
supports them.

## Proposed data structures

### Document curriculum blueprint

A versioned artifact derived from the learning brief, ordered source hierarchy, and
grounded map claims:

- concise central purpose of the source;
- intended use and important source-stated boundaries;
- major instructional domains in source order;
- each domain's rationale and provisional importance (`core`, `supporting`, or
  `peripheral`);
- supporting claim IDs, source sections, and document IDs;
- source-stated priorities when present;
- broad integrative performances suggested by the source;
- topics that are reference material rather than likely standalone learning; and
- uncertainties that require LDS judgment.

Importance is advisory and auditable. It must not automatically suppress objective
candidates.

### Candidate coverage assignment

For each objective candidate:

- covered curriculum-domain IDs;
- coverage role (`primary`, `supporting`, or `peripheral`);
- contribution to the source's central purpose;
- whether it is atomic detail or an integrative performance;
- related candidates that may collectively cover one domain; and
- concise rationale with claim references.

### Curriculum coverage report

A versioned set-level artifact containing:

- coverage state for each domain (`adequate`, `partial`, `missing`, or
  `source_insufficient`);
- uncovered or weakly represented core claims;
- overrepresented or highly fragmented areas;
- potentially peripheral candidates;
- missing integrative performances;
- source-insufficiency findings;
- newly proposed gap candidates and their lineage; and
- unresolved questions for the LDS reviewer.

The report evaluates the objective set; it does not claim that approved RLOs or a
complete learning pathway already exist.

## Phase 1: Contracts and inspectable prompts

- [x] Add strict contracts for the curriculum blueprint, candidate coverage
  assignments, domain findings, and final coverage report.
- [x] Define stable IDs and explicit schema versions for all new artifacts.
- [x] Create `document_curriculum_blueprint.md` as a versioned prompt asset.
- [x] Create `objective_set_coverage_review.md` as a versioned prompt asset.
- [x] Create `coverage_gap_discovery.md` as a versioned prompt asset.
- [x] Add all prompts to the objective-extraction README and repository prompt
  catalog.
- [x] Persist the exact prompt, version, hash, input snapshot, output schema, model
  alias, and token usage for every new model operation.

### Verification

- [x] Contract tests reject unknown domain IDs, invalid coverage states, and gap
  objectives without claim references.
- [x] Prompt tests confirm that workflow context, grounding rules, and role boundaries
  are present in every new asset.

## Phase 2: Build the document curriculum blueprint

- [x] Generate one curriculum blueprint after the learning brief and before objective
  proposal.
- [x] Supply the ordered document outline, section-map identities, collection claims,
  relationships, source priorities, and learning brief.
- [x] Preserve source order and source-to-domain lineage.
- [x] Distinguish central themes from reference, administrative, and publication
  metadata.
- [x] Record when the source points to external implementation material or lacks
  sufficient instructional detail.
- [x] Use the existing bounded hierarchical map artifacts for large sources rather
  than submitting the complete raw document in one request.
- [x] Persist the blueprint with the immutable collection-map revision.

### Verification

- [ ] A NIST SP 800-61r3 run identifies the CSF-wide risk-management purpose, the
  incident-response lifecycle, organizational roles and preparation, the Community
  Profile, and continuous improvement as explicit domains.
- [ ] Publication supersession is distinguishable from a core instructional domain.
- [x] Every blueprint domain resolves to known source claims and sections.

## Phase 3: Guide bounded discovery with the blueprint

- [x] Include the same compact blueprint in every objective-discovery batch.
- [x] Extend discovery memory with covered domain IDs, not full prior rationales.
- [x] Ask each pass to seek materially new performances in underrepresented core
  domains while retaining ordinary high-recall claim discovery.
- [x] Prevent importance labels from becoming candidate quotas or automatic filters.
- [x] Let one objective support multiple domains when its performance genuinely
  integrates them.
- [x] Keep Kind and Bloom classification out of this operation.

### Verification

- [x] Every batch receives the same blueprint revision and domain vocabulary.
- [x] Candidate count remains an outcome of supported discovery rather than a target.
- [x] Existing evidence-resolution rules continue to reject unresolvable lineage.

## Phase 4: Add set-level curriculum coverage review

- [x] Run coverage review after initial candidates have resolvable evidence and
  provisional classifications.
- [x] Map candidates to curriculum domains and evaluate the set collectively.
- [x] Evaluate central-purpose alignment, core-domain coverage, excessive attention to
  peripheral material, fragmentation, meaningful overlap, and missing integrative
  performance.
- [x] Distinguish `missing objective` from `source lacks enough information`.
- [x] Treat Remember, Understand, and Apply distributions as descriptive evidence,
  not quotas.
- [x] Preserve all initial candidates and record findings separately.
- [x] For very large candidate sets, review bounded groups by domain and synthesize a
  compact final report.

### Verification

- [x] Coverage findings reference valid candidate, domain, and claim IDs.
- [x] The review can flag a source-grounded but peripheral objective without rejecting
  it.
- [x] The review can identify a core domain represented only by isolated facts rather
  than an adequate usable performance.

## Phase 5: Run one bounded gap-discovery pass

- [x] Submit only `partial` and `missing` core domains, relevant claims, the blueprint,
  and compact existing-candidate memory to the gap prompt.
- [x] Permit new atomic or integrative candidates only when objective-defining evidence
  is available.
- [x] Do not manufacture an objective to make a report appear complete.
- [x] Mark an unresolved domain as source-insufficient when the source states an
  outcome but delegates implementation detail elsewhere.
- [x] Resolve evidence and classify any new candidates through the same existing
  pipeline as initial candidates.
- [x] Re-run the coverage review once after gap discovery; do not create an unbounded
  review-and-repair loop.

### Verification

- [x] Unsupported gap candidates fail through the normal evidence-resolution path.
- [x] Initial and gap-generated candidates remain distinguishable in audit history.
- [x] Repeated execution against the same source-map and prompt revisions does not
  continually append equivalent candidates.

## Phase 6: Integrate findings into Objective Review

- [x] Add a compact coverage summary showing core domains that are adequate, partial,
  missing, or source-insufficient.
- [x] Show a candidate's domain contribution without adding noisy rule tags to the
  primary review card.
- [x] Let reviewers filter candidates by curriculum domain and coverage role.
- [x] Clearly label peripheral and integrative findings as model recommendations.
- [x] Allow LDS reviewers to change domain importance or acknowledge a coverage gap.
- [x] Keep individual approve, reject, edit, split, merge, and add-related-objective
  actions unchanged.
- [x] Include curriculum domain, coverage role, and coverage findings in the Excel
  export.
- [x] Expose the exact blueprint and coverage prompt runs in the existing prompt audit
  interface.

### Verification

- [ ] The interface remains usable when a job contains many objectives and domains.
- [x] Coverage guidance does not block objective approval or add another review gate.
- [x] Keyboard navigation and semantic status labels meet the repository accessibility
  baseline.
- [ ] UI behavior is smoke-tested in the running containerized application.

## Phase 7: Evaluation and calibration

- [ ] Use the current NIST workbook as a baseline case for coverage behavior, not as
  NIST-specific hard-coded logic.
- [ ] Add a held-out source from a materially different domain and structure.
- [ ] Define reviewer-scored evaluation dimensions: major-domain recall, peripheral
  emphasis, integrative coverage, unsupported additions, and usefulness of gap
  findings.
- [x] Add deterministic tests for schemas, IDs, persistence, lineage, bounded retry,
  and UI/export fields.
- [ ] Provide an opt-in model-backed evaluation command for prompt comparison; do not
  make variable model judgments a blocking unit test.
- [ ] Record prompt and model versions with evaluation results.

## Observable acceptance criteria

- Every objective job has an inspectable curriculum blueprint tied to its source-map
  revision.
- Every discovery batch receives the same compact document-level curriculum context.
- Every candidate can be traced to source evidence and optionally mapped to one or
  more curriculum domains.
- The system produces a set-level report that distinguishes adequate, partial,
  missing, and source-insufficient coverage.
- Peripheral source facts remain reviewable but are not mistaken for central
  curriculum coverage.
- One bounded gap pass can add source-supported candidates without creating an
  open-ended model loop.
- No objective is automatically approved or rejected because of a coverage finding.
- All new prompts and exact prompt runs are easy for an administrator or developer to
  inspect and edit.
- The NIST example surfaces both its CSF-wide organizing purpose and gaps in applying
  the Community Profile, rather than reporting only a list of incident-response facts.

## Explicitly deferred

- Automatically assembling approved RLOs into a learner-specific pathway.
- Determining which objectives every learner should receive.
- Adding external implementation sources without an LDS decision.
- Automatically deleting objectives judged peripheral or duplicative.
- Treating a balanced Bloom distribution as proof of curriculum quality.
- Measuring extraction or chart-decoding quality through a second, more expensive
  model pipeline.
