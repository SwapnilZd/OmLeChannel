# Source-Anchored, LLM-Enriched RLO Implementation Plan

## Status

Implementation through Completed-RLO Review is complete. The focused RLO authoring,
review, API, and UI test suite passes in the API test container (39 tests). Runtime
images rebuild successfully. The commissioning stack now runs from the repository's
Projects location, and authenticated browser smoke checks pass at mobile and desktop
widths. LiteLLM now runs on Python 3.12 with the repository CA certificate, and a live
source-segment embedding call succeeds through the proxy. A live objective extraction
also completes with 42 candidates and 69 persisted prompt runs after checkpoint recovery.
Full model-backed RLO generation remains pending.

## Goal

Continue using uploaded source material to discover learning objectives while also
surfacing important, practitioner-relevant objectives that are related to the source
but not fully teachable from it. Permit the RLO authoring pipeline to supply missing
domain knowledge from an LLM, while preserving an honest distinction between:

- content supported by uploaded source evidence;
- synthesis derived from uploaded evidence;
- substantive domain knowledge supplied by an LLM; and
- generated instructional scaffolding that introduces no domain proposition.

The result should be described as **source-anchored** rather than wholly
source-grounded whenever substantive LLM knowledge is used.

## Product decisions for this implementation

These decisions define the initial POC behavior and prevent implementation from
silently answering unresolved policy questions.

1. Source-derived objective discovery remains the first pass and continues to use the
   complete source collection, document hierarchy, claims, curriculum blueprint, and
   practitioner lenses.
2. A second, explicit discovery pass proposes high-value objectives related to the
   source that the source does not fully address.
3. Every objective must retain a meaningful source relationship. The related-objective
   pass is not permission to generate a general curriculum from only a topic label.
4. A related objective may use source evidence as an anchor without representing that
   evidence as sufficient to teach or assess the complete performance.
5. Missing domain knowledge may be supplied by an LLM. It must be represented as
   LLM-origin knowledge, not cited to the uploaded source.
6. LLM provenance establishes how content was produced. It does not establish factual
   correctness or replace an authoritative citation.
7. SME input is not a required step in the POC workflow.
8. The existing two human gates remain: objective review and completed-RLO review.
   LLM enrichment does not create a third approval stage.
9. Final RLO approval accepts the visible source-supported and LLM-origin content in
   that revision. The UI must make their origins easy to distinguish before approval.
10. No automatic external research or third-party data-processing API is added in this
    phase. All model calls continue through purpose-specific LiteLLM aliases.
11. Generated Practice and Check items remain closed-response. Their answer and
    feedback logic must resolve to claims in the combined claim ledger.
12. Existing prototype objective and RLO payloads may be regenerated. Compatibility
    adapters are not required, but immutable source extraction artifacts should be
    retained and reused.

## Terminology

### Objective discovery basis

- `source_derived`: The complete learner performance is materially supported by the
  uploaded source collection.
- `source_related`: The objective is important to practitioner use of the source's
  subject matter, but the source does not fully teach or support the performance.

Authorship and support must remain separate. The existing `ObjectiveOrigin.MODEL` and
`ObjectiveOrigin.LDS` field continues to record who proposed the objective. Every
model- or LDS-authored objective receives either a `source_derived` or
`source_related` support basis.

### Claim knowledge origin

- `source_direct`: A substantive proposition directly supported by exact source
  evidence.
- `source_synthesis`: A substantive proposition reasonably derived from cited source
  claims without adding outside domain knowledge.
- `llm_domain`: A substantive proposition supplied from model knowledge and not
  verified by the uploaded sources.

Claims should be atomic and have one knowledge origin. If a statement combines source
and LLM propositions, split it into separate claims rather than using a `mixed` claim.

### Element origin

- `source`: The element uses only source-direct or source-synthesis claims.
- `llm_domain`: The element uses only substantive LLM-domain claims.
- `mixed`: The element combines source and LLM-domain claims.
- `instructional_scaffold`: The element is neutral instructional framing or structure
  and contains no substantive domain proposition.

Element origin describes composition. Claim origin describes the epistemic basis.
They are related but not interchangeable.

### Source support level

- `substantial`: Uploaded evidence can support the objective's complete assessment
  boundary.
- `partial`: Uploaded evidence supports a material portion, but important knowledge is
  missing.
- `anchor_only`: The source establishes the topic or importance but not the complete
  learner performance.

Do not calculate a false percentage of source contribution.

## Target workflow

```text
Uploaded source collection
        |
        v
Existing extraction, hierarchy, document map, and claim ledger
        |
        +--> Source-derived objective discovery
        |
        +--> Related practitioner-objective discovery
                  |
                  v
        Reconciliation, deduplication, support assessment
                  |
                  v
        LDS Objective Review
                  |
                  v
        Source mapping and knowledge-gap plan
                  |
                  v
        LLM domain-knowledge enrichment where needed
                  |
                  v
        Combined claim ledger with per-claim provenance
                  |
                  v
        Seven-part RLO generation and validation
                  |
                  v
        LDS Completed-RLO Review
```

## Contract changes

### Objective support contract

Add an `ObjectiveSupportProfile` to every `ObjectiveCandidate`:

```text
discovery_basis
source_support_level
source_relationship
source_contributions[]
missing_knowledge[]
anticipated_llm_contributions[]
source_claim_ids[]
review_note
```

Requirements:

- `source_derived` requires objective-defining source evidence and `substantial`
  support.
- `source_related` requires at least one exact source anchor and a specific explanation
  of the relationship, but it does not require source evidence to support the complete
  assessment boundary.
- `source_related` must declare at least one missing or anticipated LLM contribution.
- Objective statements must not imply that a source-defined method, threshold,
  responsibility, or decision rule exists when it does not.
- Preserve the existing model-vs-LDS author origin independently.

Extend evidence roles with `source_anchor`. Source-anchor evidence is not assessment
eligible by itself.

### Objective coverage contract

Replace the current assumption that only source-sufficient gap targets warrant
discovery. A coverage gap may route to:

- `source_search`: another bounded search of supplied claims may find a supported
  objective;
- `related_objective_discovery`: the source relationship is meaningful but complete
  support is absent;
- `not_warranted`: the gap is peripheral, duplicative, or too weakly related.

The routing decision must remain distinct from whether a domain is adequate, partial,
missing, or source-insufficient.

### Claim provenance contract

Extend `AuthoringClaim` with:

```text
knowledge_origin
evidence_refs[]
source_claim_refs[]
llm_provenance_ref
verification_status
origin_rationale
```

Validation rules:

- `source_direct` requires exact evidence references.
- `source_synthesis` requires source-claim and evidence references plus a concise
  derivation rationale.
- `llm_domain` must not carry source evidence as if it supported the proposition.
- `llm_domain` requires an LLM provenance reference and visible `unverified` status
  until the completed RLO is approved.
- Final RLO approval may change that status to `review_accepted`, not
  `source_verified`. Human acceptance does not create an authoritative citation.
- `supporting_context` remains ineligible to define an assessment answer regardless
  of knowledge origin.
- Assessment-eligible LLM claims are permitted, but the review UI must identify them
  prominently.

Use a separate `LLMKnowledgeProvenance` record containing:

- stable provenance ID;
- operation and checkpoint ID;
- LiteLLM model alias;
- prompt ID, version, filename, and hash;
- generation job and RLO revision IDs;
- input snapshot hash or durable snapshot reference;
- output snapshot reference;
- generation timestamp; and
- an explicit statement that model lineage is not source verification.

Do not store hidden chain-of-thought. Retain the model's concise, reviewer-facing
rationale and assumptions only.

### RLO authoring contract

- Bump the authoring schema version rather than overloading v1 semantics.
- Add the LLM provenance collection to `AuthoringRLORevision`.
- Preserve exact source, evidence, segment, claim, and prompt references.
- Replace the current source/mixed/generated element-origin enum with the four
  composition states defined above and derive origin deterministically from claim
  origins where practical.
- Replace `source_insufficient` as a terminal content status with explicit knowledge
  gaps and enrichment outcomes.
- Retain `source_insufficient` only for legacy payload reading until prototype data is
  regenerated.

## Prompt architecture

All new and revised prompts must remain named, versioned Markdown files in the existing
prompt directories. Update each prompt README inventory with purpose, execution point,
model alias, and output contract.

### New objective prompts

1. `related_objective_discovery.md`
   - Runs after source-derived discovery and the initial coverage review.
   - Receives the curriculum blueprint, practitioner lenses, document map, source
     claims, existing candidates, and compact candidate memory.
   - Proposes materially new objectives that help a Deloitte practitioner use or act
     on the source's subject matter.
   - Explicitly allows model knowledge to identify a performance not contained in the
     source.
   - Must disclose missing knowledge and cannot fabricate source evidence.
   - Returns an empty list when no strongly related, high-value objective remains.

2. `objective_support_assessment.md`
   - Runs for related proposals before reconciliation.
   - Separates what the source supports from what the LLM inferred.
   - Rejects topic-only adjacency and objectives whose connection cannot be stated
     concretely.
   - Produces the support profile, not a Bloom or content-kind decision.

### Revised objective prompts

- Keep `candidate_formation.md` focused on source-derived objectives.
- Update `objective_set_coverage_review.md` so source insufficiency can route to the
  related-objective pass instead of suppressing further discovery.
- Update reconciliation and evidence verification to understand `source_anchor` and
  prevent it from being promoted to assessment evidence.
- Keep provisional Kind/Bloom classification after both candidate pools are merged.
  The classifier must consider the objective's intended practice, not infer that the
  source already demonstrates it.

### New RLO prompt

Add `llm_domain_enrichment.md`:

- Receives the approved objective, practitioner context, source claim ledger,
  methodology requirements, and explicit missing-knowledge plan.
- Produces atomic LLM-domain claims needed to teach and assess the objective.
- Must identify assumptions, uncertainty, and possible conflicts with supplied source
  claims.
- Must not invent source citations or describe model knowledge as authoritative.
- Must not introduce Deloitte policy, responsibility, thresholds, or internal practice
  unless they are present in the supplied source collection.
- Returns only the enrichment contract, not learner-facing Teach content.

### Revised RLO prompts

- Source mapping remains source-only and continues to cite exact segment IDs.
- Teach/Show and Practice/Check receive the combined claim ledger and each claim's
  knowledge origin.
- Remove the instruction that model memory can never supply domain knowledge.
  Replace it with a requirement to create LLM-domain claims during the enrichment step
  and use only claims already present in the combined ledger during authoring.
- Grounding review verifies only source-direct and source-synthesis claims against
  source evidence.
- Add a provenance review that detects missing, inconsistent, or falsely attributed
  origins.
- Pedagogy review verifies that source and LLM claims together adequately teach the
  objective.
- The final cohesion pass receives the complete RLO and provenance summary.
- Targeted repair may repair wording and claim usage, but must not silently change a
  claim's knowledge origin.

## Phased implementation

### Phase 1: Add objective support semantics

- [x] Add discovery-basis, support-level, and source-anchor enums.
- [x] Add `ObjectiveSupportProfile` and contract invariants.
- [x] Keep objective authorship separate from support basis.
- [x] Update workspace/package schema versions.
- [x] Update repository serialization and API responses.
- [x] Add unit tests for valid and invalid source-derived and source-related candidates.

**Exit gate:** A related objective can retain exact source anchors without claiming
that those anchors support its complete performance or assessment.

### Phase 2: Discover related practitioner objectives

- [x] Add inspectable related-discovery and support-assessment prompt assets.
- [x] Run related discovery after the initial source-derived coverage review.
- [x] Use additive candidate memory so repeated calls do not produce paraphrases.
- [x] Bound the pass by identified source-insufficient targets and configured
  model-request token limits, not an arbitrary objective count.
- [x] Require concrete practitioner relevance and a concrete relationship to at least
  one source domain or claim.
- [x] Reconcile, deduplicate, critique, and provisionally classify both candidate pools
  together.
- [x] Record prompt runs and checkpoints so a late failure does not discard earlier
  source-derived model work.
- [x] Update progress operations and job history to expose related discovery.

**Exit gate:** One source-processing job can return both source-derived and
source-related objectives, clearly labeled and without false source attribution.

### Phase 3: Update Objective Review

- [x] Add concise Source-derived and Source-related badges to objective cards.
- [x] Show source support level near the objective, not as a hidden advanced field.
- [x] Add one compact panel with “What the source provides” and “What the LLM would
  need to provide.”
- [x] Keep exact source anchors in the existing lineage view.
- [x] Explain that LLM-related objective discovery does not verify the missing subject
  matter.
- [x] Preserve approve, edit, reject, split, merge, and add-related-objective actions.
- [x] Ensure an LDS edit flags support reassessment when it changes the performance
  boundary.
- [x] Keep Excel export concise: objective, suggested Kind/Bloom, discovery basis,
  support level, missing knowledge summary, source location, and review fields.

**Exit gate:** An instructional designer can tell why an objective is useful, what is
actually supported, and what would be model-supplied before approving it.

### Phase 4: Build the combined claim ledger

- [x] Add claim-origin, verification-status, and LLM-provenance contracts.
- [x] Preserve the existing exact-segment source-mapping path unchanged.
- [x] Add a deterministic knowledge-gap plan after source mapping.
- [x] Run LLM domain enrichment only for declared gaps.
- [x] Normalize enrichment output into atomic `llm_domain` claims.
- [x] Detect direct contradiction with source claims and surface it as a finding.
- [x] Persist enrichment checkpoints and prompt-run snapshots.
- [x] Ensure retry resumes from the last compatible checkpoint.
- [x] Add `enriching_knowledge` to RLO job progress and API/UI state handling.

**Exit gate:** The authoring service produces one claim ledger containing source and
LLM claims whose origins cannot be confused or silently changed.

### Phase 5: Generate RLOs from mixed-origin knowledge

- [x] Update planning and methodology inputs to include the objective support profile.
- [x] Generate Teach and Show from the combined ledger.
- [x] Generate only closed-response Practice and Check items.
- [x] Require every correct answer, option feedback statement, and scoring decision to
  reference assessment-eligible claims.
- [x] Allow LLM-domain claims to support an answer while retaining their visible
  unverified status.
- [x] Do not stop merely because the uploaded source lacks complete Teach substance.
- [x] Use a retryable enrichment failure when model output is invalid; do not convert
  transport or schema errors into source insufficiency.
- [x] Keep the existing final cohesion pass and complete-RLO context.

**Exit gate:** A source-partial objective can produce a complete draft without
misrepresenting LLM-domain knowledge as source-supported.

### Phase 6: Validate provenance and instructional quality

- [x] Split grounding validation into source-grounding and provenance-integrity checks.
- [x] Verify source-direct and source-synthesis claims against exact evidence.
- [x] Verify every LLM-domain claim has complete generation provenance and no source
  attribution.
- [x] Detect learner-facing assertions and assessment logic that bypass the claim
  ledger.
- [x] Check source and LLM claims for internal contradiction and qualification loss.
- [x] Continue constructive-alignment, methodology, atomicity, and cohesion review.
- [x] Replace source-insufficiency errors with actionable findings such as missing
  knowledge, enrichment incomplete, unsupported source attribution, or LLM-origin
  review priority.
- [x] Do not claim that a second model's agreement verifies an LLM-domain fact.

**Exit gate:** Validation can prove lineage completeness and source entailment without
claiming that uncited model knowledge has been independently fact-checked.

### Phase 7: Update Completed-RLO Review

- [x] Rename or extend Source Lineage to Content Provenance.
- [x] Show a compact content-composition summary by claim origin.
- [x] Retain drill-down from each element and assessment answer to its claims.
- [x] Show source evidence for source claims and model/prompt provenance for LLM claims.
- [x] Use distinct labels for Source supported, Source synthesis, LLM domain knowledge,
  and Instructional scaffolding.
- [x] Add filters for LLM-origin claims and assessments that rely on them.
- [x] Keep approval as one final RLO action rather than adding per-claim approval gates.
- [x] Include the provenance summary in exported or published review metadata.

**Exit gate:** A reviewer can identify every substantive model-supplied proposition and
every assessment that depends on one before approving the RLO.

### Phase 8: Regenerate prototypes and verify end to end

- [ ] Provide an explicit, narrowly scoped prototype-data cleanup or regeneration path.
- [ ] Preserve extracted source documents, segments, images, and source collections.
- [ ] Regenerate objective workspaces and RLO jobs under the new schema versions.
- [x] Rebuild API, source worker, RLO worker, and gateway through Docker Compose.
- [x] Verify the running UI at responsive widths.
- [ ] Record before/after prompt counts, model calls, token use, and elapsed time.
- [x] Confirm a failed late-stage operation can retry without repeating compatible
  discovery, mapping, and enrichment checkpoints.

**Exit gate:** A fresh source upload can complete the entire revised workflow in the
containerized application, and the final review clearly distinguishes source and LLM
knowledge.

## Verification matrix

All automated tests and application smoke tests must run in containers.

### Objective discovery

- [ ] A source-supported performance becomes `source_derived` with substantial support.
- [ ] A high-value related performance becomes `source_related` with partial or
  anchor-only support and declared missing knowledge.
- [ ] A merely topical objective is rejected by support assessment.
- [ ] A related candidate cannot use a source anchor as assessment-eligible evidence.
- [ ] Related discovery returns no duplicates across iterative memory calls.
- [ ] Manual LDS edits that broaden an objective trigger support reassessment.

### Claim provenance

- [ ] Source-direct claims require evidence and exact segment lineage.
- [ ] Source-synthesis claims require source references and a derivation rationale.
- [ ] LLM-domain claims require model and prompt provenance and cannot cite source
  evidence as support.
- [ ] Mixed propositions are rejected until split into atomic claims.
- [ ] Neutral scaffolding remains possible without a substantive claim.
- [ ] False source attribution produces an error rather than an LLM warning.

### Generation and assessment

- [ ] A source-complete objective generates without LLM-domain claims.
- [ ] A source-partial objective generates with clearly labeled LLM-domain enrichment.
- [ ] Teach, Show, Practice, and Check use the same combined claim ledger.
- [ ] Every correct answer and feedback explanation resolves to eligible claims.
- [ ] No open-response assessment is generated.
- [ ] The final cohesion pass cannot remove or obscure provenance.

### UI and operations

- [ ] Objective Review exposes basis, support, missing knowledge, and source anchors.
- [ ] Completed-RLO Review exposes source evidence and LLM provenance.
- [ ] Job progress identifies source discovery, related discovery, mapping, enrichment,
  generation, validation, and review.
- [ ] Prompt text and exact run snapshots remain inspectable.
- [x] Retries reuse compatible checkpoints.
- [x] UI pages load through the local nginx gateway and direct API service routes.

## Success criteria

- Source-derived objective discovery retains current source breadth and lineage.
- The pipeline surfaces important related objectives even when the source cannot fully
  teach them.
- Every related objective clearly states what the source supports and what the LLM
  would need to add.
- RLO generation no longer fails solely because the initial source is instructionally
  incomplete.
- No substantive LLM-origin claim is presented as source-supported.
- Every substantive learner-facing assertion and assessment answer resolves to an
  atomic claim with a declared origin.
- Reviewers can isolate LLM-origin knowledge without reading raw JSON.
- The implementation contains no rules, examples, or prompts tuned to a particular
  source document or subject.

## Risks and explicit limitations

### Model provenance is not verification

Recording model, prompt, input, and output lineage makes generation auditable but does
not make the resulting domain claim true. The completed-RLO reviewer may not be a
subject-matter expert. This POC therefore accepts a material quality risk when
LLM-domain claims are used in high-consequence subject areas.

### Related-objective expansion can become unbounded

A source topic can connect to an enormous universe of professional capabilities. The
related pass must require a concrete source relationship and practitioner benefit, use
additive memory, and stop after the configured operation budget. It must not try to
produce a complete curriculum for the general topic.

### Model self-review is not independent fact-checking

Grounding checks can verify cited source claims. A second model can identify
inconsistency or suspicious LLM claims, but it cannot convert uncited model knowledge
into authoritative content merely by agreeing with it.

### Regulatory and organizational claims remain especially risky

The LLM enrichment prompt must continue prohibiting invented Deloitte policy and
internal responsibilities. Legal, tax, regulatory, and cybersecurity claims may be
plausible but wrong, outdated, jurisdiction-dependent, or incomplete. Provenance must
make that risk visible rather than masking it.

### RLO reuse remains an assumption to validate

This change makes RLOs more instructionally complete, but it does not prove that they
will be reused coherently across learning pathways. Reuse, review cost, and update
behavior should be measured before treating RLO atomization as the required production
architecture.

## Deferred follow-up

- Retrieval of additional public or enterprise sources to verify LLM-domain claims.
- Formal SME contribution and attestation workflows.
- Domain-specific policies that prohibit or restrict LLM-origin knowledge.
- Automated claim currency monitoring beyond uploaded-source version checks.
- Confidence calibration based on reviewer outcomes.
- Production migration of legacy RLOs and long-term schema compatibility.
