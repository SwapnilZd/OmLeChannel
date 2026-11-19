# Learning Objective Classification Improvement Plan

**Date:** 2026-09-04  
**Status:** In progress
**Feedback artifact:** `docs/learning-objectives-d7568ffa-791e-465b-b3b1-dac0fc57bc1d.xlsx`

## Purpose

Improve learning-objective decomposition and preliminary content-kind/Bloom
classification so that proposals are evaluated against the learning team's rules
before they reach the existing Objective Review gate.

This work does not add another human approval stage. Classification at objective
listing time remains advisory. Ambiguous classifications should be surfaced with a
provisional best cell and useful reviewer guidance rather than silently committed or
discarded.

## Feedback summary

The learning team reviewed 30 proposed objectives:

- 7 passed;
- 23 failed (76.7%); and
- 21 of the 23 failed objectives had been assigned High confidence.

The failures overlap across several recurring patterns:

- objectives describing the publication or topic instead of learner performance;
- compound or oversized objectives containing independently assessable capabilities;
- confusion among Concept, Process, Procedure, and Principle;
- Bloom inflation, especially Apply to Analyze or Evaluate;
- commitment to one cell where the rules require escalation;
- weak confidence calibration; and
- one malformed or incompletely joined objective statement.

The feedback also shows that conjunctions and multiple inputs are not automatically
compound. Sequential steps within one procedure, evidence used to reconstruct one
incident, and competing considerations weighed in one judgment may remain one
coherent objective.

### Rule-number discrepancy

Several feedback entries refer to D-15 as the one-objective/one-cell rule. In the
original decomposition document and the consolidated reference, that requirement is
D-16. D-15 governs supplementary-source handling. Implementation and audit output
should use the canonical rule IDs from the source documents.

## Current-state findings

### Preliminary listing classification

`api/src/source_authoring/prompts/objective_extraction/candidate_formation.md`
currently forms objectives and assigns preliminary Kind/Bloom hints in the same model
operation. It names the five content kinds but does not provide the detailed C-1
through C-21 classification rubric.

Its later-pass diversity instruction includes Kind and Bloom distribution. Although
the prompt warns against forcing every topic into every cell, this instruction may
still encourage unsupported variation and higher-level classifications.

The current output contract also provides one confidence value for the entire
candidate. It cannot represent separate Kind confidence, Bloom confidence, a
deterministic combined confidence, alternatives, or a discriminator question.

### RLO classification

`api/src/source_authoring/prompts/rlo_generation/target_classification.md` selects the
Target cell after objective approval. It receives valid methodology profiles but not
the complete classification rules.

`api/src/source_authoring/prompts/rlo_generation/pedagogy_validation.md` assigns the
Observed classification from the generated Teach, Show, Practice, and Check. Its
classification guidance is also abbreviated.

The full learning-team rule accounting exists in
`docs/rlo-generation-rules-reference.md`, but those detailed rules are reference
documentation rather than runtime prompt input.

## Target workflow

```text
Source-grounded discovery
  -> decomposition critique and revision/split recommendations
  -> dedicated Kind classification
  -> dedicated Bloom classification
  -> independent rules critique and one bounded correction
  -> Objective Review with provisional classification guidance
  -> approved objective
  -> Target classification during RLO planning
  -> RLO generation
  -> Observed classification from the completed learning experience
```

The three classification values retain distinct meanings:

- **Suggested:** preliminary objective-stage recommendation for the reviewer.
- **Target:** intended cell selected during RLO planning from the approved objective
  and expected learner performance.
- **Observed:** cell inferred from the completed Teach, Show, Practice, and Check.

## Phase 1 — Versioned executable rubrics

- [x] Create an editable, versioned decomposition rubric prompt asset containing the
  applicable D rules, boundary tests, and canonical examples.
- [x] Create an editable, versioned classification rubric prompt asset containing
  C-1 through C-21, content-kind definitions, Bloom definitions, boundary tests, and
  canonical examples.
- [x] Load the shared classification rubric for Suggested, Target, and Observed
  classification rather than maintaining divergent condensed definitions.
- [x] Persist the complete composed prompt, rubric version, hash, input, and output
  for every classification operation.
- [x] Normalize runtime rule IDs to the canonical source-document numbering.
- [x] Update the prompt indexes whenever an asset or version changes.

## Phase 2 — Separate decomposition from classification

- [x] Remove responsibility for committing Kind and Bloom from candidate formation.
- [x] Make candidate formation return the objective statement, observable behavior,
  performance context, scope, practitioner relevance, evidence, and provenance.
- [x] Remove Kind/Bloom distribution from discovery diversity goals; prioritize
  distinct source-supported practitioner tasks, decisions, risks, and transfer
  situations instead.
- [ ] Add a decomposition-critic output that can recommend `retain`, `revise`,
  `split`, or `escalate` without deleting the original proposal.
- [ ] Check learner performance versus topic description.
- [ ] Check whether actions are independently learnable or assessable rather than
  treating every conjunction as compound.
- [ ] Check the 5–15 minute granularity heuristic and excessive dimension lists.
- [ ] Preserve the original proposal and critic decision in the audit history.

## Phase 3 — Dedicated classification stage

- [x] Classify content Kind first and Bloom level second.
- [x] Record separate Kind confidence and rationale.
- [x] Record separate Bloom confidence and rationale.
- [x] Require the Bloom rationale to describe the expected Practice/Check learner
  performance, not merely interpret the objective's verb.
- [x] Calculate combined confidence deterministically as the lower of Kind and Bloom
  confidence.
- [x] Always retain a provisional best cell when escalation is required.
- [x] Return plausible alternatives, rejected alternatives, applicable rule IDs, and
  a discriminator question.
- [x] Record verb-versus-practice mismatches explicitly.

### Deterministic classification constraints

- [x] Permit only the 13 supported Kind × Bloom cells.
- [x] Permit Evaluate only for Principle content.
- [ ] Require Process to involve stages, actors, transitions, handoffs, or
  dependencies.
- [ ] Require Procedure to involve learner-executed steps, decisions, entry/exit
  conditions, or outputs.
- [ ] Treat category membership based on attributes, instances, or non-instances as
  Concept.
- [ ] Do not infer Analyze or Evaluate merely from verbs such as `analyze`, `assess`,
  `validate`, or `evaluate`.
- [x] Require escalation when no single cell reaches Medium confidence.
- [x] Prevent High combined confidence when the result retains unresolved competing
  cells.

## Phase 4 — Independent rules critique

- [ ] Add a named, versioned classification-critic prompt.
- [ ] Evaluate each proposed objective and classification against applicable D and C
  rules before it reaches Objective Review.
- [ ] Challenge High-confidence results explicitly.
- [ ] Permit one bounded correction pass when the critic identifies a repairable
  decomposition or classification problem.
- [ ] Preserve both the original and corrected result in the prompt/audit history.
- [ ] Surface unresolved disagreement as `classification_escalated`; do not reject or
  hide an otherwise useful objective.
- [ ] Keep objective validity separate from classification certainty.

## Phase 5 — Objective Review and export

- [x] Continue to label objective-stage Kind and Bloom as Suggested.
- [x] Show separate Kind, Bloom, and combined confidence.
- [x] Show alternatives and the discriminator question when escalation is required.
- [ ] Distinguish these review states:
  - objective needs revision;
  - classification needs reviewer judgment; and
  - objective and classification are ready.
- [x] Keep rule IDs and detailed reasoning in expandable audit information rather
  than prominent tags.
- [ ] Allow the reviewer to adjust Suggested Kind/Bloom without adding a separate
  approval gate.
- [x] Include classification state, separate confidences, alternatives,
  discriminator question, and concise rationale in the Excel export.
- [x] Keep prompts and exact prompt runs inspectable from the admin UI.

## Phase 6 — Align Target and Observed classification

- [x] Use the same versioned classification rubric for Target classification during
  RLO planning.
- [x] Use the same rubric for Observed classification after Teach, Show, Practice,
  and Check exist.
- [ ] Allow Target to differ from Suggested with an explicit rationale.
- [ ] Do not treat Suggested-versus-Target disagreement as an RLO failure.
- [ ] Continue to flag Target-versus-Observed mismatch for instructional review.
- [ ] Ensure a Target recommendation guides authoring without forcing generated
  content to imitate an incorrect preliminary hint.

## Phase 7 — Calibration and evaluation

Use the reviewed workbook as a versioned calibration set, not as NIST-specific
hard-coded application behavior.

- [ ] Convert each row into structured evaluation expectations: reviewer outcome,
  decomposition issue, expected or plausible Kind, expected or plausible Bloom,
  escalation expectation, and reviewer rationale.
- [ ] Verify that the seven passing objectives remain acceptable.
- [ ] Require rows with explicit Kind/Bloom corrections to match or escalate.
- [ ] Require ambiguous examples to escalate with the relevant alternatives.
- [ ] Require compound examples to split or receive an atomicity finding.
- [ ] Track incorrect High-confidence classifications as a primary calibration
  failure.
- [x] Add deterministic contract and rule-inclusion tests to normal CI.
- [ ] Provide an opt-in model-backed evaluation command for prompt calibration; do
  not make variable commercial-model results a blocking unit test.
- [ ] Evaluate at least one held-out source from another domain before treating the
  approach as calibrated.

## Observable acceptance criteria

- Every classification call receives the complete current classification rubric.
- Every candidate has separate Kind and Bloom decisions with auditable reasoning.
- Combined confidence equals the lower component confidence.
- Every reviewer-identified ambiguous calibration row escalates rather than silently
  committing at High confidence.
- Every explicit correction in the calibration set either matches the expected cell
  or returns that cell as a plausible escalated alternative.
- Atomicity findings distinguish independent objectives from inseparable steps,
  inputs, or trade-offs within one coherent performance.
- Suggested classification remains advisory and does not create a new human review
  gate.
- Target and Observed classifications use the same rule version and remain visible in
  RLO Review.
- Exact prompt assets and prompt runs remain easy for an administrator or developer
  to inspect.

## Key product decision retained

Classification uncertainty should not cause a useful objective to disappear. The
system should show the best provisional cell, alternatives, reasoning, and a focused
question to the existing Objective Review user. Human approval applies to the
objective as a useful unit of learning; preliminary classification remains guidance
until the RLO's actual instructional and assessment content exists.
