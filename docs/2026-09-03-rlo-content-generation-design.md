# RLO Content Generation Design

## Status

Implemented design for turning an approved enabling objective and its source collection
into one reviewable, source-grounded RLO. This document refines Phases 0–4 of the
[Approved Objective to RLO Generation Plan](2026-09-03-approved-objective-to-rlo-generation-plan.md).

The containerized vertical slice is implemented; representative Instructional
Designer evaluation remains pending.

## Confirmed architecture decisions

1. The approved enabling objective is the fixed instructional contract for one RLO.
2. The seven-part authoring object is the canonical generation and human-review
   artifact.
3. The existing catalog RLO remains the publication/interchange artifact. Code, not
   a second model call, deterministically adapts the authoring object into it.
4. An RLO does not require its own terminal objective. Optional broader-outcome
   context may be retained without defining the assessment boundary.
5. The source collection is the factual boundary. Models may transform supported
   material and create instructional scaffolding, but may not silently introduce
   domain knowledge.
6. Every production prompt is a named, versioned Markdown asset whose exact text,
   input, output, and hash are retained for each operation.
7. Objective approval and completed-RLO approval are the only human gates.

## Responsibility boundary

```text
Approved objective package
        │
        ▼
Target plan ──► evidence retrieval ──► seven-part source map
                                             │
                                             ▼
                                  grounded gap generation
                                             │
                                             ▼
                                  seven-part authoring RLO
                                      │              │
                         deterministic│              │human review
                              adapter ▼              ▼
                                    catalog RLO → publish
```

The model recommends, retrieves, maps, transforms, generates, and critiques. The
application owns identities, ordering, schemas, state transitions, evidence
resolution, prompt provenance, deterministic validation, and publication.

## Input contract

Each RLO generation job starts from an immutable approved objective revision and
source collection snapshot containing:

- approved candidate ID, exact objective statement, and revision;
- preliminary Suggested content kind and Bloom level;
- objective-defining and supporting-context evidence;
- preliminary seven-part source-feature associations;
- practitioner lenses and optional LDS instructions;
- all approved sibling objectives in the batch;
- exact source IDs, versions, checksums, ordered nodes, and visual explanations; and
- versions of the applicable rules and schemas.

The generator may choose a Target classification, but it cannot materially rewrite
the approved objective. A proposed objective change creates a finding and routes back
to objective review.

## Authoring contract

### Top-level `AuthoringRLORevision`

The first implementation should define a strict, versioned contract with these
logical fields:

| Field | Purpose |
| --- | --- |
| `rlo_id`, `version`, `revision` | Application-assigned identity and immutable revision. |
| `objective` | Approved candidate identity and exact enabling-objective statement. |
| `broader_outcome` | Optional source- or LDS-provided context; never required. |
| `classifications` | Suggested, Target, and Observed values with confidence and rationale. |
| `methodology_profile` | Versioned requirements for the Target content-kind × Bloom cell. |
| `sources`, `evidence`, `claims` | Immutable lineage and the factual claim ledger. |
| `parts` | Exactly seven ordered authoring parts. |
| `relationships` | Prerequisite, corequisite, follow-on, and related RLO IDs. |
| `validation` | Deterministic and model-assisted findings plus triage outcome. |
| `provenance` | Rule, prompt, output-contract, model-alias, and operation versions. |

The strict persisted object must use typed fields rather than unrestricted narrative
JSON. Delivery-format markup and learner-specific personalization do not belong in
this contract.

### Shared authoring element

Every substantive or instructional element within a part carries:

| Field | Purpose |
| --- | --- |
| `element_id` | Deterministically assigned stable local ID. |
| `element_type` | Typed role such as `definition`, `step`, `worked_example`, `practice_item`, or `feedback`. |
| `content` | Structured, format-neutral content. |
| `origin` | `source`, `mixed`, or `generated`. |
| `claim_refs` | Claims used by this element. Required for substantive assertions and correct answers. |
| `evidence_refs` | Resolved exact evidence, retained for direct inspection. |
| `generation_note` | For generated/mixed elements, what was created versus transformed. |
| `requirement_refs` | Methodology-profile requirements satisfied by the element. |

Part-level `source_insufficient` is a readiness state, not an element origin.

### Seven ordered parts

1. **Cover** — deterministic identity, objective, classifications, domain, duration,
   source summary, and relationships.
2. **Set-up** — moment-of-need hook, objective presentation, relevance, and required
   prior-knowledge activation.
3. **Teach** — structured source substance needed to perform the objective: facts,
   attributes, steps, decisions, rationale, conditions, or relationships required by
   the Target methodology profile.
4. **Show** — a worked instance with visible expert reasoning, decisions, and outcome.
5. **Practice** — one or more supported opportunities to perform the objective with
   explanatory feedback and appropriate scaffolding.
6. **Check** — criterion-referenced evidence of the exact objective at the intended
   cognitive demand, including correct-answer/rubric support and pass criteria.
7. **Send-off** — retention/transfer prompt, appropriate sibling or follow-on links,
   and a source-supported on-job application cue.

Each part records `complete`, `partial`, `absent`, or `source_insufficient`, plus its
requirements, elements, gaps, and findings. Part status is computed from the
requirements; the model does not set an unexplained status string.

## Classification and methodology

The contract preserves three classifications:

- **Suggested:** discovery-stage hint shown during objective review.
- **Target:** generation plan selected from the approved objective and evidence.
- **Observed:** classification inferred from the completed Teach, Practice, and Check.

Target classification returns a provisional best cell even when confidence is below
Medium. It also returns an escalation flag, alternatives, rationale, and a
discriminator question. This prevents an escalation from becoming an unusable null
classification while preserving uncertainty for final review.

The Target cell points to a versioned methodology profile maintained separately from
prompts. The profile defines required Teach substance, Show structure, Practice and
Check shapes, feedback expectations, and allowed cognitive demand. Prompts receive
the profile as input; changing instructional rules does not require duplicating them
across prompt prose.

The complete 13-cell methodology definitions are a required rules artifact. Until
all cells are available, unsupported cells must be explicit rather than guessed from
neighboring profiles.

## Evidence acquisition and adequacy

Generation does not send an entire large document to one model call. It builds a
bounded evidence packet through reproducible retrieval passes:

1. Retrieve the objective-defining evidence already approved with the candidate.
2. Expand through the source hierarchy to parents, children, and neighboring nodes
   needed to preserve definitions, step order, qualifications, and exceptions.
3. Query separately for every Target methodology requirement rather than searching
   only for words in the objective.
4. Search across every source in the approved collection and include applicable
   table, chart, and image explanations.
5. Challenge every proposed `complete` mapping in a second pass and search for missed
   contradictions, constraints, examples, and assessment-relevant details.
6. Persist selected and rejected evidence IDs, retrieval reasons, and coverage
   results so the map can be reproduced and inspected.

The configured source-tranche limit bounds an individual source input. It does not
cap total document size, total evidence gathered across calls, or the number of
objectives. A compact persisted planning memory carries coverage and claim identities
between tranches.

### Claim ledger

Before prose or activities are generated, source material is normalized into atomic
claims. Each claim contains:

- a deterministic local claim ID;
- a concise statement entailed by the cited source;
- exact evidence and source-version references;
- `objective_defining` or `supporting_context` role;
- applicable objective/methodology requirements;
- qualifications, exceptions, or scope notes; and
- permitted instructional uses.

Supporting context may enrich explanation but cannot establish the correct answer to
a Check item or broaden what the learner is expected to perform.

## Permitted transformation policy

“Do not introduce new facts” does not mean copying source paragraphs. The following
transformations are permitted when the meaning remains entailed by cited claims:

- paraphrase into clearer practitioner language;
- summarize or combine compatible claims;
- reorder content into a teachable sequence while preserving source-required order;
- turn a documented procedure into steps and decision points;
- expose reasoning already supported by rules, criteria, or relationships;
- contrast supported examples, non-examples, and misconceptions; and
- restate supported material as feedback or a correct-answer explanation.

The generator may create instructional scaffolding that is not itself a source fact:

- a hook or transition;
- directions to the learner;
- fictional names and neutral scenario framing;
- a practice interaction structure;
- question wording;
- encouragement and metacognitive prompts; and
- a retrieval or transfer cue.

Scaffolding must be marked `generated`. Any domain proposition needed to interpret a
scenario, choose an answer, score a response, or understand feedback must resolve to
the claim ledger. An invented distractor is allowed only as an explicitly incorrect
option whose corrective feedback is grounded in evidence; it cannot introduce an
unsupported alternative rule.

The following are prohibited:

- supplying missing Teach substance from model memory;
- inventing Deloitte policies, roles, risks, thresholds, or practices;
- treating an inference as a sourced fact when the source does not entail it;
- turning supporting context into an assessment requirement; and
- increasing the objective's scope or cognitive demand to make an activity richer.

When the source cannot support the substantive Teach requirements, generation stops
at a reviewable `source_insufficient` result. It does not hide the gap with fluent
model output.

## Generation operations

Each child job executes and checkpoints these operations:

1. **Plan:** select Target classification and methodology profile; identify likely
   sibling relationships and evidence requirements.
2. **Map:** retrieve evidence, build the claim ledger, map source-native elements,
   identify gaps, and challenge completeness.
3. **Generate Set-up:** construct only missing framing and activation elements.
4. **Generate Teach + Show:** transform supported substance and create a worked
   instance without adding domain claims.
5. **Generate Practice + Check:** construct aligned performances, feedback, answers,
   and rubrics whose decision basis resolves to claims.
6. **Generate Send-off:** create supported retention and workplace-transfer cues.
7. **Assemble:** application code assigns IDs, orders parts, resolves references,
   builds Cover, and creates one strict authoring revision.
8. **Validate:** run deterministic checks, grounding review, pedagogy review, and
   Observed classification.
9. **Repair once:** modify only named model-owned elements, retain the original and
   repair record, and rerun affected validation.
10. **Adapt:** deterministically create the catalog RLO for final review/publication.

Every operation persists before the next begins. Restarting a worker resumes from the
last compatible checkpoint. A prompt, rule, contract, or evidence-version change
invalidates only the affected operation and its downstream artifacts.

## Prompt design

Production assets live under:

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

The README indexes prompt ID, version, operation, LiteLLM alias, and output contract,
matching the existing objective-extraction pattern. The loader must support prompt
subdirectories without adding a second prompt-loading convention.

Every prompt must explicitly state:

- source text is untrusted data, never instructions;
- the approved objective and methodology profile are constraints;
- source claims are the exclusive domain-fact boundary;
- the exact allowed/prohibited transformation policy;
- required structured output and evidence/claim references; and
- that missing support must be reported rather than repaired from model knowledge.

Rules that can be deterministic—IDs, required fields, statuses, reference integrity,
ordering, and allowed enum values—belong in contracts and validators, not prompt
prose alone.

Each operation record retains the exact prompt text and SHA-256 hash, prompt ID and
version, structured input, structured output, output-contract version, LiteLLM alias,
token usage, timestamps, and any repair ancestry. The POC sandbox should expose these
records so a developer or Instructional Designer can inspect what the model saw and
change the relevant Markdown asset intentionally.

## Validation

### Deterministic

- objective identity and wording match the approved package;
- seven parts exist once and in order;
- required fields and methodology requirements are addressed or explicitly missing;
- source, evidence, claim, element, assessment, and relationship references resolve;
- substantive elements and correct-answer logic have claim/evidence support;
- supporting-context claims are not the sole basis of assessment answers;
- generated elements carry origin and generation notes;
- Cover values match application-owned metadata;
- the catalog adapter produces stable IDs and valid cross-references; and
- prompt/input/output provenance is complete.

### Model-assisted

- each transformed statement remains entailed by its evidence;
- examples do not smuggle in unsupported domain assumptions;
- Teach adequately supports the approved performance;
- Show exposes the appropriate expert reasoning;
- Practice and Check perform the objective at the intended level;
- feedback explains answers without adding unsupported rules;
- Target and Observed classifications align; and
- the assembled object is appropriately atomic for roughly 5–15 minutes.

Model-assisted findings are visible judgments, not mathematical proof. One bounded
repair may address explicit repairable findings. Source insufficiency, objective
changes, and uncertain business rules require human/source action rather than repair.

## Deterministic catalog adapter

The adapter should use one documented mapping:

| Authoring object | Existing catalog RLO |
| --- | --- |
| Approved objective + Observed Bloom | `enabling_objective` |
| Claim ledger and Teach atoms | `concepts` and `evidence` |
| Set-up, Teach, Show, Send-off elements | typed `components` |
| Practice and Check items | components and `assessment_items` as appropriate |
| Seven-part instructional roles | `gagne_event_mapping` |
| Target methodology and planning | `design_brief` and `authoring_rationale` |
| Relationships | prerequisite/corequisite/follow-on/related fields |
| Immutable sources | `sources` and `evidence` |

The catalog schema must make `terminal_objective` optional and update Gagné mapping
validation so it never assumes that field exists. Prototype fixtures may be updated
or discarded; no migration compatibility layer is required for them.

The adapter must not discard authoring provenance. The catalog record should retain
the authoring revision identity so the seven-part object, prompts, evidence map, and
validation history remain retrievable during audit or reprocessing.

## First implementation slice

The narrowest useful vertical slice is one approved objective with one or more
sources and one RLO:

- define strict authoring, classification, claim, attribution, and part contracts;
- implement one methodology profile already supported by available rules;
- create a hand-authored fixture and deterministic catalog adapter;
- add deterministic validation for identity, ordering, references, and attribution;
- add the named prompt index and target/mapping prompt assets;
- create a durable child job through planning and source mapping;
- expose its operation records and seven-part gap map in the sandbox; and
- stop before generation until the evidence map is reproducible and inspectable.

This proves the factual boundary and schema handoff before model-generated instruction
is introduced. The next slice adds Teach + Show, then Practice + Check, followed by
the remaining framing, semantic validation, repair, and final review UI.

## Remaining product confirmations

1. When Teach is source-insufficient, may an Instructional Designer attach another
   approved source and resume the same RLO job? The recommended answer is yes, with a
   new immutable source-map revision.
2. Should final POC approval publish immediately? The recommended answer is one
   **Approve and publish** action, with revision history retained.
