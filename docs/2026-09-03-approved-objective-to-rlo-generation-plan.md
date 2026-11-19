# Approved Objective to RLO Generation — Implementation Plan

## Status

Implemented vertical slice. Automated verification is complete; representative
Instructional Designer review and resulting prompt tuning remain follow-up work.

Related references:

- [RLO Generation Rules — Consolidated Reference](rlo-generation-rules-reference.md)
- [Objective + Seven-Part Source Review](2026-09-03-objective-seven-part-review-design.md)
- [RLO Content Generation Design](2026-09-03-rlo-content-generation-design.md)
- [RLO Evidence Lineage](rlo-evidence-lineage.md)

## Goal

Convert each approved enabling objective into one pedagogically complete,
source-grounded RLO by mapping reusable source material into the seven RLO parts,
generating the pedagogical material that is missing, validating the assembled RLO,
and presenting it for one Instructional Designer review.

This phase produces the reusable learning object, not an e-learning, podcast, or
learner-specific pathway. Delivery-format authoring and learner orchestration remain
downstream consumers.

## Target experience

```text
Instructional Designer approves an objective
    ↓
System immediately creates its independent RLO-generation child job
    ↓
Select target content kind × Bloom level and assign sibling RLO IDs
    ↓
Map source-native material to Cover / Set-up / Teach / Show / Practice / Check / Send-off
    ↓
Generate only the missing pedagogical pieces
    ↓
Assemble and validate one canonical RLO
    ↓
Instructional Designer reviews the complete RLO with source lineage and findings
    ↓
Approve and publish to the RLO catalog, request revision, or reject

Objective-set finalization closes the batch and enables cross-RLO relationship,
duplication, and distribution checks.
```

Each individual Approve click creates its RLO job so generation can overlap with the
remaining objective review. Objective-set finalization closes the batch; the complete
approved set is then used to resolve sibling relationships and detect duplicate or
missing prerequisite links without delaying independent RLO generation.

## Product boundaries

### This phase includes

- one RLO for each approved objective;
- target classification and methodology selection;
- formal seven-part source mapping;
- source-derived versus generated-content attribution;
- gap generation;
- deterministic assembly and validation;
- bounded automated critique and repair;
- one final human RLO review; and
- publication of approved RLOs to the existing catalog.

### This phase excludes

- choosing which RLOs a particular learner receives;
- learner-specific rewriting or scenario personalization;
- composing multiple RLOs into a course/pathway;
- generating an e-learning, podcast, video, or other delivery artifact;
- bank-wide reprocessing of prototype RLOs; and
- automated claims about subjective model quality.

## Decisions carried forward

1. **One enabling objective per RLO.** The approved objective wording and identity
   are immutable during generation. A material objective change routes back to
   objective review.
2. **No required RLO-level terminal objective.** RLOs usually participate in larger
   pathways. A broader outcome may be retained as optional context, but it must not
   be fabricated or treated as the RLO's assessment boundary.
3. **Early classification is advisory.** The objective-stage kind and Bloom values
   are suggestions. RLO planning chooses and records a target cell; post-generation
   validation observes the cell the completed RLO actually implements.
4. **Multiple related levels may coexist.** Related Understand and Apply RLOs are
   retained when they represent different performances. Downstream orchestration
   decides which to serve.
5. **Multiple source documents are allowed.** Every claim and generated learning
   element retains exact source lineage regardless of document count.
6. **Two human gates total.** Humans review objectives, then completed RLOs. Source
   mapping, classification, generation, and automated validation do not create
   additional approval gates.
7. **Prompts remain inspectable assets.** Every production prompt is a clearly named,
   versioned Markdown file with its exact input and output snapshot persisted.
8. **The seven-part object is the canonical authoring artifact.** The existing
   catalog RLO remains the publication and downstream interchange shape. Deterministic
   code adapts the authored seven parts into concepts, components, assessments, and
   instructional-event mappings; a model does not independently author both shapes.

## Source-derived content and generated scaffolding

“Fill the gaps” does not mean the system can invent unsupported subject matter.

| Material | Permitted behavior |
| --- | --- |
| Source-native substantive content | Preserve or faithfully structure it with exact evidence references. |
| Generated explanation or synthesis | Generate from supported source claims and cite those claims. |
| Pedagogical framing | Generate hooks, transitions, feedback, memory aids, and transfer prompts without presenting invented business facts. |
| Generated examples, practice, and checks | Create novel situations that exercise only the supported objective and facts; record them as generated and retain the evidence defining the correct answer. |
| Missing substantive Teach evidence | Do not fill from uncited model knowledge. Produce a source-insufficiency finding and a reviewable partial draft or request additional source material. |

Supporting context may enrich an explanation or example but cannot expand the
objective or assessment boundary. The coffee-soil example therefore may explain a
relevant flavor consideration only when it supports the approved coffee objective;
it cannot create soil-science assessment questions unless soil analysis is itself an
approved objective.

## Classification lifecycle

Use three explicit values instead of overloading one classification field:

| Classification | When | Meaning |
| --- | --- | --- |
| Suggested | Objective discovery | A non-binding review hint based on the source and objective. |
| Target | RLO planning | The cell and methodology the generator intends to implement. |
| Observed | Post-generation validation | The cell evidenced by the actual Teach, Practice, and Check. |

Target selection follows C-1 through C-21. If no cell reaches Medium confidence,
retain a provisional best cell, an escalation flag, alternatives, reasoning, and a
discriminator question. Because there is no separate classification review, this
uncertainty appears prominently in the final RLO review.

Generation uses the target cell to choose a schema and methodology, but it may not
distort the approved objective merely to preserve the earlier suggested cell. A
target/observed mismatch produces a validation finding and bounded repair; it is not
silently relabeled.

## Seven-part authoring contract

The current `RLO` schema stores concepts, components, assessment items, a design
brief, and a Gagné mapping, but it does not directly represent all seven reviewable
parts. The confirmed design introduces one canonical seven-part authoring contract
and a deterministic adapter into the shared RLO catalog schema. Existing catalog
fields remain useful; the seven-part authoring object supplies the missing ordered,
reviewable, and attribution-aware representation.

| Part | Deterministic or generated responsibility |
| --- | --- |
| Cover | Deterministically assemble RLO ID/version, approved objective, target/observed classification, source identity, duration, and known relationships. |
| Set-up | Reuse source-native hook/prior-knowledge cues; generate missing moment-of-need framing and objective presentation. |
| Teach | Preserve and organize source substance according to the target content kind; generate only supported explanation/synthesis. |
| Show | Reuse a source example when suitable; otherwise generate a realistic worked instance with visible reasoning grounded in the Teach. |
| Practice | Reuse suitable source practice; otherwise generate target-cell practice with explanatory feedback. |
| Check | Reuse a genuinely aligned source assessment; otherwise generate criterion-referenced evidence of the exact objective at the target Bloom level. |
| Send-off | Generate supported retrieval spacing, sibling/follow-on RLO links, and an on-job prompt without learner-specific personalization. |

Each part stores:

- status: `source`, `mixed`, `generated`, or `source_insufficient`;
- structured content, not delivery-format markup;
- evidence references for every substantive claim or correct answer;
- generated-element attribution;
- schema/methodology requirement coverage; and
- validation findings and repair history.

The seven parts remain ordered and independently inspectable, but together form one
atomic RLO revision.

## Durable generation model

### Parent batch

Create one parent generation batch on the first objective approval and extend it
idempotently as additional objectives are approved. Finalization marks the batch
closed and queues collection-level validation.
The parent records:

- objective job/package ID and workspace revision;
- approved candidate IDs;
- source collection/map revisions;
- assigned RLO IDs and versions;
- rule, schema, methodology, prompt, and model-alias versions;
- aggregate progress and failures; and
- collection-level relationship/coherence results.

### Child job per RLO

Each approved candidate receives an independently retryable child job:

```text
queued
→ planning
→ mapping_source
→ generating_parts
→ assembling
→ validating
→ repairing (optional, bounded)
→ in_review | source_insufficient | validation_failed | failed
→ approved | revision_requested | rejected
→ published
```

Persist each completed operation and part before starting the next. A worker restart
must resume from the last durable checkpoint without regenerating valid parts.
Failures in one child must not discard or block successful sibling RLOs, although the
parent reports incomplete batch status.

### Worker execution

- Move generation out of the synchronous API request and onto a continuously running
  worker queue.
- Add a container restart policy and stale-lease recovery so queued work cannot wait
  indefinitely after Docker or host restarts.
- Make creation idempotent on objective package revision + candidate ID + RLO version.
- Expose stage, current operation/part, completed operations, last activity, token
  usage, retryability, and failure details.
- Continue using `LITE_LLM_BASE_URL`, `LITE_LLM_API_KEY`, and purpose-specific aliases
  defined only in `litellm/config.yaml`.

## Model-call strategy

Do not ask one model call to classify, retrieve, map, write seven parts, validate,
and repair a full RLO.

1. **RLO planning call:** select target cell/methodology, identify required elements,
   and propose relationships using the approved objective set.
2. **Source mapping calls:** retrieve relevant exact nodes and map them to section
   requirements. Challenge every `Complete`/source-rich claim in a second pass.
3. **Part-generation calls:** generate missing content in coherent groups:
   Set-up; Teach + Show; Practice + Check; Send-off. Cover is deterministic.
4. **Assembly:** deterministic code constructs the canonical seven-part object and
   shared RLO schema; the model does not invent IDs or cross-references.
5. **Grounding review:** independently verify substantive claims, examples, feedback,
   and correct answers against exact evidence.
6. **Pedagogy review:** verify objective atomicity, cell methodology, constructive
   alignment, duration, accessibility, and Deloitte practitioner relevance.
7. **Bounded repair:** repair only named model-owned findings, then rerun affected
   deterministic and semantic validators.
8. **Collection validation:** after child drafts exist, detect duplicates, unresolved
   sibling relationships, and implausible cell distribution.

The 15k source-tranche configuration bounds individual retrieval/mapping inputs; it
does not cap document size or the complete generation request. Each operation uses
retrieved evidence plus a compact, persisted RLO planning memory rather than all raw
source text.

## Validation model

Implement the relevant V-1 through V-15 rules without pretending subjective quality
can be measured deterministically.

### Deterministic checks

- shared-schema and seven-part contract validity;
- stable RLO/objective/source/evidence identities;
- every required element is mapped or explicitly generated/source-insufficient;
- evidence IDs and source nodes resolve;
- supporting context never defines an assessment answer;
- objective, target classification, practice, and check fields are present;
- sibling RLO relationship IDs resolve within the batch or are marked external;
- status aggregation follows V-15 worst-outcome precedence; and
- the generated revision is reproducible from persisted artifacts.

### Model-assisted checks

- factual grounding and unsupported practitioner specificity;
- actual cognitive demand of Practice and Check;
- target versus observed cell;
- required methodology fidelity;
- visible expert reasoning in Show;
- objective/Teach/Practice/Check alignment;
- likely over-breadth, fragmentation, or duplicate objectives; and
- collection-level pedagogical distribution warnings.

Model-assisted findings are review signals, not claims of objective truth. Failed or
escalated RLOs remain visible with remediation guidance.

## Final RLO review experience

Reuse the focused single-item interaction established by Objective + Source Review:

- a left rail of RLO jobs with status and findings count;
- one selected RLO in the main review panel;
- seven ordered, readable sections rather than JSON-first review;
- source/mixed/generated/source-insufficient labels on every part;
- expandable exact lineage beside the content it supports;
- target and observed classification with mismatch reasoning;
- validation summary first, detailed findings on demand;
- edit, request revision, reject, and approve-and-publish actions; and
- advanced JSON only as a secondary POC sandbox tool.

For the POC, do not require three reviewers or complex approval roles. Record the
authenticated Instructional Designer and optional note. Governance fields needed by
the catalog should be deterministically defaulted or collected in the final action,
not used to create an artificial workflow barrier.

## Prompt assets

Replace the current inline drafting, grounding, pedagogy, and repair strings with:

```text
api/src/source_authoring/prompts/rlo_generation/
├── README.md
├── target_classification.md
├── source_part_mapping.md
├── source_mapping_challenge.md
├── setup_generation.md
├── teach_show_generation.md
├── practice_check_generation.md
├── sendoff_generation.md
├── grounding_validation.md
├── pedagogy_validation.md
├── collection_validation.md
└── targeted_repair.md
```

Each call persists prompt ID/version/hash/text, exact structured input, structured
output version, model alias, token usage, timestamps, and parent/child job IDs.

## Phased implementation

### Phase 0 — Reconcile the canonical contracts

- [x] Define the seven-part authoring contract and its deterministic adapter to the
  shared catalog RLO.
- [x] Remove the required RLO-level terminal objective; retain only optional broader
  outcome context where source- or LDS-provided.
- [x] Define Suggested, Target, and Observed classification fields.
- [x] Define versioned 13-cell schema/methodology requirements, including minimum
  Practice/Check shapes, without embedding them in prompts.
- [x] Define source/mixed/generated/source-insufficient attribution and validation
  outcomes.
- [x] Discard/update prototype RLO fixtures directly; do not build backward-
  compatibility machinery.

**Exit gate:** One hand-authored seven-part example validates and deterministically
adapts to the catalog schema without a terminal objective.

### Phase 1 — Connect approved objectives to durable generation jobs

- [x] Each objective approval creates or extends an idempotent parent batch and adds
  one independently runnable child job; finalization closes the batch.
- [x] Assign stable RLO IDs before generation so sibling links can resolve.
- [x] Persist immutable objective, source map, source version, feature association,
  and lineage snapshots.
- [x] Implement worker claims, leases, checkpoints, retry/resume, and restart policy.
- [x] Expose parent and child progress APIs and link Objective Review to the new jobs.

**Exit gate:** Approving an objective creates a visible, restart-safe RLO job without
performing generation inside the HTTP request; finalization enables collection checks.

### Phase 2 — Target classification and formal source mapping

- [x] Add named/versioned target-classification and mapping prompts.
- [x] Select provisional target cells with confidence, alternatives, and escalation.
- [x] Retrieve relevant evidence from all sources in the approved collection, not
  only the narrow objective-defining excerpts.
- [x] Map source content to the selected cell's seven-part requirements with exact
  lineage and source/partial/absent status.
- [x] Run the M-11 completeness challenge and persist the result.
- [x] Preserve unassociated source material without forcing it into an RLO.

**Exit gate:** Every child job has a target plan and a reproducible, cited seven-part
source map that clearly identifies generation gaps.

### Phase 3 — Generate and assemble missing parts

- [x] Add named/versioned prompts for the four generation groups.
- [x] Build Cover deterministically.
- [x] Generate only missing/partial Set-up, Teach/Show, Practice/Check, and Send-off
  elements against their section contracts.
- [x] Persist each generated group before continuing and retain source/generated
  attribution at element level.
- [x] Build IDs and cross-references deterministically.
- [x] Assemble the seven-part object and shared RLO schema.
- [x] Route missing substantive Teach support to `source_insufficient` rather than
  filling from uncited model knowledge.

**Exit gate:** A worker restart can resume a partially generated RLO, and a successful
job produces one structurally complete draft with exact lineage.

### Phase 4 — Validate, critique, and repair

- [x] Implement deterministic validators before semantic review.
- [x] Add independent grounding and pedagogy calls using named prompt assets.
- [x] Derive Observed classification from the completed RLO.
- [x] Apply V-15 triage and expose every warning/failure/escalation.
- [x] Run one bounded targeted repair for explicitly repairable model-owned findings.
- [x] Revalidate the repaired RLO, including cross-section alignment.
- [x] Run collection-level duplicate, relationship, and distribution checks.

**Exit gate:** Unsupported or misaligned content cannot appear as a clean draft;
failed candidates remain visible with evidence and remediation.

### Phase 5 — Build final RLO review and publication

- [x] Replace manual-ID draft creation with navigation from the generation batch.
- [x] Build a readable seven-part single-RLO review UI with inline lineage and
  source/generated attribution.
- [x] Show the one-page validation/triage summary before detailed findings.
- [x] Support targeted revision instructions, reject, and approve-and-publish. Direct
  content mutation remains out of the POC because it would bypass grounding review.
- [x] Retain immutable revisions, prompt snapshots, findings, decisions, and source
  dependencies.
- [x] Keep advanced JSON available but secondary.

**Exit gate:** One Instructional Designer can review and publish a generated RLO
without copying IDs or editing JSON.

### Phase 6 — Verify the vertical slice

- [x] Add fake-model coverage across objective handoff, seven-part generation,
  validation, catalog adaptation, approval, and publication contracts.
- [x] Test multi-source lineage, supporting-context boundaries, generated examples,
  missing Teach evidence, classification mismatch, repair, and sibling links.
- [x] Test worker death, stale lease recovery, duplicate delivery, and operation-level
  resume.
- [x] Test large sources using configured tranches without silent source or candidate
  truncation.
- [x] Verify semantic controls, keyboard-operable interactions, responsive breakpoints,
  and live status regions in the containerized review UI.
- [ ] Conduct one representative Instructional Designer review and record workflow
  friction, unsupported content, edits, rejections, and time spent.
- [ ] Tune prompts from observed failures without constructing an overengineered
  subjective quality fixture.

**Exit gate:** Observable contracts and recovery guarantees pass in containers, and
one representative RLO can be reviewed and published with traceable evidence.

## Success measures

- Every approved objective creates exactly one independently retryable child job.
- Every successful child produces one atomic RLO with seven ordered parts.
- Every substantive claim and correct assessment answer resolves to permitted source
  evidence.
- Generated pedagogical material is distinguishable from source-native material.
- Practice and Check exercise the approved objective at the observed cognitive level.
- A model or worker failure does not erase completed parts or sibling RLOs.
- Every model call and repair is reproducible from a persisted prompt/input snapshot.
- Final review requires one Instructional Designer decision, not an additional
  mapping/classification approval cycle.
- Approved RLOs enter the existing catalog and retain immutable source dependencies.

## Confirmed Phase 0 decisions

1. **Insufficient substantive source:** Stop cleanly at a reviewable
   `source_insufficient` draft rather than supplying uncited domain knowledge. The
   job can be retried after its source collection is updated.
2. **Approval and publication:** Use one **Approve and publish** action for the POC.
