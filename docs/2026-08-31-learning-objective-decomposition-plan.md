# Learning Objective Decomposition Build Plan

**Status:** Draft for discussion

**Branch:** `feature/learning-objective-decomposition`

**Initial scope:** Layer 1 — Decomposition

**Downstream context:** Classification → Mapping → Validation → Instructional Designer review → RLO generation

## Purpose

Build a scalable, evidence-grounded process that turns one or more extracted source
documents into candidate enabling objectives: specific things a practitioner should
be able to do. The process must work across large, hierarchical documents, preserve
source lineage, expose uncertainty, and give learning admins an effective sandbox
for reviewing and editing the results.

The relevance boundary is the realistic work of Deloitte practitioners: their
tasks, decisions, risks, and expected performance. The system should over-surface
plausible enabling objectives within that boundary, but it should not turn every
interesting fact in a source into an objective merely because the source mentions
it. When admin context is absent, practitioner lenses and their assumptions remain
explicitly inferred and reviewable.

This phase stops at decomposition. It may attach a preliminary content-type and
Bloom-level hint, but it does not commit a candidate to an RLO cell, map the seven
RLO sections, validate a complete RLO, or generate missing instructional content.

## Materials reviewed

The five supplied files were treated as business and instructional-design source
material, not as executable instructions:

- `01_RLO_Decomposition_Rules_Simplified - Copy.docx`
- `02_RLO_Classification_Rules_Simplified - Copy.docx`
- `03_RLO_Mapping_Rules_Simplified - Copy.docx`
- `04_RLO_Validation_Rules_Simplified - Copy.docx`
- `rlo-generator_v1.0.pptx`

The decomposition document is the primary input for this build. The other four
documents define the handoff contract and prevent Layer 1 from absorbing work that
belongs downstream.

## Product outcome

A learning admin can select an ingested source collection, optionally describe the
practitioner context, run decomposition, and review a complete candidate inventory.
For each candidate, the admin can see:

- a standard-form, observable objective;
- its expected practitioner context and approximate 5–15 minute scope;
- the practitioner task, decision, or risk that makes it worth teaching;
- High, Medium, or Low confidence with an explanation;
- the decomposition rules and signals that produced it;
- exact source evidence, including file and page/slide/section locators;
- preliminary content-type and Bloom-level hints, clearly marked as uncommitted;
- parent/child, prerequisite, related, duplicate, and conflict relationships;
- assumptions, currency warnings, and other review flags;
- whether the candidate is new, edited, approved for classification, or rejected by
  the learning admin.

No candidate should disappear merely because it is low-confidence, duplicated,
overly broad, or beyond an arbitrary display limit. Those conditions should remain
visible and reviewable.

There is no fixed candidate-count target or result cap. Candidate volume should
follow the number of distinct, practitioner-relevant enabling objectives supported
by the source. Request-size, response-size, pagination, and worker limits remain
per-call or concurrency controls rather than total candidate-count limits or
curriculum decisions.

## Existing foundation

The current source-content implementation already provides much of the required
platform:

- Docling-based extraction, OCR, visual explanations, and source locators;
- ordered document nodes and hierarchy paths;
- configurable token-bounded segmentation;
- section, document, and collection source maps with claim-level citations;
- optional practitioner instructions and inferred practitioner lenses;
- Postgres-backed, revisioned objective workspaces and admin decisions;
- LiteLLM aliases and Langfuse tracing for model-backed stages;
- an extraction/objective sandbox and grounded RLO drafting workflow.

The existing objective service is a useful prototype, but it currently combines
decomposition, evidence verification, pedagogy critique, deduplication, ranking,
and filtering. It also caps the initial candidate list at 12. The supplied rules
instead define decomposition as a high-recall stage: surface uncertain candidates
and preserve them for review because later stages cannot recover an objective that
was never found.

## Proposed decomposition flow

```mermaid
flowchart LR
    A[Hierarchical source maps] --> B[Bounded planning units]
    B --> C[Detect D-4–D-12 signals]
    C --> D[Form and decompose candidates]
    D --> E[Reconcile across units and files]
    E --> F[Attach confidence, lineage, and flags]
    F --> G[Learning-admin review workspace]
    G --> H[Approved candidates enter Classification]
```

Large documents are handled by processing bounded planning units, not by truncating
the collection. Every eligible source node must appear in a unit or in an explicit
coverage exception. Per-unit results are persisted before collection-level
reconciliation, allowing a long run to resume without repeating completed work.

## Design principles

1. **Objectives describe performance, not topics.** Standard form is “The learner
   will be able to [observable verb] [content],” with practitioner context recorded
   separately when useful.
2. **Practitioner need defines relevance.** Every candidate must connect to a
   realistic Deloitte practitioner task, decision, risk, or explicitly stated
   priority. Interesting background may support instruction without becoming an
   assessable enabling objective.
3. **Decomposition favors recall over precision.** Low-confidence and questionable
   candidates are surfaced with flags; they are not silently filtered.
4. **Source evidence remains canonical.** Model output never replaces source text,
   hierarchy, locators, or document identity.
5. **Document size does not define curriculum size.** Token limits bound individual
   calls. They do not cap total source coverage or silently cap total candidates.
6. **Hierarchy is preserved.** Candidates retain the sections, clauses, pages,
   slides, and parent objectives from which they were derived.
7. **Enabling objectives are the RLO boundary.** An RLO owns exactly one enabling
   objective. A stated terminal objective may guide decomposition and connect RLOs
   to a broader course or pathway outcome, but it is not itself stored as the RLO's
   objective unless it is genuinely atomic.
8. **Layer boundaries stay explicit.** Decomposition offers only preliminary cell
   hints; Classification owns the committed cell assignment.
9. **Human review concerns learning design.** Learning admins review candidate
   objectives and scope, not Docling extraction quality.
10. **Observable guarantees are tested.** Tests cover contracts, coverage, lineage,
   batching, and deterministic rules. They do not pretend to objectively score the
   pedagogical quality of model judgment.

Here, “standalone” means that an RLO is pedagogically complete for its one enabling
objective. It does not mean the RLO independently fulfills a terminal course,
capability, or pathway outcome.

## Proposed contracts

### Decomposition signal

Each signal should contain:

- stable signal ID and the applicable rule ID (`D-4` through `D-12`);
- signal type, such as explicit objective, heading, worked example, assessment,
  repetition, emphasis, reflective prompt, SME intent, or structured visual;
- one or more source citations with source version, node IDs, and locators;
- source role (primary or supplementary) and source structure type;
- the model's interpretation and confidence in the signal.

### Candidate objective

Each candidate should contain:

- stable candidate ID and workspace revision;
- standard-form objective statement and observable behavior;
- content boundary and performance context;
- the practitioner task, decision, risk, or priority establishing relevance;
- estimated active-engagement minutes;
- confidence plus a structured confidence rationale;
- supporting signal IDs and exact evidence references;
- preliminary content-type and Bloom-level hints;
- optional course/pathway outcome anchors, child enabling objectives,
  prerequisites, and postconditions;
- duplicate/near-duplicate group and cross-file corroboration;
- assumptions, conflicts, granularity flags, and currency flags;
- lifecycle status and learning-admin decision history.

### Decomposition run

Each run should record:

- collection/map revision and optional learning-brief revision;
- rule-set and prompt versions;
- model aliases and token usage;
- planning units and node-level coverage;
- persisted per-unit outputs and reconciliation output;
- progress, error, retry, and completion state.

## Phased implementation

### Phase 0 — Confirm Layer 1 policy and contracts

- [ ] Resolve the open decisions at the end of this plan.
- [ ] Translate D-1–D-19 into a versioned, machine-readable rule catalog.
- [ ] Define strict contracts for signals, candidates, relationships, confidence,
  flags, coverage, and run metadata.
- [ ] Define the exact handoff contract from Decomposition to Classification.
- [ ] Decide how existing prototype objective workspaces will be replaced; prototype
  backward compatibility is not required.
- [ ] Add contract tests for invalid citations, missing objective-defining evidence,
  invalid confidence rationales, broken parent/child links, and silent omissions.

**Exit gate:** The rule ownership and data contracts are agreed before model prompts
or UI behavior are changed.

### Phase 1 — Build hierarchy-aware planning and coverage

- [ ] Convert collection-map claims and source hierarchy into bounded planning units.
- [ ] Build planning units from the configured 15k tranche size and combine roughly
  five or six units within the separate configured model-request ceiling; do not
  introduce a tool-specific endpoint, credential, or model variable.
- [ ] Keep coherent sections together when they fit; split deterministically at
  existing node boundaries when they do not.
- [ ] Include limited ancestor context and adjacent context without duplicating the
  entire document in every request.
- [ ] Classify each source as structured material or SME-style material and as
  primary or supplementary, using admin metadata where available.
- [ ] Persist a node-level coverage ledger so every eligible node is processed,
  deliberately omitted with a reason, or reported as unresolved.
- [ ] Add restart/resume behavior for completed planning units.

**Exit gate:** A synthetic collection well beyond one model context window is fully
covered through multiple bounded units, with no truncation or silent node loss.

### Phase 2 — Detect decomposition signals

- [ ] Implement a structured-document detector for D-4–D-10 and D-12.
- [ ] Implement a distinct SME-intent prompt branch for D-11 with conservative
  starting confidence.
- [ ] Detect stated terminal objectives and preserve them as course/pathway outcome
  anchors while finding the enabling sub-skills beneath them (D-2).
- [ ] Do not emit a broad terminal objective as an RLO candidate; emit its atomic,
  practitioner-relevant enabling objectives and retain `supports_outcome` lineage.
- [ ] Treat tables, decision trees, flowcharts, matrices, and process diagrams as
  first-class evidence by consuming extracted visual explanations (D-12).
- [ ] Record rule IDs and exact citations for every signal.
- [ ] Preserve weak or ambiguous signals as Low confidence instead of dropping them.
- [ ] Add deterministic tests for each signal contract using small synthetic source
  fragments and visual structures.

**Exit gate:** Every surfaced signal is attributable to a rule and resolvable to
source nodes; weak signals remain visible.

### Phase 3 — Form atomic candidate objectives

- [x] Run candidate formation iteratively within each bounded source unit, carrying
  forward a compact memory of prior objective statements, behaviors, preliminary
  content-type/Bloom hints, and claim IDs.
- [x] Ask later passes for materially new objectives, emphasizing uncovered claims
  and different supported kinds or levels instead of a fixed objective count.
- [x] Stop deterministically when a follow-up pass adds nothing new, with four passes
  as a finite safety bound.
- [ ] Convert signals into standard-form, observable candidate objectives (D-1).
- [ ] Require each candidate to name the practitioner task, decision, risk, or
  explicit priority that establishes its learning relevance.
- [ ] Split compound objectives that span distinct actions or preliminary cells
  while retaining their relationship to the parent wording (D-16).
- [ ] Estimate the 5–15 minute active-engagement envelope and flag likely over-broad
  or over-narrow candidates rather than automatically deleting them (D-17).
- [ ] Infer conservative prerequisites and postconditions as a granularity check
  (D-18), distinguishing candidate links from external prerequisites.
- [ ] Attach preliminary content-type and Bloom-level hints without committing the
  Classification result.
- [ ] Preserve candidate derivation so an admin can see which signals were combined,
  split, or rewritten.
- [x] Persist every discovery pass as a separately named prompt run so its exact
  prompt, compact memory input, and structured output remain inspectable.

**Exit gate:** Each candidate describes one observable performance and carries a
complete derivation trail, even when its granularity remains uncertain.

### Phase 4 — Reconcile across units and files

- [ ] Compare semantically related candidates produced by different planning units.
- [ ] Group duplicates and near-duplicates without silently discarding any candidate.
- [ ] Merge evidence into a retained candidate only when the objective and scope are
  equivalent; preserve all source-specific citations.
- [ ] Apply cross-file corroboration and repetition signals (D-8, D-13).
- [ ] Weight sparse-file signals appropriately without inventing evidence (D-14).
- [ ] Prevent supplementary-only evidence from producing an unqualified candidate;
  retain it at Low confidence with a verification flag (D-15).
- [ ] Calculate final decomposition confidence conservatively and record the rule-
  and evidence-based explanation.
- [ ] Run collection-level coverage and relationship checks after reconciliation.

**Exit gate:** Results are stable across planning-unit boundaries, cross-file support
is visible, and reconciliation never erases the audit trail.

### Phase 5 — Add currency and existing-bank annotations

- [ ] Detect explicit edition, effective-date, and supersession language in candidate
  evidence and attach a currency flag (the observable portion of D-19).
- [ ] Compare candidates with existing RLO objectives using retrieval followed by a
  scoped semantic comparison.
- [ ] Show exact, possible, and no-match outcomes with existing RLO identity and
  signoff/review metadata when available.
- [ ] Identify a possible refresh when the new source explicitly appears newer.
- [ ] Keep matching advisory during this POC; do not silently suppress a candidate
  or automatically replace an existing RLO.

**Exit gate:** Admins can see potential staleness and existing coverage without the
prototype making an irreversible lifecycle decision.

### Phase 6 — Persist and expose decomposition runs

- [ ] Add idempotent Postgres migrations for versioned runs, unit results, signals,
  candidates, relationships, and admin decisions.
- [ ] Keep large source/extraction artifacts in object storage and operational state
  in Postgres; use Qdrant only for retrieval and similarity workloads.
- [ ] Move compute-heavy decomposition behind the existing worker boundary with
  durable job state, leases, bounded retries, and resumability.
- [ ] Add purpose-specific LiteLLM aliases in `litellm/config.yaml`; keep provider
  model IDs out of application code.
- [ ] Emit Langfuse traces for planning units, signal detection, candidate formation,
  reconciliation, and model usage.
- [ ] Expose APIs for starting a run, polling detailed progress, reading results,
  editing candidates, recording decisions, and resuming failed runs.

**Exit gate:** A failed long-running decomposition resumes from persisted work and
produces the same auditable workspace contract as an uninterrupted run.

### Phase 7 — Build the learning-admin decomposition sandbox

- [ ] Separate extraction inspection from learning-objective decomposition while
  retaining navigation between the two.
- [ ] Show progress by meaningful stage and planning-unit count.
- [ ] Present a scannable candidate inventory with confidence, scope, flags, and
  hierarchy—not only the candidates that passed automated critique.
- [ ] Provide filters for confidence, source, rule/signal, relationship, and review
  status.
- [ ] Let an admin inspect evidence in source context and jump to the original
  page/slide/section.
- [ ] Let an admin edit, split, merge, add, approve for Classification, or reject a
  candidate, with decision history retained.
- [ ] Make Low-confidence, duplicate, supplementary-only, and unresolved candidates
  visually clear without creating heavy approval guardrails.
- [ ] Preserve keyboard access, semantic structure, status announcements, and useful
  text alternatives for visual evidence.

**Exit gate:** A learning admin can understand why every candidate exists, correct
the inventory, and deliberately hand selected candidates to Classification.

### Phase 8 — Verify the vertical slice

- [ ] Add containerized contract, repository, API, worker-resume, and UI tests.
- [ ] Test multi-million-token behavior with generated hierarchical text and fake
  model responses; verify bounded requests, full coverage, and resumability.
- [ ] Add deterministic cases for terminal-outcome-to-enabling-objective
  decomposition, ambiguous candidates, compound splitting, cross-file
  corroboration, supplementary-only evidence, diagrams, duplicate grouping, and
  currency flags.
- [ ] Reuse the coffee example to verify that supporting context can enrich a related
  candidate without automatically expanding the assessment boundary.
- [ ] Run a small human review with one Instructional Designer against representative
  source types and record misses, false positives, and usability observations.
- [ ] Tune prompts and confidence calibration from observed review outcomes; do not
  introduce a stronger-model-as-judge quality harness unless it has a demonstrated
  need.

**Exit gate:** Automated tests prove the observable system guarantees, and one human
review confirms the output is useful enough to proceed to Classification work.

## Explicit non-goals for this feature

- Committing candidates to the final content-type × Bloom-level cell.
- Mapping content to all seven RLO sections.
- Generating practice, assessment, examples, feedback, or transfer content.
- Automatically validating or approving complete RLOs.
- Human validation of Docling extraction quality.
- Multilingual processing or legacy `.ppt` support.
- Production-grade RLO schema migration or reprocessing of prototype RLOs.

## Confirmed direction and remaining open decisions

1. **Candidate limit — confirmed:** Remove the 12-candidate result cap from Layer 1.
   Candidate volume follows the supported practitioner needs found in the source.
   Retain token/output bounds per call, bounded concurrency, and UI pagination, but
   do not impose a total candidate-count limit.
2. **Terminal objectives — confirmed direction:** RLOs contain enabling objectives,
   not broad terminal objectives. Preserve stated terminal objectives as optional
   course/pathway outcome anchors and retain their relationship to the enabling
   objectives produced by decomposition.
3. **Primary versus supplementary sources:** D-15 requires this distinction, but it
   is not reliably inferable in every collection. Recommendation: offer optional
   admin labeling and default unlabeled sources to primary with an inferred flag.
4. **Engagement-time envelope:** A model cannot reliably prove that an objective
   takes 5–15 minutes. Recommendation: treat the estimate as a granularity heuristic
   and reviewer flag, not an automatic rejection rule.
5. **Bank override in D-19:** Automatically suppressing a new candidate assumes a
   mature, current RLO bank and lifecycle policy that the POC does not yet have.
   Recommendation: implement match/refresh annotations now and defer automatic
   override behavior.
6. **Confidence calculation:** Recommendation: let the model propose confidence but
   require structured evidence factors and apply deterministic ceilings, such as
   supplementary-only evidence never exceeding Low.
7. **Classification hint:** Recommendation: carry both content-type and Bloom-level
   hints as optional, independent values with separate rationales. Layer 2 may change
   either one.
8. **Rule-set fidelity:** Some supplied rules combine product policy with proposed
   implementation tactics. Recommendation: version the rule catalog and keep model,
   storage, retrieval, and batching choices in application configuration rather than
   embedding them in the business rules.

## Definition of done

- A new decomposition run can process a small source or a source collection far
  beyond one model context window without truncation.
- Every eligible node is represented in the coverage ledger or has an explicit
  omission reason.
- Every candidate traces through signals to exact, verifiable source locations.
- Low-confidence and problematic candidates remain visible.
- Planning-unit boundaries do not create unexplained duplicates or lost objectives.
- A learning admin can edit and decide candidates in an accessible sandbox.
- Approved candidates cross a versioned contract into Classification.
- The full vertical slice runs and is verified in containers.
