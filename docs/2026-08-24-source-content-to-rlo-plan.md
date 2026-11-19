# Source Content to Reusable Learning Objects: High-Level Feature Plan

**Status:** Draft for product and architecture review  
**Date:** 2026-08-24  
**Scope:** Source intake through reviewed draft RLO creation

## 1. Purpose

Build a repeatable pipeline that converts authoritative source material—such as
statutes, standards, government publications, technical manuals, books, and
presentations—into evidence-grounded candidate learning objectives and then
into pedagogically complete draft Reusable Learning Objects (RLOs).

The feature must preserve a reviewable chain from every generated claim back to
the source. It must help a Deloitte learning practitioner make the instructional
decisions that source documents cannot answer alone: who needs to learn what,
for which real work, at what depth, and with what priority.

## 2. Current repository baseline

The repository already provides a narrow intake slice:

- authenticated upload for PDF, PPTX, DOCX, EPUB, HTML, Markdown, and text;
- file validation, duplicate detection, checksum generation, and original-file
  storage in MinIO or GCS;
- a persistent ingestion job record and background worker; and
- lightweight metadata extraction such as page count, slide count, title,
  author, and word count.

The current worker does **not** extract substantive content. The feature still
needs a canonical extracted-document model, layout-aware extraction, OCR,
mechanical quality checks, chunking and retrieval, source classification,
learning-context capture, objective generation, source-grounded RLO drafting,
and instructional designer review of the resulting RLOs.

The existing RLO schema is the intended output contract. In particular, each
RLO has exactly one enabling objective and already supports concepts,
instructional components, assessments, sources, performance context,
governance, accessibility, and rights.

## 3. Product principles

1. **Extract first; interpret second.** Deterministic parsing and OCR create a
   durable source representation before any LLM reasoning occurs.
2. **Never silently truncate a source.** The complete document is ingested even
   when no single model call can contain it.
3. **Ground every proposal.** Candidate objectives and RLO claims cite stable
   page, slide, section, and element identifiers.
4. **Treat practitioner relevance as an explicit input.** The source establishes
   what is true; a human-informed learning brief establishes what is useful.
5. **Human approval is an RLO gate.** Instructional designers validate created
   RLOs, not extraction artifacts or a separate objective workspace.
6. **Keep generated artifacts reproducible.** Store extractor, model, prompt,
   configuration, and source versions with each run.
7. **Evaluate capability, not reputation.** Select extraction components through
   a repository-owned benchmark corpus and pinned license review.
8. **Keep source content canonical.** Extracted, indexed, summarized, and RLO
   artifacts are derived outputs and can be regenerated.

## 4. Proposed end-to-end workflow

```text
Upload and attest rights
  -> classify source and inspect safety
  -> extract structure, text, tables, figures, and notes
  -> apply OCR only where needed
  -> run mechanical extraction checks and retain diagnostics
  -> normalize, segment, and index with source anchors
  -> capture practitioner learning brief
  -> map the source and identify learning opportunities
  -> propose evidence-backed objectives
  -> generate one draft RLO per selected enabling objective candidate
  -> validate grounding, pedagogy, schema, rights, and accessibility
  -> instructional designer reviews RLOs and approves catalog publication
```

## 5. Capability areas

### 5.1 Intake, provenance, and source classification

Extend intake to capture:

- title, publisher/issuing authority, publication date, edition/version, and
  canonical URL or citation;
- uploader's right to use the material, sharing constraints, sensitivity, and
  retention classification;
- language and expected document type;
- source role: authoritative primary source, secondary treatment, reference,
  job aid, existing instructional material, assessment, or unknown; and
- optional grouping of multiple files into one source collection.

The classification stage should detect likely assessments, answer keys,
storyboards, course scripts, and already-authored learning objectives. These
materials may be retained as explicitly labeled comparison or supporting
artifacts, but must not silently leak instructional decisions into a test that
claims to derive them from raw factual material.

### 5.2 High-fidelity extraction

Create a dedicated, containerized extraction worker. Its output should be a
versioned `ExtractedDocument` JSON artifact containing:

- document metadata and hierarchy;
- ordered elements such as headings, paragraphs, lists, tables, formulas,
  figures, captions, headers, footers, footnotes, and citations;
- page or slide number, bounding box when available, and reading order for every
  element;
- PPTX speaker notes and slide/shape relationships where available;
- extracted and rendered representations of tables and figures;
- extraction method, confidence, warnings, and engine/model versions; and
- stable element IDs used by every downstream citation.

Recommended initial technical direction:

- run a short bake-off with **Docling** as the leading unified PDF/PPTX/DOCX
  candidate; its code is MIT-licensed and it emits structured JSON/Markdown;
- use native OOXML extraction where it provides information a general parser
  omits, especially PPTX speaker notes and object relationships;
- use **Tesseract** (Apache-2.0) as a conservative OCR baseline and benchmark
  **PaddleOCR / PP-StructureV3** (Apache-2.0) for harder layouts, tables,
  orientation, and multilingual material; and
- retain Apache Tika (Apache-2.0) as a broad-format fallback only if the bake-off
  demonstrates a format gap. Do not add parallel extractors speculatively.

Docling's code license does not automatically establish that every optional
model weight and transitive dependency is acceptable. Pin the actual runtime
bill of materials, model cards, weights, and licenses and require legal/security
approval before selection.

Docling should run as a local deterministic extraction service and should not
depend on LiteLLM for its standard parsing, layout, table, or OCR stages. This
keeps extraction reproducible, limits source disclosure, and allows extraction
quality to be evaluated independently from generative-model behavior. Optional
Docling VLM pipelines should not be enabled in the initial slice unless the
benchmark demonstrates a specific gap that cannot be met by the standard
pipeline.

LiteLLM begins at the semantic interpretation boundary. Purpose-specific calls
may enrich uncertain structure, produce section/document maps, discover
objectives, verify evidence, critique pedagogy, and draft RLOs. GPT-5.6 Luna is
the initial candidate for high-volume structured tasks such as section mapping
and classification. Model selection for objective proposal, evidence
verification, and RLO drafting remains an evaluation decision: compare Luna
with a stronger configured alias on representative sources and promote only
where human and grounding scores justify the added cost.

Commercial models are permitted and preferred where they produce the best
measured result. All generative model traffic must use the product's existing
LiteLLM-to-Azure-OpenAI path. Do not introduce third-party document-processing,
OCR, extraction, embedding, or model APIs. Locally deployed open-source
components may still be used for deterministic extraction and OCR.

OCR should be selected per page or slide, not merely per file. Born-digital
text should remain authoritative when healthy; OCR should run for image-only
pages, corrupt or sparse text layers, and image regions that contain material
text. Preserve both native and OCR text plus confidence so diagnostics identify
which path produced a passage.

### 5.3 Extraction diagnostics

Record mechanical diagnostics for missing output, unreadable pages, uncertain
reading order, low OCR confidence, malformed structures, unsupported objects,
and likely repeated headers or footers. Fail only when an observable processing
requirement is not met; otherwise retain warnings for troubleshooting and
continue unattended. Do not require an instructional designer to review or
approve extraction.

Chart explanations must retain the original visual, source lineage, bounded
context, and structured uncertainty. Automated tests verify those mechanics,
not subjective semantic accuracy that would require a separate interpretation
system to judge.

### 5.4 Universal ordered document hierarchy

Normalize every source into one format-neutral, ordered document tree. The tree
must preserve at least the order in which material appears, even when the
extractor cannot infer rich semantic structure.

Every node should carry:

- a stable `node_id`, `parent_id`, and zero-based `ordinal` among siblings;
- an `ordinal_path` derived from ancestor ordinals for deterministic whole-source
  traversal;
- a generic structural `kind` such as `root`, `container`, `block`, `inline`, or
  `asset`;
- a more specific semantic `role` such as `part`, `chapter`, `section`, `page`,
  `slide`, `heading`, `paragraph`, `list`, `table`, `figure`, `caption`,
  `footnote`, `speaker_note`, or `formula`;
- text or a reference to a binary/visual asset;
- physical source locators such as page, slide, shape, bounding box, cell, or
  character offsets;
- extraction method, confidence, and provenance; and
- ordered child IDs plus optional typed relationships to non-child nodes.

The generic `kind` makes traversal and chunking format-independent; `role`
retains the meaning needed by specialized renderers and reviewers. Unknown
content remains an ordered `block` rather than being dropped.

The hierarchy and physical layout are related but distinct. For example, a PDF
section can span several pages, while a page can contain blocks from nested
sections. Preserve a canonical logical tree and attach page/slide/bounding-box
locators to its nodes. Use typed relationships for structures that are not
strictly hierarchical—caption-to-figure, footnote-to-reference,
speaker-note-to-slide, table-cell coordinates, citations, and cross-references.
Do not force these into the parent/child tree.

Store the canonical derived artifact as nested JSON for portability and expose
an adjacency representation (`node_id`, `parent_id`, `ordinal`) for querying.
All chunks, summaries, objective evidence, and RLO evidence must reference these
stable node IDs rather than copying untraceable text.

### 5.5 Normalization, segmentation, and retrieval

Do not use the LLM context window as a document parser. Once extraction is
complete:

- segment by document structure first (part/chapter/section/page/slide) and by
  token size second;
- keep tables, captions, footnotes, and list structures together where possible;
- allow small overlaps while retaining a single canonical element identity;
- create embeddings for discovery, while keeping authoritative text and anchors
  in object storage/database artifacts; and
- construct hierarchical section and document maps from bounded evidence sets.

Set a hard maximum of **50,000 source tokens per LLM call**, excluding system
instructions, response allowance, and tool/schema overhead. The caller must
calculate the model's complete request budget and use the lower limit. Most
operations should use substantially smaller, section-coherent inputs; 50,000 is
a ceiling, not a target.

Long-document synthesis should follow a deterministic hierarchy:

1. summarize/map bounded sections with citations;
2. combine section maps into chapter or part maps;
3. identify cross-document themes and conflicts from those maps;
4. retrieve original evidence for each candidate objective; and
5. reject a candidate if adequate primary evidence cannot be reassembled within
   the request budget.

### 5.6 Practitioner learning brief

Before proposing objectives, ask the learning practitioner for a lightweight
brief:

- target Deloitte roles, service lines, industries, and experience levels;
- real tasks, decisions, risks, or conversations the material should support;
- desired business/performance outcome and triggering context;
- required versus optional topics and explicitly excluded scope;
- expected baseline knowledge and target proficiency;
- regulatory, geographic, client, confidentiality, and time constraints; and
- preferred breadth or approximate learning duration.

The agent may suggest answers inferred from the source, but must label them as
assumptions. If the user supplies little context, the system should propose a
small set of alternative practitioner lenses rather than fabricate one universal
curriculum from a broad source such as a NIST framework.

The brief is optional. With no practitioner instructions, the system should
continue using clearly labeled assumptions and offer a small set of plausible
learning lenses for the admin to refine. Supplying lightweight instructions
should improve relevance without becoming an intake blocker.

### 5.7 Agentic objective discovery

Use a bounded workflow with typed intermediate artifacts rather than an
open-ended autonomous agent:

1. **Source mapper:** identifies topics, mandates, procedures, decision points,
   examples, exceptions, dependencies, and source authority.
2. **Practice mapper:** relates supported material to the approved practitioner
   brief and identifies realistic workplace applications.
3. **Objective proposer:** creates a deliberately limited candidate set with an
   observable behavior, conditions/context, expected level, and scope.
4. **Evidence verifier:** independently retrieves supporting and potentially
   conflicting passages and marks unsupported or over-broad candidates.
5. **Pedagogy critic:** checks atomicity, Bloom/performance alignment,
   teachability, redundancy, assessability, prerequisite burden, and whether an
   item is merely a topic rather than an objective.
6. **Portfolio curator:** groups duplicates, exposes alternatives, identifies
   coverage gaps, and selects a bounded candidate set for draft generation.

Each candidate objective should include:

- proposed enabling and terminal objective language;
- practitioner role and performance context;
- source scope and citations visible as page/slide excerpts;
- rationale for practitioner value;
- Bloom level, performance level, difficulty, prerequisites, and estimated
  learning effort;
- confidence and explicit assumptions;
- overlap/dependency links to other candidates; and
- critic findings and reason for inclusion.

Candidate count must be governed by the learning brief, not document length.
Default to a curated shortlist and let the user request broader exploration.

### 5.8 Instructional designer RLO review interface

After draft creation, provide a workspace rather than a chat-only experience:

- source outline and page/slide viewer on the left;
- draft RLOs in a sortable, filterable center panel;
- RLO parts, evidence, rationale, assumptions, and validation findings in a
  detail panel;
- edit, approve, reject, comment, and request-revision actions;
- visible change history;
- coverage view showing which source sections and practitioner needs are
  represented, intentionally excluded, or unresolved;
- comments and review states for the instructional designer; and
- keyboard-complete controls, semantic structure, visible focus, and accessible
  evidence descriptions.

This is an authenticated learning-administration capability. “User” in this
workflow means a learning admin, learning practitioner, or reviewing SME—not a
general employee or learner. No learner-facing source or RLO review
experience is in scope.

Regeneration must be scoped and must not discard instructional designer edits.

### 5.9 Draft RLO creation and publication

Create one draft RLO per selected enabling objective candidate. Generation
should retrieve only candidate context and directly supporting source elements. It
should populate the existing schema, including concepts, CDT components,
misconceptions, assessment items, design brief, performance context, sources,
rights, and governance.

Add source anchors fine-grained enough to validate individual concepts,
components, examples, misconceptions, and assessment answers. The present RLO
`Source` citation is bibliographic, and `Concept.source_refs` points only to
those whole-source records. The schema already permits multiple sources, but it
does not represent claim-level document evidence.

Extend the RLO schema with a portable evidence ledger rather than overloading
the bibliographic citation string. At minimum:

- each `Source` gains the ingested source document ID, immutable version or
  checksum, and optional canonical locator;
- each evidence entry identifies its source, one or more extracted `node_id`
  values, a human-readable page/slide/section locator, and an excerpt hash; and
- objectives, concepts, components, misconceptions, and assessment items can
  reference evidence-entry IDs.

An RLO may use one or many source documents. Every supported claim must retain
source-specific evidence, and the generation/review interface must expose when
sources agree, overlap, conflict, or have different authority. Multi-source
support must not merge passages into a synthetic citation that loses origin.

Drafts remain non-production until:

- schema and cross-reference validation passes;
- every factual claim and correct assessment answer is supported;
- unsupported examples are removed or clearly designated for SME authorship;
- objective/component/assessment alignment passes;
- rights and governance fields are complete; and
- the instructional designer's review decision is recorded.

Approved RLOs then enter the existing catalog and commissioning flow; this
feature should not bypass catalog versioning or approval eligibility rules.

### 5.10 Operations, security, and observability

- Persist production source jobs in Postgres so workers fail explicitly when
  durable state is unavailable.
- Use explicit, retryable stage states and immutable artifacts so jobs resume
  after failure without repeating successful expensive work.
- Run document tools in resource-limited containers with no unnecessary network
  access; treat uploaded files and extracted instructions as untrusted input.
- Scan uploads, defend against archives/decompression bombs and malformed office
  files, and prevent document text from becoming agent instructions.
- Encrypt and authorize originals, derivatives, previews, and citations under
  the same source-level access policy.
- Support deletion and retention across originals, derivatives, indexes,
  caches, traces, and generated drafts.
- Add purpose-specific LiteLLM aliases for source mapping, objective proposing,
  evidence verification, pedagogy critique, and RLO drafting. Provider IDs stay
  only in `litellm/config.yaml`.
- Record per-stage duration, page/token volume, OCR use, warnings, model usage,
  cost, retries, reviewer changes, and grounding results without logging
  restricted source content into general telemetry.

## 6. Proposed delivery phases and exit gates

### Phase 0 — Decisions, corpus, and contracts

- Resolve licensing scope, supported formats/languages, sensitivity boundary,
  reviewer roles, and source-to-RLO citation requirements.
- Define versioned contracts for source metadata, extracted elements, extraction
  reports, chunks, learning briefs, candidate objectives, reviews, and lineage.
- Build a small representative corpus from the included NIST and GAO PDFs plus
  focused born-digital/scanned PDF and PPTX cases for observable mechanics and
  known failures.

**Exit gate:** contracts and focused mechanical cases are defined before an
extractor is selected.

### Phase 1 — PDF/PPTX extraction vertical slice

- Benchmark eligible extraction/OCR stacks in containers.
- Persist a canonical extracted artifact with stable page/slide anchors.
- Add extraction diagnostics for PDF and PPTX.
- Pin the full dependency/model license inventory.

**Exit gate:** representative PDF and PPTX documents can be uploaded, extracted,
and regenerated deterministically; observable structure, lineage, and failure
conditions pass focused tests.

### Phase 2 — Segmentation, indexing, and document map

- Create structure-aware segments and exact element lineage.
- Index segments for hybrid retrieval.
- Generate section/document maps under the per-call token budget.
- Add resumability, idempotency, access control, and deletion propagation.

**Exit gate:** a document larger than an LLM context window produces a complete,
navigable map without truncation, and every summary statement resolves to source
evidence.

### Phase 3 — Learning brief and objective discovery

- Implement the practitioner brief and alternative learning lenses.
- Produce typed, cited candidate objectives through the bounded agent workflow.

**Exit gate:** one broad authoritative source produces a deliberately scoped,
evidence-backed objective candidate set with all model assumptions recorded.

### Phase 4 — Grounded draft RLOs

- Generate schema-valid draft RLOs from selected objective candidates.
- Add claim-level evidence verification and pedagogical alignment checks.
- Add instructional designer review states, revisions, and catalog publication.

**Exit gate:** each selected objective candidate yields one reviewable draft RLO
whose claims and assessment answers trace to source elements and which enters
the existing catalog only after instructional designer approval.

### Phase 5 — Hardening and format expansion

- Add DOCX, HTML, EPUB, Markdown, and text through the same canonical contract.
- Add multilingual OCR only for approved languages and measured models.
- Tune throughput, GPU/CPU scheduling, batch collections, disaster recovery,
  retention, and cost controls.

**Exit gate:** the service meets agreed quality, security, accessibility,
throughput, and recovery objectives on the production-like benchmark suite.

## 7. Evaluation strategy

Extraction evaluation must include more than “text was returned”:

- character/word accuracy on OCR pages;
- reading-order and hierarchy accuracy;
- table cell/structure fidelity;
- figure/caption association;
- PPTX slide, note, and object coverage;
- citation-anchor correctness and visual alignment;
- latency, peak memory/GPU use, and failure rate; and
- license and vulnerability findings for the pinned runtime.

Objective/RLO evaluation should include:

- evidence precision and citation correctness;
- unsupported-claim and contradiction rate;
- objective atomicity, observability, assessability, and role relevance;
- duplicate/redundancy and prerequisite quality;
- instructional designer RLO acceptance, edits, rejection reasons, and review
  time; and
- schema, lineage, rights, accessibility, and governance validity.

LLM-as-judge scores may aid development triage but are not an extraction release
gate. Test observable mechanics deterministically and reserve human evaluation
for created RLOs.

## 8. Principal risks and controls

| Risk | Primary control |
|---|---|
| Complex layouts produce plausible but incorrect text order | Stable bounding-box anchors, mechanical invariants, diagnostics, and documented limitations |
| OCR corrupts valid born-digital text | Page-level OCR routing; preserve and compare native/OCR variants |
| Long sources are truncated or lose minority topics | Whole-document extraction, hierarchical maps, coverage ledger, retrieval back to original evidence |
| Broad standards generate an unbounded curriculum | Optional practitioner context, proposed learning lenses, curated candidate cap, explicit scope and exclusions |
| Existing course artifacts leak objectives or answers | Intake classification and labels; exclude or isolate comparison artifacts |
| Model invents practice relevance or factual support | Visible assumptions, evidence verifier, instructional designer RLO approval, claim-level grounding |
| Prompt injection appears in source text | Treat source as quoted data, typed tool boundaries, least privilege, no source-directed tool use |
| “Open source” dependency includes restricted model weights | Pinned software/model bill of materials and license approval |
| Source version changes invalidate RLOs | Immutable checksums, citations, version graph, impact analysis and review workflow |
| Sensitive content leaks through logs or indexes | Source-level authorization, protected derivatives, telemetry redaction, complete deletion |

## 9. Confirmed product decisions

- Commercial generative models are allowed and generally preferred. Model calls
  use the existing LiteLLM-to-Azure-OpenAI path.
- No third-party APIs may process source data outside that approved model path.
  Extraction and OCR run locally using approved dependencies.
- Initial content scope is public and Deloitte-internal material. Avoid adding
  disproportionate sensitivity machinery to the first vertical slice.
- Initial language scope is English. Legacy `.ppt` is excluded; `.pptx` remains
  in scope.
- Charts and diagrams require grounded written explanations so downstream
  models can use their meaning, not merely their surrounding text.
- Practitioner instructions are optional. The system continues with visible
  assumptions and suggested learning lenses when instructions are absent.
- The workflow is an admin capability, not a learner-facing feature.
- Instructional designers review created RLOs, not extraction output or a
  separate objective approval workspace.
- RLOs may use one or multiple source documents, provided source-specific
  lineage is retained for every supported claim.

## 10. Remaining questions for review

1. Should 50,000 mean source-content tokens per model call, as proposed, or a
   lower complete-request ceiling including instructions and output?
2. What should be the default objective shortlist size and expected RLO
   granularity or duration?
3. When multiple sources conflict, should the admin select the controlling
   authority manually, or may the system recommend precedence for approval?
4. Does source removal archive dependent RLOs, block deletion, or retain a
   required evidence snapshot?
5. Are handwritten documents, mathematical formulas, and embedded PPTX media
   explicitly out of the initial release, or should they enter the extraction
   benchmark even though multilingual and legacy PPT do not?

## 11. Current recommendation

Begin with Phase 0 and a narrow Phase 1 bake-off using the three representative
NIST/GAO PDFs already in the repository, then add deliberately difficult scanned
PDF and PPTX fixtures. Do not begin objective prompting until the canonical
source/evidence contracts and observable extraction checks exist. That order
makes grounding testable without creating a false semantic-quality gate or
coupling RLO generation to whichever parser is selected first.

## 12. Initial technology references

- [Docling project and supported formats](https://docling.org/)
- [Docling model catalog](https://github.com/docling-project/docling/blob/main/docs/usage/model_catalog.md)
- [PaddleOCR / PP-StructureV3](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.en.md)
- [Tesseract documentation](https://github.com/tesseract-ocr/tessdoc)
- [Apache Tika](https://tika.apache.org/)
- [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF)
