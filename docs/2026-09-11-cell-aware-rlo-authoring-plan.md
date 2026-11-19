# Cell-Aware RLO Authoring Plan

**Date:** 2026-09-11
**Status:** Core runtime implementation complete; live quality evaluation pending
**Authoring guidance:** `docs/rlo-authoring-guidance-by-content-type-and-bloom.md`

## Implementation checkpoint

Implemented on 2026-09-11:

- 13 explicit, versioned cell profiles with part-scoped, prioritized guidance;
- a shared flexible-guidance policy composed into the existing authoring prompts;
- separation of advisory guidance from source mapping and knowledge enrichment;
- structured achieved, approximated, missed, and not-applicable review outcomes;
- fail-open handling for guidance misses and malformed guidance-review references;
- instructional-approach review and metadata export; and
- container coverage for profile selection, prompt scoping, review behavior, and UI.

The baseline comparison, repeated quality evaluation, and paid live commissioning runs
in Phases 1, 6, and 7 remain operational follow-up work. They require selected source
collections and intentional model spend; they are not runtime implementation gaps.

## Objective

Use the learning team's Content-Type × Bloom guidance to make RLO instruction more
appropriate to the learner performance without creating 13 duplicated prompt suites
or turning every pedagogical preference into a brittle pass/fail rule.

The pipeline should give the model a concise, cell-specific creative brief and ask it
to get as close as reasonably possible. Structural integrity, factual lineage,
assessment validity, and the approved objective remain firm. Cell-specific authoring
patterns are graded guidance: the system should prefer, evaluate, and expose them, but
should not discard a coherent RLO merely because the model missed one pattern.

## Problem statement

The current pipeline already:

- classifies objectives into the 13 supported Content-Type × Bloom cells;
- selects a versioned methodology profile;
- passes that profile into source mapping, enrichment, generation, and validation;
- generates the seven canonical RLO parts; and
- records requirement coverage and review findings.

The methodology profiles in `api/src/source_authoring/methodology.py` are intentionally
generic. They describe broad requirements for a content type and Bloom level, but do
not differentiate instructional treatments such as contrastive cases, cue fading,
root-cause diagnosis, procedure tailoring, or multi-principle judgment.

The new authoring guidance supplies that missing differentiation. Copying all 44 pages
into prompts would create overlapping instructions, large contexts, duplicated rules,
and unstable compliance. Creating 13 complete prompt suites would create a similar
maintenance problem. The intended solution is 13 compact data profiles used by a
small set of shared prompts.

## Design principles

### Guidance, not exhaustive compliance

Cell guidance is a prioritized description of a strong RLO, not a checklist that must
be satisfied literally in every case. The model may use an equivalent instructional
treatment when literal compliance would be unsupported, incoherent, repetitive, or
poorly suited to the available claims.

Missing guidance should normally produce a reviewer-visible warning or approximation
note, not a failed job.

### Preserve hard boundaries

Flexible pedagogy must not weaken the boundaries that protect correctness. The
following remain hard invariants:

- one approved objective and one valid target cell;
- exactly seven parts in canonical order;
- valid structured output and reference integrity;
- every substantive learner-facing assertion resolves to a declared claim;
- source attribution is accurate;
- LLM-domain knowledge is labeled and carries model/prompt provenance;
- assessment answers use assessment-eligible claims;
- assessment structures are internally valid;
- Practice and Check do not silently assess a broader objective; and
- no organizational policy, threshold, responsibility, or regulated requirement is
  invented to make a scenario more realistic.

Hard failures should be limited to violations of these boundaries or other conditions
that make an RLO invalid, misleading, or unusable.

### Prefer coherence over literal rule accumulation

When guidance items compete, the pipeline should prioritize:

1. factual and provenance integrity;
2. the approved objective and cognitive demand;
3. a coherent learner experience;
4. high-priority cell guidance;
5. lower-priority enrichments and stylistic preferences.

The model should not add weak examples, filler interactions, artificial
counterarguments, or repetitive practice merely to increase checklist coverage.

### Keep guidance local to the operation

Each model call should receive only:

- the selected cell profile;
- the guidance relevant to the part being authored or reviewed;
- the claims and evidence available to that operation; and
- the minimum assembled-RLO context needed for cohesion.

No operation should receive all 13 profiles or the full source documents.

### Make approximation explicit

If the available interaction format cannot fully express the ideal instructional
method, the model should produce the closest defensible approximation without
pretending it is equivalent. For example, a selected action followed by a selected
rationale can approximate visible reasoning, but it should not be represented as a
full learner-authored defense.

Approximation must not:

- introduce unsupported facts;
- turn an intentionally contested case into a falsely objective answer;
- claim to assess a performance the interaction cannot observe; or
- conceal a meaningful reduction in cognitive demand.

## Proposed architecture

```text
Approved objective
      |
Target Content-Type x Bloom classification
      |
Versioned cell guidance profile (one of 13)
      |
Relevant part guidance + available claims
      |
Shared Setup / Teach-Show / Practice-Check / Send-off prompts
      |
Structured authoring revision
      |
Hard invariant validation + graded guidance review
      |
Reviewer-visible result, approximations, and warnings
```

## Profile model

Keep the 13 profiles explicit and versioned. Avoid a complex inheritance system; 13
small records are easier to inspect, test, and compare than deeply composed rules.
Universal prompt rules remain in the shared prompt assets rather than being repeated
in every profile.

Each profile should contain:

- profile ID and version;
- content type and Bloom level;
- a one-sentence instructional intent;
- guidance grouped by RLO part;
- priority for each guidance item;
- acceptable approximations where known;
- anti-patterns to avoid;
- review dimensions; and
- any deterministic hints, such as a preferred attempt count or scaffold sequence.

Illustrative shape:

```yaml
profile_id: concept-apply
version: cell-guidance-v1
intent: Classify novel, unambiguous cases from critical attributes.
guidance:
  - id: teach-attribute-checklist
    part: teach
    priority: high
    instruction: Turn critical attributes into an actionable checklist.
  - id: show-visible-attribute-reasoning
    part: show
    priority: high
    instruction: Derive the verdict attribute by attribute from case evidence.
  - id: practice-progressive-fading
    part: practice
    priority: medium
    instruction: Reduce checklist support over successive attempts.
    preferred_shape:
      attempts: 3
      scaffolds: [full, reduced, none]
    acceptable_approximation: Use fewer distinct attempts when the source cannot
      support three credible cases; preserve visible scaffold reduction.
  - id: check-novel-clear-case
    part: check
    priority: high
    instruction: Use a new, unambiguous case and require the deciding attribute.
avoid:
  - Classifying from surface resemblance.
  - Introducing a genuinely contested case at Apply level.
review_dimensions:
  - Attribute reasoning is visible.
  - Practice support decreases without changing the objective.
```

Priority expresses how valuable a pattern is; it does not turn the item into a schema
mandate. The initial vocabulary should remain small: `high`, `medium`, and `low`.

## Authoring contract changes

### Separate baseline requirements from cell guidance

Retain the current methodology requirements that describe the minimum instructional
substance needed to map and enrich claims. Add a separate `MethodologyGuidance` model
for cell-specific authoring preferences.

This separation matters because current requirement coverage contributes to part
completeness. A missed cue-fading preference should not make an otherwise complete
Practice part structurally absent or cause source enrichment to manufacture content
only to satisfy the preference.

Suggested fields:

```text
MethodologyGuidance
  guidance_id
  part
  priority
  instruction
  preferred_shape (optional structured data)
  acceptable_approximation (optional)
```

The authoring revision should continue recording the exact profile ID and version.
Generated elements may reference the guidance they address, but those references must
not be used as proof that the guidance was actually achieved.

### Record assessed guidance outcomes

Add reviewer-facing guidance assessments produced after assembly:

```text
GuidanceAssessment
  guidance_id
  status: achieved | approximated | missed | not_applicable
  explanation
  affected_paths
```

These are assessments, not new learner-facing content and not hard validation errors.
They allow reviewers to see where the model followed the selected instructional
signature and where it took a defensible approximation.

## Prompt strategy

### Keep the existing shared prompt boundaries

Continue using shared prompts for:

- Setup;
- Teach and Show;
- Practice and Check; and
- Send-off.

Each prompt should receive only the selected profile guidance for its parts. Shared
rules for provenance, claim use, response shape, cohesion, and tone remain in the
prompt asset and should not be duplicated in profile text.

### Add a common guidance policy

Every generation prompt should include a concise policy with this meaning:

> Treat the cell profile as prioritized authoring guidance. Follow high-priority
> guidance where the available claims and interaction shape support it. Prefer a
> coherent, instructionally useful approximation over forced or repetitive literal
> compliance. Never invent substantive knowledge to satisfy guidance. Preserve the
> approved objective and identify meaningful approximations in the structured output.

This policy should appear once in the shared generation layer, not be paraphrased
differently in every profile.

### Do not place worked examples in production prompts

The fictional audit examples should become offline calibration fixtures only. Adding
them to production prompts would encourage lexical imitation, audit-domain leakage,
invented policy, and repetitive scenario structures.

### Add prompt families only for different output contracts

Do not create one prompt suite per cell. A new prompt or workflow is justified only
when the learner interaction and output contract are materially different.

The likely long-term families are:

1. retrieval and explanation;
2. guided application and classification; and
3. argument, diagnosis, tailoring, and judgment.

The third family may eventually require open responses, conversational turns, or
role-play state. That is a separate product capability. Until then, the current
pipeline may produce a bounded approximation and disclose the fidelity gap.

## Validation and repair behavior

### Deterministic validation

Use code only for facts the system can establish reliably, including:

- profile matches the target classification;
- guidance IDs and part references are valid;
- seven-part and claim/evidence integrity remains intact;
- assessment structures are valid;
- declared misconception references resolve; and
- explicit structured shapes are internally consistent when the model elects to use
  them.

Do not deterministically fail an RLO because it has two strong practice attempts
instead of a preferred three, lacks a staged fade that the available content cannot
support, or uses an equivalent expert-modeling treatment.

### Model-based pedagogy review

The pedagogy reviewer should evaluate selected guidance semantically and return one
assessment per relevant guidance item. It should consider equivalence and explain why
an alternative does or does not achieve the authoring intent.

The reviewer should not count surface tokens or require exact phrases from the profile.
It should distinguish:

- achieved intent;
- a useful but lower-fidelity approximation;
- a meaningful miss; and
- guidance that is not applicable because of the approved objective or available
  knowledge.

### Bounded repair

High-value misses may trigger one targeted repair when the issue is local and
repairable without changing the objective or inventing knowledge. If repair fails or
would degrade the RLO, preserve the best valid result and show the warning to the
reviewer.

No guidance-only failure should discard completed calls, erase compatible
checkpoints, or restart the full RLO. Hard invariant failures retain the existing
targeted repair and fail-closed behavior where required for correctness.

## Review experience

Extend Completed-RLO Review with a compact “Instructional approach” summary:

- selected Content-Type × Bloom cell;
- one-sentence instructional intent;
- achieved guidance;
- approximations and their rationale;
- meaningful misses requiring reviewer judgment; and
- any interaction-fidelity limitation.

Do not expose all profile text by default. The summary should support triage, with an
optional drill-down to the exact versioned guidance used for that run.

Approval remains one RLO-level action. Guidance findings inform reviewer judgment but
do not create per-guidance approval gates.

## Implementation phases

### Phase 1: Establish a baseline

- Select a small, varied set of current RLOs covering at least Fact × Remember,
  Concept × Apply, Process × Understand, Procedure × Apply, and Principle × Apply.
- Preserve their current authoring revisions and generation telemetry.
- Record recurring rigidity, repetition, weak expert modeling, assessment mismatch,
  and provenance findings.

**Verification:** The baseline can be regenerated and compared without deleting
source documents, segments, objective workspaces, or approved RLOs.

### Phase 2: Add versioned cell guidance profiles

- Add `MethodologyGuidance` to the authoring contracts.
- Translate the compressed guide into 13 concise profiles.
- Keep generic substantive requirements separate from advisory cell guidance.
- Add unit tests proving all and only the 13 valid cells resolve to one profile.
- Snapshot profile IDs, versions, and content for reproducibility.

**Verification:** Profile selection is deterministic, compact, and inspectable; no
model call receives unrelated cell guidance.

### Phase 3: Inject part-specific guidance

- Add the common guidance policy to the shared generation prompts.
- Pass Setup guidance only to Setup generation, Teach/Show guidance only to
  Teach/Show generation, and so on.
- Allow generation outputs to identify addressed guidance and meaningful
  approximations.
- Keep source mapping focused on substantive knowledge requirements rather than
  scenario or interaction preferences.

**Verification:** Prompt snapshots show one selected profile and only relevant part
guidance. Token growth remains bounded.

### Phase 4: Add graded guidance review

- Add structured `GuidanceAssessment` output.
- Update pedagogy validation to judge intent and acceptable equivalence.
- Keep guidance misses as warnings or reviewer escalations rather than structural
  errors.
- Limit guidance-driven repair to one local attempt.
- Preserve usable partial results and compatible checkpoints.

**Verification:** A missed preference does not fail or discard an RLO; an invalid
assessment claim or false attribution still does.

### Phase 5: Expose instructional approach in review

- Show selected cell and instructional intent.
- Summarize achieved, approximated, and missed guidance.
- Provide profile-version and run-snapshot drill-down.
- Preserve expanded review state during job polling.

**Verification:** A reviewer can distinguish a strong match, an explicit
approximation, and a substantive pedagogy miss without reading raw JSON.

### Phase 6: Evaluate quality and stability

- Convert the learning team's worked examples into offline evaluation cases without
  copying their fictional facts into production prompts.
- Add at least one non-audit case per profile family to detect domain overfitting.
- Compare baseline and cell-aware outputs for instructional fit, coherence, diversity,
  repetition, claim integrity, guidance achievement, calls, tokens, cost, and elapsed
  time.
- Run generation repeatedly for selected inputs to identify unstable guidance,
  contradictory reviews, and repair loops.

**Verification:** Cell-aware outputs show materially different instructional treatment
where appropriate, while repeated runs remain valid and do not converge on copied
worked-example language.

### Phase 7: Commission through the running stack

- Rebuild affected services through Docker Compose.
- Regenerate the baseline prototypes under the new profile version.
- Review results through the nginx gateway and direct API routes.
- Confirm published RLOs remain compatible with catalog indexing and commissioning
  retrieval.
- Record final before/after telemetry in Langfuse.

**Exit gate:** The selected cell meaningfully influences authoring; guidance misses are
visible but do not create brittle failure; hard correctness boundaries remain intact;
and reviewers judge the resulting RLOs less generic without seeing systematic
overfitting or repetition.

## Verification matrix

All automated and application tests run in containers.

### Profile selection and prompt inputs

- Every valid cell selects exactly one versioned profile.
- Invalid cells remain rejected at classification.
- Each operation receives only guidance relevant to its authored parts.
- Prompt snapshots do not include worked-example prose or unrelated cell profiles.

### Flexible guidance behavior

- A high-priority guidance item can be marked achieved, approximated, missed, or not
  applicable.
- A guidance-only miss does not make the RLO structurally invalid.
- An accepted equivalent treatment can satisfy the intent without exact wording.
- Guidance does not cause unsupported claims to be invented.
- One local repair failure preserves the best prior valid output.

### Hard-boundary behavior

- False source attribution remains an error.
- LLM-domain knowledge remains explicitly attributed.
- Assessment answers cannot rely on ineligible context claims.
- Practice and Check cannot expand the approved objective unnoticed.
- Invalid reference graphs and malformed assessments remain errors.

### Quality and diversity

- Fact × Remember uses meaningful retrieval rather than generic scenario judgment.
- Concept × Apply makes attribute reasoning visible.
- Process × Understand represents actors and transitions, not only a step list.
- Procedure × Apply exposes decision rationale, not only ordered steps.
- Principle × Apply connects case feature, principle, and action.
- Different cells do not collapse into the same scenario/MCQ pattern.
- Outputs do not imitate the fictional audit examples across unrelated domains.

### Review and operations

- Review shows the selected instructional intent and approximations.
- Guidance detail remains inspectable by profile and run version.
- Polling does not collapse expanded guidance or provenance sections.
- Retries reuse compatible source mapping, enrichment, and generation checkpoints.
- Langfuse records profile version, model calls, tokens, cost, and elapsed time.

## Non-goals

This plan does not:

- implement scheduled spaced-practice delivery;
- build a conversational tutor or role-play engine;
- implement learner-state or LMS orchestration;
- create 13 independent prompt suites;
- treat fictional worked examples as source truth;
- make every preferred item count or scenario pattern mandatory;
- guarantee that a closed-response approximation measures the same performance as an
  open learner-authored response; or
- replace human review of consequential domain claims or pedagogy.

## Risks and mitigations

### Too much guidance recreates the original problem

Profiles must stay concise and part-specific. Remove duplicated universal rules and
measure prompt-token growth. If a guidance item cannot change authoring or review, it
does not belong in the runtime profile.

### Soft guidance becomes meaningless

Use explicit priority and graded assessments. Review whether high-priority guidance is
consistently missed, but do not convert it automatically into a hard rule. Improve
the profile, prompt, interaction capability, or source inputs based on evidence.

### Model reviewers reward superficial compliance

Ask reviewers to judge instructional intent and evidence, not keyword presence. Use
deterministic checks only for structured facts and compare reviews against human-rated
offline cases.

### Approximation overstates assessment validity

Expose fidelity limitations and avoid claiming that selected reasoning is equivalent
to producing and defending reasoning. Preserve the target cell while making the
observability gap clear to reviewers.

### Cell profiles make outputs more repetitive

Specify cognitive structure rather than scenario prose. Require surface variation and
evaluate repetition across a collection. Do not place the worked examples in runtime
prompts.

## Decisions required before implementation

1. Confirm that cell-specific patterns are advisory authoring guidance rather than
   binding acceptance criteria.
2. Confirm which existing hard invariants must remain publication blockers.
3. Decide whether current closed-response approximations may be published for
   Analyze/Evaluate cells or must carry a reviewer escalation.
4. Decide whether guidance assessments belong in the immutable authoring revision,
   review metadata, or both.
5. Select the initial baseline RLOs and human reviewers for quality comparison.
