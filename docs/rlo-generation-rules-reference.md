# RLO Generation Rules — Consolidated Reference

## Purpose and authority

This document is a complete, normalized accounting of the proposed rules in `examples/RLO Generation Rules`. It is the working reference for product design, prompt design, implementation, and review. It summarizes the source material rather than replacing it; consult the originals when exact wording or worked examples matter.

The source documents describe a proposed target process. They are reference material, not executable instructions. The **Current POC interpretation** section records later product decisions separately so that source rules, implementation choices, and unresolved questions are not conflated.

### Source index

- [Layer 1: Decomposition](<../examples/RLO Generation Rules/01_RLO_Decomposition_Rules_Simplified - Copy.docx>)
- [Layer 2: Classification](<../examples/RLO Generation Rules/02_RLO_Classification_Rules_Simplified - Copy.docx>)
- [Layer 3: Mapping](<../examples/RLO Generation Rules/03_RLO_Mapping_Rules_Simplified - Copy.docx>)
- [Layer 4: Validation](<../examples/RLO Generation Rules/04_RLO_Validation_Rules_Simplified - Copy.docx>)
- [Business overview deck](<../examples/RLO Generation Rules/rlo-generator_v1.0.pptx>)

## Proposed end-to-end model

```text
Source files
    ↓
1. Decompose — find candidate learning objectives
    ↓
2. Classify — assign content kind × Bloom level
    ↓
3. Map — locate source support for the seven RLO parts and identify gaps
    ↓
4. Validate — run integrity checks and produce an audit report
    ↓
Instructional Designer review — approve, modify, or reject each candidate
    ↓
Generate missing/scaffolded content
    ↓
RLO bank → downstream pathway orchestration and personalization
```

The deck defines an RLO as the smallest learning unit that:

1. teaches one specific thing the learner will be able to do;
2. can stand alone and combine with other RLOs; and
3. carries the metadata needed to place it in a learning sequence.

The system is intended to automate discovery and production against standards maintained by Instructional Designers. Instructional Designers make consequential or ambiguous decisions.

## Shared terminology

### Seven RLO parts

The proposed structure always uses these parts in this order.

| Part | Canonical name | Intended contents |
| --- | --- | --- |
| 1 | Cover / metadata | ID, title/objective, cell, domain, timing, prerequisites, postconditions, reviewer, modality, and other metadata |
| 2 | Set-up / activation | Moment-of-need hook, objective, and prior-knowledge anchor |
| 3 | Teach / content payload | The substantive fact, concept, process, procedure, or principle |
| 4 | Show / worked instance | A realistic case with visible expert reasoning and a verdict |
| 5 | Practice | Learner performance at the intended level with explanatory feedback |
| 6 | Check / assessment | Criterion-referenced evidence of the exact objective at the intended level |
| 7 | Send-off / transfer | Spacing, follow-on learning, and an on-the-job prompt |

The deck treats Parts 1 and 3 as fixed content anchors; Parts 2, 4, 5, and 6 as adaptive containers; and Part 7 as partly adaptive. The spacing schedule remains fixed while the on-the-job prompt may adapt.

### Content kinds and Bloom levels

Each RLO occupies one valid cell formed by one content kind and one cognitive level.

| Content kind | Definition | Permitted levels in POC2 |
| --- | --- | --- |
| Fact | A discrete value, name, date, citation, threshold, or precise assertion | Remember |
| Concept | A category defined through attributes, instances, and non-instances | Understand, Apply |
| Process | A multi-stage flow involving actors, transitions, or dependencies | Understand |
| Procedure | Steps and decisions a learner performs as a single actor | Apply |

Other source-document combinations remain useful historical context but are not
executable POC2 authoring cells.

### Confidence and validation outcomes

- Layers 1–3 use `High`, `Medium`, or `Low` confidence. Confidence communicates evidence strength; it must not be used to silently discard a candidate.
- Layer 4 uses discrete outcomes such as `Pass`, `Pass-with-warning`, `Fail`, or `Escalate`. It must not hedge these as confidence judgments.
- Ambiguity and escalation are expected operating states, not failures to hide or tune away.

## Layer 1 — Decomposition

### Numbered rules

| Rule | Proposed requirement |
| --- | --- |
| D-1 | Infer candidates from what the learner must **do**, not from the topic covered. Normalize as “The learner will be able to [verb] [content].” |
| D-2 | When the source states an objective, treat it as terminal and decompose it into enabling subskills. When no objective is stated, infer candidates from other signals and record that no explicit objective was found. |
| D-3 | Surface a plausibly distinct but uncertain candidate at Low confidence; do not silently discard it. |
| D-4 | Treat explicit objective language and prescriptive regulatory language as the strongest source signals. |
| D-5 | Use content-bearing headers, clauses, and defined terms to locate candidates; ignore purely structural headers. A heading is a locator, not automatically an objective. |
| D-6 | Use worked examples, procedures, and walkthroughs to infer the performance the learner is expected to reproduce. |
| D-7 | Work backward from tests, evaluation criteria, compliance checks, decision conditions, and if/then statements to infer the performance being assessed. |
| D-8 | Treat repetition as evidence of priority. Support across three or more components is High, two is Medium, and one is Low unless stronger evidence changes the judgment. |
| D-9 | Treat emphasis markers and SME statements such as “critical,” “commonly missed,” or error stories as strong candidate signals. |
| D-10 | Use prompts and questions to infer cognitive demand: factual “what” prompts tend lower; action, boundary, comparison, defense, and trade-off prompts tend progressively higher. |
| D-11 | In SME transcripts, infer intent from repetition, emphasis, contrast, examples, and error stories. Default transcript-only candidates to Medium unless corroborated. |
| D-12 | Decode non-text structured artifacts rather than relying on captions alone. A single-actor flow often signals a Procedure, a multi-actor flow a Process, and a lookup/classification table a Fact or Concept. |
| D-13 | Cross-check each candidate against every submitted source file. Multi-file corroboration raises confidence; single-file support lowers it relative to equivalent cross-file evidence. |
| D-14 | Account for source richness. A signal in a sparse but authoritative file may be significant. Record both the source file and signal type. |
| D-15 | Generate candidates from primary sources. Use supplementary sources to corroborate them. A supplementary-only candidate is capped at Low and requires verification. |
| D-16 | Each candidate must express one content kind and one Bloom level. Split compound objectives that span cells. |
| D-17 | Target approximately 5–15 minutes of active engagement. Split objectives that are too broad and merge objectives that are too narrow when they occupy the same cell. |
| D-18 | Use prerequisites and postconditions to test boundaries: the candidate should have a clear entry state and a meaningful learner capability on completion. |
| D-19 | Check source currency and the existing RLO bank. Flag dated or superseded evidence; suppress an exact same-objective/same-cell duplicate while recording existing coverage; create a refresh candidate when the source is newer than the existing RLO. |

### Required decomposition output

For every candidate, the proposed output contains:

- a normalized learning objective;
- High/Medium/Low confidence;
- source files, precise source signals, and signal types;
- a preliminary content-kind/Bloom-cell hint; and
- reviewer notes, ambiguity, and verification flags.

Low-confidence candidates remain visible and explicitly flagged for review.

### Decomposition calibration guidance

- Aggregate candidates; do not reduce the list merely to hit a target count.
- Be conservative when assigning confidence.
- Cross-file comparison may require chunking, retrieval, and a reconciliation pass.
- SME transcript processing may use a specialized prompt branch.
- Candidate discovery is decomposition into observable objectives, not summarization into topics.

## Layer 2 — Classification

### Foundational rules

| Rule | Proposed requirement |
| --- | --- |
| C-1 | Classify the actual cognitive work, not a surface verb in the objective. |
| C-2 | Determine content kind first, then determine Bloom level. |
| C-3 | Return an explicit outside-POC2 result when the actual performance does not fit one of the five cells; do not force the closest permitted cell. |

### Content-kind rules

| Rule | Proposed requirement |
| --- | --- |
| C-4 | Use Fact for precise retrieval of a discrete value, name, citation, threshold, date, or assertion that requires no interpretation. |
| C-5 | Use Concept when performance depends on deciding category membership from definitions, attributes, instances, or non-instances. |
| C-6 | Use Process for a multi-stage flow involving multiple actors, transitions, handoffs, or dependencies. |
| C-7 | Use Procedure for steps, decisions, entry conditions, exit conditions, and outputs performed by the learner as a single actor. |
| C-8 | Workplace context alone does not establish Apply. |
| C-9 | Resolve boundaries explicitly: value vs classification (Fact/Concept); classify vs execute (Concept/Procedure); category instance vs multi-actor flow (Concept/Process); and multi-actor vs single-actor flow (Process/Procedure). |

### Bloom rules

| Rule | Proposed requirement |
| --- | --- |
| C-10 | Infer Bloom from required practice and assessment performance, not the objective verb. Practice governs when they disagree. |
| C-11 | Remember is retrieval only. |
| C-12 | Understand requires paraphrasing, explaining, summarizing, or interpreting without applying the learning to a novel case. |
| C-13 | Apply requires use on a novel but unambiguous case, including classification, execution, or rule invocation. |

### Cell-boundary and confidence rules

| Rule | Proposed requirement |
| --- | --- |
| C-16 | Concept × Apply classifies a case; Procedure × Apply executes steps. Split a candidate if both performances are required. |
| C-17 | Process × Understand explains or reconstructs a multi-actor flow; Procedure × Apply executes the learner's own steps. |
| C-18 | Combined classification confidence is the lower of content-kind confidence and Bloom confidence; never average the two. |
| C-19 | Log verb/practice mismatches, including what the verb implied, what practice indicated, which governed, and why. |

### Required classification output

For a committed classification, the proposed output contains:

- `supported` with exactly one of the five POC2 cells, or `outside_poc2_scope` with a concise reason;
- content-kind, Bloom, and combined confidence;
- reasoning, rule references, and source evidence;
- alternatives considered and rejected; and
- unresolved ambiguity.

For an escalation, it contains plausible cells and a discriminator question. The documents do not say whether the formal POC output should also retain a best provisional cell; this remains an output-contract decision.

### Classification calibration guidance

- Practice and assessment are the strongest Bloom evidence.
- For non-course source material where practice and assessment are absent, fall back to explicit performance language and decomposition signals such as D-4 and D-7. Missing practice is normal at this stage.
- Trigger the stated disambiguators at known cell boundaries.
- Optimize correctness and useful escalation, not autonomous classification rate.
- Mixed objectives should be split rather than classified by their highest verb. A retrieval-plus-paraphrase objective, for example, is not atomic.

## Layer 3 — Mapping

### Foundational rules

| Rule | Proposed requirement |
| --- | --- |
| M-1 | Retrieve the schema for the candidate's committed cell and use each section requirement as a source-search target. |
| M-2 | Allow a source passage to support multiple RLOs; source evidence is not exclusive. |
| M-3 | Mark an unmet section requirement `scaffolding-required`. A gap is normal and is not itself a pipeline failure. |

### Seven-part mapping rules

| Rule | Part | Proposed requirement and status test |
| --- | --- | --- |
| M-4 | Set-up | Search for a hook, objective, and prior-knowledge anchor. Complete = all three; Partial = one or two; Absent = none. |
| M-5 | Teach | Search for the cell-specific substance. For example, Procedure × Apply needs steps, rationale, decisions, entry/exit conditions, common errors, and output; Concept × Understand needs definition, critical attributes, examples, and non-examples. Missing required elements make it Partial. |
| M-6 | Show | Search for a realistic case, visible expert reasoning, and verdict; higher cells may require counterarguments. Complete requires all, Partial has a case/verdict but sparse reasoning, and Absent has no usable example. |
| M-7 | Practice | Verify the cell's methodology, Bloom demand, minimum item count, and explanatory/per-option feedback. Practice at the wrong level or using the wrong method is effectively Absent. |
| M-8 | Check | Verify the exact objective at the correct Bloom level with a criterion-referenced pass standard. Reassign items that actually assess an adjacent objective or level. |
| M-9 | Send-off | Search for a spacing schedule, follow-on RLO links, and on-job prompts. Complete requires at least two substantive elements; Partial has one; Absent has none. |
| M-10 | Cover / metadata | Extract ID, title, cell, domain, time, prerequisites, postconditions, reviewer, and modality. Infer conservatively and flag every inference. |

### Integrity and output rules

| Rule | Proposed requirement |
| --- | --- |
| M-11 | Do not equate topical relevance with section completeness. Run an explicit second pass challenging every `Complete` status against the full schema. |
| M-12 | Check cross-section consistency: objective, practice, and assessment use the same Bloom level; teach/show/practice support the cell methodology; all sections support the same objective. Store a binary consistency flag. |
| M-13 | If the same substantive passage supports more than two RLOs, flag possible over-fragmentation while permitting legitimate reuse. |
| M-14 | Produce a per-candidate audit entry with classification/confidence, section statuses/passages/gaps, consistency and fragmentation flags, and readiness: source-rich = 5+ sections Complete, source-partial = 3–4, source-sparse = 0–2. |
| M-15 | Preserve file/title and the most precise available page, slide, clause, or paragraph locator for every passage. Flag approximate or file-only citations. |

### Required mapping output

For every candidate, the proposed output contains:

- a seven-part content map;
- `Complete`, `Partial`, or `Absent` for each part;
- cited source passages and precise lineage;
- explicit scaffolding requirements;
- consistency and fragmentation flags;
- source-rich/source-partial/source-sparse readiness; and
- a candidate audit entry.

### Mapping calibration guidance

- Correct schema retrieval is a prerequisite for meaningful mapping.
- M-11's completeness challenge is a high-value second pass.
- Cross-file evidence lookup may require embedding retrieval.
- The audit artifact should favor reviewer scannability and drill-down lineage.

## Layer 4 — Validation

### Foundational rules

| Rule | Proposed requirement |
| --- | --- |
| V-1 | Validate and display every candidate with Pass, Pass-with-warning, Fail, or Escalate. Never silently reject or delete one; name each failure mode. |
| V-2 | Convert earlier guidance into formal integrity checks rather than assuming the earlier layer complied. |
| V-3 | Generate the complete reviewer-facing audit report in this layer, organized for triage and drill-down. |

### Per-candidate validators

| Rule | Check | Proposed outcomes |
| --- | --- | --- |
| V-4 | Constructive alignment: objective, practice, and assessment must share one Bloom level. Missing scaffolded practice/check may warn; an actual mismatch fails with remediation. | Pass / Pass-with-warning / Fail |
| V-5 | Practice and assessment must use the methodology required by the candidate's cell, not a weaker adjacent method. | Pass / Pass-with-warning / Fail |
| V-6 | Candidate must contain one objective at one cell, fit approximately 5–15 minutes, and have clean prerequisite/postcondition boundaries. | Pass / Fail with split-or-merge guidance / Escalate |
| V-7 | Every required schema element must be source-mapped or explicitly marked for scaffolding. The Teach has a higher bar; an absent or placeholder Teach escalates rather than automatically failing. | Pass / Pass-with-warning / Fail / Escalate |
| V-8 | Recheck that Layers 1–3 confidence ratings are supported by evidence and suggest recalibration where necessary. | Pass / Recalibrate / Escalate |
| V-9 | Verify every mapped passage against a specific source location or mark it as generated/scaffolding-required. | Pass / Pass-with-warning / Fail |

### Cross-candidate validators

These run only across candidates from the current source/course submission, not the entire RLO bank.

| Rule | Proposed requirement |
| --- | --- |
| V-10 | Detect semantic duplicates at the same objective and cell. Merge true duplicates, propose merging scoped near-duplicates, and preserve related candidates at different cells. |
| V-11 | Resolve every prerequisite and postcondition to another candidate or explicitly mark it external. Flag orphan prerequisites, orphan postconditions, and likely missed candidates. |
| V-12 | Judge whether the overall cell distribution is pedagogically plausible. Flag all-one-cell sets, higher-level candidates with missing foundations, and suspicious over-classification. A distribution warning does not fail an individual candidate. |

### Report and triage rules

| Rule | Proposed requirement |
| --- | --- |
| V-13 | Assemble a final audit report with course/source-level totals, cell and readiness distributions, outcome counts, a five-cell POC2 chart, cross-candidate warnings, and per-candidate detail. |
| V-14 | Put a one-page validation summary first: what was produced, what can be approved quickly, what needs remediation, what needs judgment, estimated scaffolding workload, and Teach-completeness counts. |
| V-15 | Assign exactly one triage bucket using worst-outcome precedence: any Fail or Escalate → Judgment-required; otherwise any Pass-with-warning → Attention-required; otherwise all Pass → Fast-approval. Name every triggered validator; never average or majority-vote. |

### Required validation output

The proposed output consists of:

- the final audit report from V-13;
- the one-page validation summary from V-14; and
- a machine-readable candidate manifest containing validator outcomes, evidence, metadata, and scaffolding requirements.

The proposed routing is:

- approved candidates with gaps proceed to scaffolding generation;
- rejected candidates exit but remain auditable; and
- materially modified candidates re-enter the earliest affected layer—for example, a cell change returns to classification and remapping.

### Validation calibration guidance

- Validators must commit to a discrete outcome, not “probably pass.”
- V-10 and V-11 are submission/course scope only; bank-wide comparison belongs to downstream orchestration.
- The one-page summary is the most important reviewer-facing artifact and warrants focused UX attention.
- Failed candidates remain available for remediation or explicit rejection.
- Escalation is desirable when automation cannot responsibly resolve a question.

## Deck-level product guidance

The deck adds or emphasizes the following product expectations beyond the numbered rules:

- The input may be SME material, regulatory/policy text, references, or unstructured practitioner knowledge.
- The first major output is a reviewer-ready list of learning units, not finished authored RLOs.
- Instructional Designers own the definition of quality, the rules, review decisions, and hard judgment calls.
- The review gate is described as per-candidate rather than all-or-nothing batch approval.
- Source-derived and generated material must remain distinguishable.
- After approval, generation fills only identified gaps according to the selected cell's schema and methodology.
- RLO sequencing into learner pathways is downstream of generation.
- Personalization changes professional context without changing the objective, fixed Teach, or cognitive demand.
- Initial personalization inputs are job family, industry alignment, and career level. Potential later inputs include proficiency, learning history, goals, and talent-deployment data.
- The deck proposes context-specific hooks, examples, practice, checks, and on-job prompts for Deloitte roles such as Audit, Tax, Advisory, and Consulting while holding the core learning constant.

## Cross-layer handoff summary

| Layer | Consumes | Adds | Must preserve |
| --- | --- | --- | --- |
| Decomposition | Ordered source content and lineage | Candidate objective, evidence, confidence, preliminary hint | Every plausible candidate and its source signals |
| Classification | Candidate and relevant source evidence | Content kind, Bloom, cell confidence, alternatives | Objective identity, lineage, and ambiguity |
| Mapping | Classified candidate, schema, and source | Seven-part coverage, passages, gaps, readiness | Precise passage lineage and inferred/generated distinction |
| Validation | Full mapped candidate set | Integrity outcomes, triage, audit report | Failed/escalated candidates, remediation, and all evidence |

## Current POC interpretation

These are product decisions made after the source documents were written. They qualify implementation behavior but do not silently rewrite the proposed rules above.

1. **The first pass discovers a broad list of enabling learning objectives.** It should not prematurely construct full RLOs or reduce the list to an arbitrary candidate count. RLOs are generally components of larger pathways, so a terminal objective is not required on each RLO candidate.
2. **Objective review is the first human gate.** An LDS Instructional Designer can approve, edit, reject, or add candidates and can inspect exact source lineage.
3. **Show source availability during objective review.** Alongside each candidate, show preliminary evidence for Cover, Set-up, Teach, Show, Practice, Check, and Send-off. This is an inventory of what appears to exist in the source, not human validation of extraction quality and not a claim that the eventual RLO section is pedagogically complete.
4. **Classification at listing time is provisional but authoring eligibility is not.** Suggested Bloom level and content kind may be refined, but objective approval, Target, and Observed classification must remain within the five POC2 cells. An outside-scope objective remains visible and cannot start authoring.
5. **Do not create a separate human mapping/detail-review gate solely to confirm source extraction.** The preferred POC shape is objective review with source availability, followed later by review of the generated RLO. Automated checks may run between those human gates.
6. **Preserve both related candidates at different levels.** If the same topic yields Concept × Understand and Concept × Apply objectives, keep both. The downstream pathway system—not the RLO generator—decides which a learner receives.
7. **Prompts are implementation assets.** Prompts used for discovery, reconciliation, coverage, or later classification must be clearly named, versioned, and easy to inspect and edit.

## Source-rule tensions and unresolved decisions

These points require conscious resolution before the corresponding source rule is treated as an implementation contract.

| Topic | Tension or open decision |
| --- | --- |
| Terminal vs enabling objectives | D-2 calls a stated objective terminal and decomposes it. The current POC treats RLO candidates primarily as enabling objectives that participate in larger pathways. Preserve the decomposition intent without requiring a terminal objective field. |
| Early committed classification | D-16 and Layer 2 assume one committed cell before mapping. Current product direction treats early classification as a hint because practice and assessment usually do not exist yet. Distinguish `suggested`, `target`, and `observed` classifications in later data design. |
| Escalation output | C-3 requires plausible cells and a discriminator but does not specify whether to return a provisional best cell. A stable JSON contract still needs this decision. |
| Existing-bank suppression | D-19 suppresses exact bank duplicates, but current RLOs are disposable prototypes and early classification is provisional. Bank-wide deduplication/reprocessing is not a current priority. |
| Seven-part completeness | M-1 through M-11 require a committed cell/schema before a part can be declared Complete. Objective review can therefore show only preliminary source availability; formal completeness belongs after a target schema is chosen. |
| Human-gate ordering | The Mapping document refers to reviewer approval before Layer 4 in one passage, while the Validation document and deck place Layer 4 before the human review gate. The deck's end-to-end flow favors validation before review. |
| Scaffolding ownership | Mapping language sometimes implies scaffolding work occurs in Layer 4, while the Validation document defines Layer 4 as audit-only and sends approved gaps to a separate generation system. The latter is the clearer boundary. |
| Number of reviews | The source material can be read as objective, mapping/detail, and final-content reviews. Current POC direction favors two human gates: objective/availability review and eventual RLO review. |
| Rule cross-references | V-6 says it formalizes D-14–D-16 granularity guidance, but the actual single-cell, duration, and boundary rules are D-16–D-18. Treat this as a source-document numbering error. |
| Excluded cell guidance | Historical inputs describe additional combinations, but active POC2 prompts and methodology contain only the five approved cells. |
| Personalization timing | The deck describes adaptive learner-specific RLO sections, but the generator does not know the eventual learner during objective discovery or base RLO creation. Treat those as downstream rendering/orchestration variants, not separate objectives. |

## Implementation checklist derived from the rules

This is a traceability checklist, not a new feature plan.

- [ ] Candidate records preserve objective, evidence, confidence, provenance, and uncertainty.
- [ ] Objective discovery surfaces low-confidence candidates and does not enforce a fixed count.
- [ ] Source hierarchy preserves file order and precise page/slide/clause/paragraph lineage.
- [ ] Early content-kind and Bloom values are explicitly marked as suggestions.
- [ ] Objective review supports approve, edit, reject, and add actions.
- [ ] Objective review shows preliminary seven-part source availability with lineage.
- [ ] Prompt files are named, versioned, inspectable, and editable.
- [ ] Later RLO planning retrieves a versioned schema/methodology for a target cell.
- [ ] Source mapping distinguishes source-derived content from scaffolding-required content.
- [ ] Formal mapping challenges every `Complete` status against the selected schema.
- [ ] Validation produces discrete, traceable outcomes and never drops failures.
- [ ] Cross-candidate duplicate, dependency, and distribution checks run at submission scope.
- [ ] Human review decisions and re-entry routing remain auditable.
- [ ] Generated RLO review compares observed alignment with the planned target without treating the early hint as binding.
