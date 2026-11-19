# Source Content to RLO Implementation Plan

**Status:** Phase 9 complete — Phase 10 next
**Progress:** 10 of 11 phases complete
**Date:** 2026-08-24  
**Source plan:** [`2026-08-24-source-content-to-rlo-plan.md`](2026-08-24-source-content-to-rlo-plan.md)

## Goal

Build an admin-only workflow that converts one or more uploaded source documents
into reviewed, evidence-grounded draft Reusable Learning Objects (RLOs).

The completed path is:

```text
Upload PDF/PPTX
  -> deterministic Docling extraction and selective OCR
  -> universal ordered document hierarchy
  -> chart/diagram explanations through Azure OpenAI
  -> hierarchy-aware segmentation and indexing
  -> optional practitioner context and document mapping
  -> evidence-backed objective proposals
  -> grounded draft RLO creation
  -> instructional designer RLO review
  -> evidence, pedagogy, schema, and governance validation
  -> existing versioned RLO catalog
```

## Working Rules

- Complete and verify one phase before starting the next.
- Update this document's phase checkbox and progress count only after its exit
  gate passes.
- Add a short execution record beneath each completed phase with the commit,
  tests, benchmark result, and any changed assumption.
- Write a failing generic test before changing behavior.
- Run builds, tests, migrations, and browser smoke checks in containers.
- Keep uploaded source content canonical. Every extracted, mapped, indexed,
  proposed, and generated artifact is a versioned derivative.
- Never truncate a document because it exceeds a model context window.
- Treat uploaded files and their text as untrusted data, never as agent
  instructions.
- Use only local, approved extraction/OCR dependencies and the existing
  LiteLLM-to-Azure-OpenAI model path. Do not introduce another processing API.
- Put provider model IDs only in `litellm/config.yaml`; application code uses
  purpose-specific `ModelAlias` values.
- Preserve stable source node IDs through chunking, mapping, RLO review,
  and RLO generation.
- Do not publish a model-generated RLO without explicit instructional designer
  review.
- Keep tests topic-neutral. NIST and GAO files are evaluation fixtures, not
  hard-coded product assumptions.

## Confirmed Scope

- [x] Commercial generative models are allowed and preferred when evaluation
  shows better results.
- [x] Model traffic uses LiteLLM and Azure OpenAI.
- [x] Third-party document-processing APIs are prohibited.
- [x] Public and Deloitte-internal materials are in scope.
- [x] English PDF and PPTX are the initial formats.
- [x] Legacy `.ppt` and multilingual optimization are out of initial scope.
- [x] Scanned PDFs and selective OCR are in scope.
- [x] Charts and diagrams must receive grounded written explanations.
- [x] Practitioner instructions are optional.
- [x] The workflow is for learning admins, not general employees or learners.
- [x] An RLO may use one or multiple source documents if claim-level lineage is
  retained.

## Initial Assumptions to Validate

- Use `SOURCE_CONTENT_TRANCHE_TOKEN_LIMIT` (15,000 by default) to bound one
  information tranche and `SOURCE_CONTENT_REQUEST_TOKEN_LIMIT` (100,000 by
  default) to bound serialized model input. A synthesis request may combine
  roughly five or six tranches while reserving capacity for structure and
  intermediate results.
- Use Docling's standard local pipeline before considering an optional VLM
  extraction mode.
- Use GPT-5.6 Luna first for high-volume mapping, classification, and chart
  descriptions; benchmark stronger aliases for objective proposal, evidence
  verification, pedagogical critique, and RLO drafting.
- Treat handwriting, audio/video transcription, and legacy Office formats as
  out of scope for the first release.
- Start with a curated objective shortlist capped at 12 candidates per
  workspace; use evaluation results to adjust it.
- Do not physically remove source evidence referenced by a published RLO until
  a retention/dependency policy is approved in Phase 9.

## Phase Tracker

- [x] Phase 0 — Baseline, corpus, and dependency decision
- [x] Phase 1 — Canonical contracts and ordered hierarchy
- [x] Phase 2 — Durable source persistence and worker separation
- [x] Phase 3 — Docling PDF/PPTX extraction vertical slice
- [x] Phase 4 — Selective OCR and visual explanations
- [x] Phase 5 — Hierarchy-aware segmentation, indexing, and retrieval
- [x] Phase 6 — Hierarchical document and collection mapping
- [x] Phase 7 — Optional learning brief and objective discovery
- [x] Phase 8 — RLO evidence schema
- [x] Phase 9 — Grounded RLO drafting, instructional designer review, and publication
- [ ] Phase 10 — End-to-end evaluation, security, and rollout

## Architecture Boundaries

### Deterministic source-processing boundary

Owns file inspection, Docling conversion, native PPTX supplementation, OCR,
normalization, hierarchy construction, locators, previews, assets, and quality
metrics. It performs no pedagogical inference.

### Semantic source-authoring boundary

Owns chart explanations, section/document maps, practitioner lenses, objective
proposals, evidence verification, pedagogical critique, and RLO drafting. Every
model call consumes bounded node-referenced evidence through LiteLLM.

### Existing RLO catalog boundary

Remains the source of truth for validated RLO versions and Qdrant catalog
discovery. Draft generation must use the existing ingestion endpoint or its
shared service boundary rather than writing catalog objects directly.

## Planned Package and File Map

Exact filenames may be adjusted if an earlier phase proves a simpler fit, but
the responsibility boundaries should remain stable.

| Area | Planned responsibility |
|---|---|
| `api/src/source_ingestion/contracts.py` | Source, extraction-run, hierarchy-node, artifact, and quality-report contracts |
| `api/src/source_ingestion/hierarchy.py` | Ordered-tree construction, traversal, locator, and invariant validation |
| `api/src/source_ingestion/repository.py` | Durable source/job/run persistence and atomic state transitions |
| `api/src/source_ingestion/artifacts.py` | Versioned object-storage key construction and artifact manifests |
| `api/src/source_ingestion/extractors/docling.py` | Docling adapter and normalized output mapping |
| `api/src/source_ingestion/extractors/pptx.py` | PPTX notes/relationship supplementation when the benchmark requires it |
| `api/src/source_ingestion/ocr.py` | Page-level OCR routing and native/OCR comparison |
| `api/src/source_ingestion/quality.py` | Deterministic extraction warnings and mechanical failure checks |
| `api/src/source_ingestion/worker.py` | Retryable extraction-stage orchestration only |
| `api/src/source_authoring/` | Mapping, chart explanation, objective, evidence, review, and RLO-drafting services |
| `api/src/source_admin.py` | Admin APIs and read models for sources and RLO drafts |
| `api/templates/source_*.html` | Accessible admin upload and RLO review pages |
| `rlo_schema/v1.py` or next schema version | Portable source identity and evidence ledger |
| `src/learning_commissioning/adapters/rlo.py` | Evidence-aware catalog-to-pipeline projection |
| `llm_gateway/__init__.py` | Purpose-specific source-content model aliases |
| `litellm/config.yaml` | Azure OpenAI provider mappings and reasoning settings |
| `source_content/Dockerfile` | Heavy Docling/OCR extraction-worker runtime |
| `api/Dockerfile` test target | API/source packages plus repository source-content tests |
| `docker-compose.yml` | Postgres-backed source API/worker services and dependencies |
| `tests/source_content/` | Contracts, hierarchy, extraction, mapping, objectives, RLO, and evaluation tests |
| `tests/browser/` | Keyboard and browser smoke coverage for admin review workflows |

## Persistent Records and Artifacts

Use Postgres for queryable state and object storage for large immutable JSON,
page images, crops, and generated artifacts.

### Core records

- `source_documents`: stable source identity and current version.
- `source_versions`: checksum, original object URI, metadata, rights, uploader,
  and lifecycle state.
- `source_processing_runs`: stage, attempt, worker, extractor/model versions,
  timing, artifact URIs, warning counts, and failure information.
- `source_collections`: admin-selected group of one or more source versions.
- `source_collection_members`: ordered source membership and authority notes.
- `learning_briefs`: optional practitioner instructions and model-proposed
  assumptions/lenses.
- `objective_workspaces`: source collection, brief, model/prompt versions, state,
  and artifact URIs.
- `objective_candidates`: proposed objective, evidence, order, assumptions, and
  generation metadata.
- `rlo_draft_jobs`: objective snapshot, generated RLO URI, validation report,
  review state, and published catalog identity/version.

### Artifact key shape

```text
source-content/sources/{source_id}/versions/{checksum}/original/{filename}
source-content/sources/{source_id}/versions/{checksum}/extractions/{run_id}/document.json
source-content/sources/{source_id}/versions/{checksum}/extractions/{run_id}/report.json
source-content/sources/{source_id}/versions/{checksum}/extractions/{run_id}/previews/{locator}.webp
source-content/sources/{source_id}/versions/{checksum}/extractions/{run_id}/assets/{asset_id}
source-content/collections/{collection_id}/maps/{run_id}.json
source-content/objective-workspaces/{workspace_id}/{revision}.json
source-content/rlo-drafts/{draft_job_id}/{revision}.json
```

Do not expose object keys as browser-authorized paths. APIs resolve every artifact
through its owning source, collection, workspace, or draft record.

## Source Lifecycle

| State | Meaning |
|---|---|
| `uploaded` | Original and source-version record are durable. |
| `queued_for_extraction` | Waiting for an extraction worker. |
| `extracting` | A worker owns the active extraction attempt. |
| `indexing` | Extracted nodes are being segmented and indexed. |
| `ready` | Source can participate in mapping/objective workspaces. |
| `failed` | Current stage failed with retryable/non-retryable classification. |
| `archived` | Hidden from new workspaces but retained for lineage. |

Transitions must assert their expected prior state. Retrying creates a new run
and artifacts; it never overwrites a previous run.

---

## Phase 0 — Baseline, Corpus, and Dependency Decision

**Purpose:** Establish measurable acceptance criteria before selecting and
embedding a heavy extraction stack.

- [x] Record the branch, commit, current source-upload behavior, container image
  sizes, and targeted test results.
- [x] Add a reusable `api-test` Compose target that copies the API/source code
  and root source-content tests so every later API verification runs in a
  container without ad hoc bind mounts.
- [x] Inventory existing source upload, storage, worker, RLO schema, catalog,
  Qdrant, LiteLLM, and authentication boundaries.
- [x] Create a checked-in manifest for the benchmark corpus without duplicating
  restricted source files.
- [x] Include the existing NIST and GAO PDFs plus purpose-built fixtures for:
  born-digital multi-column PDF, image-only PDF, mixed native/scanned PDF,
  tables, footnotes, charts, diagrams, rotated pages, PPTX speaker notes,
  grouped shapes, tables, and reading-order ambiguity.
- [x] Add expected hierarchy/order, text, table, note, chart, and locator
  annotations for a small gold subset.
- [x] Define scored metrics and minimum Phase 2 thresholds for text coverage,
  reading order, hierarchy, table fidelity, PPTX notes, chart coverage, locator
  correctness, latency, and resource use.
- [x] Build and scan a pinned Docling proof image; inventory every direct and
  transitive software/model license.
- [x] Confirm that the selected standard Docling pipeline and OCR dependencies
  run without outbound processing APIs after images/models are built.
- [x] Record unresolved decisions rather than silently changing the assumptions
  above.

**Container verification:**

```bash
docker compose --profile test build api api-test
docker compose --profile test run --rm api-test python -m pytest tests/test_source_upload.py tests/test_source_ingestion_worker.py -q
```

**Exit gate:** A reproducible benchmark corpus, scoring script contract,
baseline results, pinned candidate image, and approved dependency/model license
inventory exist.

### Phase 0 execution record

Completed in the working tree on 2026-08-24 from base commit `89d2918`.

- Verification: 21 API/benchmark tests passed; 2 Docling runtime tests passed
  with Compose networking disabled.
- Benchmark: seven cases validate, including three public evaluation documents,
  four generated fixtures, and three schema-validated gold annotations.
- Candidate: Docling 2.119.0, PyTorch 2.7.1, local Heron/TableFormer assets,
  and local Tesseract. The separate test image is 1,223,672,808 bytes.
- Records: `2026-08-24-source-content-phase-0-baseline.md`,
  `2026-08-24-source-content-boundary-inventory.md`, and
  `2026-08-24-source-content-dependency-review.md`.
- Changed assumption: model compilation is disabled for CPU inference so the
  runtime does not require a production C++ compiler toolchain.

---

## Phase 1 — Canonical Contracts and Ordered Hierarchy

**Purpose:** Define the stable data boundary before integrating Docling output.

- [x] Write failing tests for hierarchy ordering, stable IDs, parent/child
  integrity, locators, unknown blocks, assets, and typed relationships.
- [x] Define strict, versioned Pydantic contracts for `SourceDocument`,
  `SourceVersion`, `ExtractionRun`, `ExtractedDocument`, `DocumentNode`,
  `SourceLocator`, `NodeRelationship`, `ExtractionWarning`, and
  `ExtractionQualityReport`.
- [x] Represent every node with `node_id`, `parent_id`, sibling `ordinal`,
  derived `ordinal_path`, generic `kind`, semantic `role`, content/asset
  reference, locators, method, confidence, and ordered children.
- [x] Define typed non-tree relationships for captions, footnotes, citations,
  speaker notes, cross-references, and table cells.
- [x] Implement deterministic depth-first traversal and prove it produces one
  complete source order.
- [x] Preserve unknown extracted material as ordered nodes instead of dropping
  it.
- [x] Reject duplicate IDs, orphaned nodes, cycles, mismatched child lists,
  duplicate sibling ordinals, invalid relationships, and locators outside the
  source.
- [x] Define artifact manifest and schema-version migration rules.
- [x] Serialize a nested portable artifact and an equivalent adjacency view;
  verify round-trip identity.

**Container verification:**

```bash
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_contracts.py tests/source_content/test_hierarchy.py -q
```

**Exit gate:** Format-neutral fixtures for PDF-like and PPTX-like content
validate, round-trip, and traverse in deterministic source order without any
Docling dependency.

### Phase 1 execution record

Completed in the working tree on 2026-08-24.

- Verification: 14 contract/hierarchy tests passed in `api-test`.
- Added strict v1 source, version, run, document, node, locator, relationship,
  warning, quality, and artifact contracts.
- Added deterministic node IDs, complete depth-first traversal, nested and
  adjacency round trips, and rejection tests for malformed trees, locators,
  relationships, and unknown fields.

---

## Phase 2 — Durable Source Persistence and Worker Separation

**Purpose:** Replace the SQLite/in-process metadata job with a durable,
horizontally safe stage boundary before expensive extraction is introduced.

- [x] Write failing repository tests for idempotent upload, checksum versioning,
  atomic claims, expected-state transitions, retry attempts, leases, stale-job
  recovery, and artifact ownership.
- [x] Add idempotent Postgres migrations only for source documents, versions,
  and processing runs. Add later workflow tables in the phase that first uses
  them.
- [x] Remove legacy SQLite persistence; source state is Postgres-only and a
  missing or non-Postgres database configuration fails startup.
- [x] Separate API startup from worker startup; the API must not run extraction
  in its lifespan.
- [x] Add a dedicated worker command that claims only eligible source stages
  with `FOR UPDATE SKIP LOCKED` or the repository's equivalent safe pattern.
- [x] Persist each stage artifact before advancing state.
- [x] Make uploads idempotent by source checksum without treating a new edition
  of the same logical document as an accidental duplicate.
- [x] Add bounded retry classification and prevent two workers from owning the
  same attempt.
- [x] Add Compose health checks and a separate source-worker service using the
  shared Postgres/object-storage services.
- [x] Preserve current authenticated upload/list/detail/delete behavior while
  returning the expanded source state.

**Container verification:**

```bash
docker compose --profile commissioning up -d workflow-postgres minio api
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_repository.py tests/test_source_upload.py -q
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_worker_claiming.py -q
```

**Exit gate:** Two containerized workers cannot double-claim a source; an API
restart does not lose state; current upload behavior remains compatible; and a
failed stage can be safely retried as a new run.

### Phase 2 execution record

Completed in the working tree on 2026-08-24.

- Verification: 45 API/source tests passed, including clean/idempotent
  migrations and a live Postgres two-worker contention test; 2 offline Docling
  runtime tests passed in the extraction image.
- Added versioned source documents, immutable editions, processing attempts,
  expected-state transitions, leases/stale recovery, bounded retry
  classification, and artifact ownership.
- Removed extraction from API lifespan and started the dedicated Compose worker
  against Postgres and MinIO; its container health check reported `healthy`.
- Removed the transitional SQLite importer and test fallback. API, worker, and
  repository tests all use the shared Postgres service.

---

## Phase 3 — Docling PDF/PPTX Extraction Vertical Slice

**Purpose:** Produce the canonical ordered hierarchy and downstream artifacts from
born-digital PDF and PPTX without generative inference.

- [x] Write adapter tests against pinned small PDF/PPTX fixtures before mapping
  the full benchmark corpus.
- [x] Create the dedicated extraction-worker image so Docling and native Office
  dependencies do not inflate the API runtime.
- [x] Add an extraction-worker test target containing the source-content tests
  and benchmark fixtures used by this and later extraction phases.
- [x] Pin Docling, its model artifacts, and every extraction option used by the
  run manifest.
- [x] Implement a Docling adapter that maps text, headings, lists, tables,
  figures, formulas, captions, pages/slides, bounding boxes, and reading order
  into the Phase 1 contracts.
- [x] Compare Docling PPTX output with the required notes/object relationships;
  add a narrow native OOXML supplement only for measured gaps.
- [x] Render page/slide previews and stable figure/table/chart crops.
- [x] Store original extractor output for diagnosis while making the normalized
  contract the only downstream interface.
- [x] Generate deterministic warnings for missing pages/slides, sparse output,
  ambiguous order, unsupported objects, and mapping loss.
- [x] Persist `document.json`, `report.json`, preview images, assets, and a
  complete artifact manifest.
- [x] Run the Phase 0 benchmark and record quality, time, CPU/GPU, memory, and
  image-size results.
- [x] Keep `.ppt`, multilingual tuning, handwriting, and media transcription out
  of the implementation.

**Container verification:**

```bash
docker compose --profile test build source-extraction-test
docker compose --profile test run --rm source-extraction-test python -m pytest tests/source_content/test_docling_adapter.py -q
docker compose --profile test run --rm source-extraction-test python -m src.source_ingestion.benchmark --manifest tests/source_content/fixtures/manifest.json
```

**Exit gate:** Representative born-digital PDF and PPTX inputs produce valid,
complete, ordered canonical artifacts with stable page/slide locators and meet
the approved benchmark threshold.

### Phase 3 execution record

Completed in the working tree on 2026-08-24.

- Verification: 9 focused benchmark, adapter, quality, and worker tests passed
  in the dedicated extraction test image.
- Benchmark: the born-digital gold PDF and PPTX cases passed every approved
  quality threshold at 1.0. Cold PDF extraction took 6.682 seconds and warm
  PPTX extraction took 1.208 seconds; preview/crop output was 33,716 and 78,782
  bytes respectively. Peak process RSS was 1,214,288 KiB and GPU use was zero.
- Runtime: Docling 2.119.0 and PDFium 5.1.0 run offline; local LibreOffice
  renders PPTX review previews. The worker image is 1,342,979,492 bytes.
- Artifacts: normalized and original extractor JSON, deterministic quality
  report, WebP page/slide previews, table/figure/chart crops, and the complete
  checksummed manifest are persisted before the ready-state transition.
- Changed assumption: numeric citation markers are ignored by benchmark text
  comparison when Docling preserves the complete cited wording but normalizes
  away the marker glyph.

---

## Phase 4 — Selective OCR and Visual Explanations

**Purpose:** Support scanned pages and make meaningful charts/diagrams usable by
downstream text-based reasoning.

- [x] Write failing tests for image-only pages, mixed documents, corrupt/sparse
  native text, rotated pages, valid born-digital pages, and repeated headers.
- [x] Implement deterministic page-level OCR routing. Do not OCR a healthy
  native text layer by default.
- [x] Benchmark Tesseract against PaddleOCR/PP-Structure on the approved corpus
  and select the smallest stack that meets the threshold.
- [x] Preserve native and OCR variants, confidence, engine/model version, and
  the rule that selected the authoritative variant.
- [x] Add deterministic OCR coverage and low-confidence warnings.
- [x] Define a strict `VisualExplanation` contract containing asset/node IDs,
  chart type, title, axes, measures, legend/series, visible trends or
  relationships, qualifications, extracted visible text, confidence, and
  unsupported/uncertain observations.
- [x] Add a `source-visual-explanation` LiteLLM alias mapped to Azure OpenAI;
  start evaluation with GPT-5.6 Luna image input and structured output.
- [x] Send only the chart/diagram crop plus bounded adjacent caption/context,
  never an unrelated full document.
- [x] Validate model statements against extracted chart text where possible and
  require uncertainty rather than invented values.
- [x] Attach the written explanation as a derived child/relationship of the
  visual node without replacing the original asset.
- [x] Verify observable mechanics: crop-only requests, bounded adjacent context,
  strict output, lineage attachment, and unsupported-number handling.

**Container verification:**

```bash
docker compose --profile test run --rm source-extraction-test python -m pytest tests/source_content/test_ocr.py tests/source_content/test_visual_explanations.py tests/source_content/test_extraction_worker.py -q
```

**Exit gate:** Mixed and scanned PDFs retain correct page order and readable
text; chart/diagram explanations retain their source asset and lineage and pass
the observable contract checks. Semantic interpretation quality is a model
capability limitation, not an extraction release gate.

### Phase 4 execution record

Completed on 2026-08-25.

- Verification: selective routing covers healthy, image-only, mixed,
  corrupt/sparse, rotated, and repeated-header-only pages. Visual client tests
  verify crop-only image input, same-extent context bounded at 2,000
  characters, strict output, lineage attachment, and unsupported-number
  handling. Eight focused extraction-container tests and ten Postgres repository
  tests pass; successful extraction transitions directly to `ready`.
- OCR benchmark: Tesseract and RapidOCR PP-OCRv6/ONNX both achieved 1.0 word
  recall on the scanned gold page. Tesseract took 0.740 seconds at 0.963 mean
  confidence; RapidOCR took 0.797 seconds at 1.000 mean confidence. Tesseract
  remains selected because it meets the threshold without adding ONNX Runtime
  to production; ONNX Runtime remains test-only.
- Model boundary: `source-visual-explanation` routes to GPT-5.6 Luna through
  the shared LiteLLM/Azure OpenAI path. Numeric statements absent from locally
  extracted chart text are removed from asserted measures/trends and retained
  as explicit uncertainty.
- Changed assumption: removed blinded human chart scoring and its fixture. It
  could not establish semantic correctness without a separate, more capable
  interpretation method and did not belong to the instructional designer role.
- Changed assumption: RapidOCR's packaged PP-OCRv6 models were used as the
  Paddle-family comparison instead of adding the larger PP-Structure stack;
  both candidates already met the approved OCR recall threshold.

---

## Phase 5 — Hierarchy-Aware Segmentation, Indexing, and Retrieval

**Purpose:** Make complete sources searchable without losing order or evidence
lineage.

- [x] Write focused tests for hierarchy boundaries, oversized nodes, atomic
  structures, overlap, token budgets, and node lineage.
- [x] Define strict `SourceSegment` and `RetrievalHit` contracts with ordered
  node IDs, locator range, token count, hierarchy path, source version, and
  collection identity.
- [x] Add idempotent source-collection and ordered-membership migrations and
  repository operations.
- [x] Segment by hierarchy first and token limit second; do not split tables,
  captions, or list structures unless the hard limit requires it.
- [x] Implement a single tokenizer/budget calculator for semantic
  source-content call.
- [x] Enforce the provisional 50,000 source-token ceiling while reserving prompt,
  schema, reasoning, and output capacity.
- [x] Add a purpose-specific source-segment embedding alias through LiteLLM and
  a separate Qdrant collection keyed by source version and node IDs.
- [x] Add exact lexical/node retrieval alongside vector retrieval; rerank only
  if evaluation demonstrates a need.
- [x] Persist segments and replace the source-version index before a successful
  extraction job becomes ready. Indexing failures propagate; warnings do not
  require human approval.
- [x] Make reindexing idempotent by extraction/index revision and remove
  stale points when a source is superseded or archived.
- [x] Add collection-scoped retrieval over one or multiple ordered sources while
  preserving each hit's origin and authority metadata.
- [x] Add focused retrieval checks for lexical evidence, semantic retrieval,
  exact nodes, stale replacement, source scoping, and collection metadata.

**Container verification:**

```bash
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_segmentation.py tests/source_content/test_source_index.py -q
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_source_retrieval.py -q
```

**Exit gate:** Every indexed segment resolves to ordered canonical nodes; inputs
larger than one model call are divided into bounded embedding requests; and
semantic, lexical, node, and collection retrieval preserve source lineage.

### Phase 5 execution record

Completed on 2026-08-25.

- Contracts: added strict versioned source-segment and retrieval-hit records with
  node IDs, hierarchy path, locator range, token count, collection identity, and
  authority metadata.
- Segmentation: uses `o200k_base`, a 1,200-token default segment size, 100-token
  hard-split overlap, and a shared source-token ceiling configured through
  `SOURCE_CONTENT_TRANCHE_TOKEN_LIMIT` (15,000 by default) and enforce the
  separate `SOURCE_CONTENT_REQUEST_TOKEN_LIMIT` (100,000 by default) when
  constructing model requests.
- Persistence and retrieval: added ordered Postgres source collections and a
  separate `source_segments` Qdrant collection with idempotent replacement,
  vector search, exact lexical matching, and exact node lookup.
- Worker integration: successful extraction persists `segments.json`, replaces
  that source version's index, and transitions to `ready` only afterward.
- Offline runtime: the extraction image preloads the `o200k_base` tokenizer data
  during image construction, alongside the Docling model artifacts.
- Verification: 22 focused Phase 5 tests passed in the API/Postgres container,
  9 Docling regression tests passed in the extraction container, and the
  LiteLLM route guardrail test passed. The in-memory Qdrant warning only notes
  that payload indexes affect server Qdrant, not its local test implementation.
- Changed assumption: no reranker or subjective retrieval-quality harness was
  added. The phase tests observable behavior; later corpus evaluation can justify
  more retrieval machinery if needed.

---

## Phase 6 — Hierarchical Document and Collection Mapping

**Purpose:** Build a complete, cited semantic map without sending the complete
source to one model call.

- [x] Define strict section-map, document-map, collection-map, claim, conflict,
  uncertainty, and coverage-ledger contracts.
- [x] Add `source-section-mapping` and `source-document-synthesis` model aliases
  using GPT-5.6 Luna; defer stronger-model comparison until a representative
  mapping evaluation corpus exists.
- [x] Map bounded hierarchy-coherent segments with direct node citations.
- [x] Combine child maps into parent maps deterministically by hierarchy level.
- [x] Retrieve original nodes before promoting any statement into a higher-level
  map.
- [x] Record which source nodes are represented, excluded, redundant,
  or unresolved; do not treat token presence as semantic coverage.
- [x] Build collection maps that retain per-source authority and surface
  agreement, overlap, conflict, version differences, and gaps.
- [x] Reject or qualify map claims whose cited evidence cannot be reassembled
  under the budget.
- [x] Persist prompt, alias, model response, token usage, hierarchy range, and
  map revision without copying restricted content into general logs.
- [x] Add deterministic resumability so completed section maps are reused after
  failure.
- [x] Test observable citation correctness, unsupported citations, secondary-topic
  preservation, hierarchy completeness, configured request bounds, token-usage
  capture, and resumability with deterministic model clients.

**Container verification:**

```bash
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_document_mapping.py -q
```

**Exit gate:** An over-context source or multi-source collection produces a
complete navigable map, every factual map claim resolves to source nodes, and
interrupted mapping resumes without repeating completed calls.

### Phase 6 execution record

Completed on 2026-08-25.

- Contracts: added strict cited claims, relationships, conflicts, uncertainties,
  coverage ledgers, section maps, document maps, and collection maps.
- Mapping: added bounded section calls and deterministic bottom-up synthesis that
  retrieves original cited nodes before promoting claims.
- Collections: retain source order and authority while explicitly representing
  agreements, overlaps, conflicts, version differences, gaps, and uncertainty.
- Persistence: added idempotent Postgres map artifacts containing the prompt
  template, model alias, input node IDs, token usage, map revision, and response.
  Completed section maps are reused after a later synthesis failure.
- Learning boundary: source mapping remains pedagogically neutral. Secondary
  concepts are preserved without deciding whether they warrant an objective,
  RLO, or assessment; those decisions begin in Phase 7.
- Verification: 47 source mapping, hierarchy, segmentation, retrieval, contract,
  and Postgres tests passed in the API container. The GPT-5.6 Luna routing check
  also passed.
- Changed assumption: no subjective mapping-quality fixture or live stronger-model
  comparison was invented for this phase. Those evaluations require a curated,
  representative corpus; the automated suite tests observable guarantees.

---

## Phase 7 — Optional Learning Brief and Objective Discovery

**Purpose:** Turn source maps into a bounded set of realistic, evidence-backed
learning opportunities without requiring practitioner context.

- [x] Define strict contracts for `LearningBrief`, `PractitionerLens`,
  `ObjectiveCandidate`, `ObjectiveEvidence`, critic findings, dependencies, and
  workspace revisions.
- [x] Add idempotent migrations and repository operations for learning briefs,
  objective workspaces, revisions, and objective decisions.
- [x] Support optional admin instructions for roles, tasks, decisions, risks,
  proficiency, priorities, exclusions, duration, service line, and industry.
- [x] When instructions are absent, generate a small set of clearly labeled
  lenses and assumptions; do not block the workflow.
- [x] Add purpose-specific aliases for lens proposal, objective proposal,
  evidence verification, and pedagogy critique.
- [x] Implement a bounded sequence: practice mapping → objective proposal →
  evidence retrieval → independent verification → pedagogy critique → duplicate
  grouping and ranking.
- [x] Cap the initial candidate set at 12 and record why candidates below the cap
  were selected; do not scale count with page count.
- [x] Require observable behavior, performance context, Bloom/performance level,
  scope, prerequisites, rationale, assumptions, expected effort, and direct
  evidence for every candidate.
- [x] Reject topic labels, compound objectives, unsupported Deloitte context,
  objectives that merely restate a heading, and candidates whose source support
  cannot be retrieved.
- [x] Preserve multiple-source evidence separately and surface conflicts rather
  than letting the model choose authority silently.
- [x] Add fake deterministic model clients for all normal tests and reserve live
  Azure evaluation for a controlled corpus.
- [x] Start all four purpose-specific routes with Luna and defer stronger-model
  comparison until a controlled practitioner/SME evaluation corpus exists.

**Container verification:**

```bash
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_learning_brief.py tests/source_content/test_objective_pipeline.py -q
```

**Exit gate:** With or without admin instructions, one selected source collection
produces no more than 12 typed candidates whose evidence resolves to nodes and
whose unsupported or redundant candidates are visibly rejected or grouped.

### Phase 7 execution record

Completed on 2026-08-25.

- Contracts: added optional practitioner instructions, inferred lenses, learning
  briefs, typed objective evidence, candidates, critic findings, duplicate
  groups, rejections, admin decisions, and versioned workspaces.
- Assessment boundary: objective-defining evidence may support assessment;
  supporting context may enrich later instruction but is structurally prohibited
  from expanding what the learner is assessed on.
- Pipeline: added bounded lens proposal, claim-batched objective proposal, exact
  evidence retrieval, independent verification, pedagogy critique, deterministic
  duplicate grouping, ranking, and the fixed 12-candidate cap.
- Grounding: unresolved, unsupported, invalid, duplicate, beyond-cap, and
  over-budget candidates remain visible as typed rejections. Multi-source
  evidence and known source conflicts remain separate.
- Persistence: added Postgres learning briefs, objective workspaces, immutable
  revisions, model metadata, and per-candidate admin decisions.
- Verification: 59 source mapping, retrieval, objective discovery, contract, and
  Postgres tests passed in the API container. The four Luna route checks passed.
- Changed assumption: no subjective objective-quality fixture or live
  Luna-versus-stronger-model comparison was invented. That evaluation requires
  a controlled corpus and practitioner/SME acceptance data.

---

## Phase 8 — RLO Evidence Schema

**Purpose:** Add portable claim-level lineage before generated RLOs enter the
existing catalog.

- [x] Write schema tests for single-source, multi-source, claim-level evidence,
  missing evidence, empty node references, source-version mismatch, duplicate
  evidence IDs, and excerpt integrity.
- [x] Extend the active prototype schema directly. Do not add historical
  migrations or legacy validation branches before the framework is a production
  contract.
- [x] Extend `Source` with ingested source identity, immutable checksum/version,
  and optional canonical locator without making internal object-store paths
  public citations.
- [x] Add a top-level evidence ledger containing evidence ID, source ID, node
  IDs, human-readable locator, optional bounded excerpt, excerpt hash, and usage
  note.
- [x] Add evidence references to the enabling objective, concepts, components,
  misconceptions, and assessment items/options at the minimum granularity
  required to verify their claims.
- [x] Validate that every evidence reference resolves to the declared source and
  evidence ledger.
- [x] Preserve existing bibliographic `source_refs` semantics; evidence uses a
  separate ledger and `evidence_refs` fields.
- [x] Update the shared RLO-to-`RLODocument` commissioning adapter so lineage is
  retained through downstream commissioning.
- [x] Update catalog embedding/index revision only for evidence fields that
  materially improve discovery; do not embed raw citation boilerplate.
- [x] Add JSON fixtures and schema documentation for one-source and multi-source
  RLOs.

**Container verification:**

```bash
docker compose run --rm learning-pipeline python -m pytest tests/test_validation.py tests/commissioning/test_rlo_adapter.py tests/validation/test_rlo_references.py -q
docker compose --profile test run --rm api-test python -m pytest api/tests/test_app_seed.py tests/source_content/test_rlo_evidence_schema.py -q
```

**Exit gate:** A multi-source RLO can trace objective, content, and assessment
claims to specific source versions and extracted node IDs, and commissioning
preserves that lineage.

### Phase 8 execution record

Completed on 2026-08-25.

- Contract: added immutable ingested-source identity, a claim-level evidence
  ledger, evidence roles, bounded hash-verified excerpts, and references from
  objectives, concepts, misconceptions, components, assessment items, and
  options.
- Assessment boundary: supporting context may enrich concepts and components
  but cannot define an objective or support an assessment item/option.
- Validation: added deterministic source/evidence reference checks, source
  version agreement, ID uniqueness, non-empty node pointers, and excerpt hash
  verification. Actual node existence remains a Phase 9 drafting-boundary check
  against the immutable extraction artifact rather than duplicating the full
  source hierarchy in each RLO.
- Commissioning: updated `RLODocument` and the shared adapter to preserve
  lineage. Existing prototype records still load as a consequence of additive
  defaults, but no migration or legacy compatibility machinery was added.
- Discovery: left the catalog embedding revision unchanged because citation
  boilerplate does not improve semantic RLO discovery.
- Documentation: added single- and multi-source coffee fixtures, including the
  distinction between machine-procedure evidence and soil/flavor context.
- Verification: 40 unique schema, API seed, commissioning, and RLO validation
  tests passed in the API and learning-pipeline containers.

---

## Phase 9 — Grounded RLO Drafting, Instructional Designer Review, and Publication

**Purpose:** Generate pedagogically complete draft RLOs from evidence-backed
objective candidates and publish only validated, instructional-designer-reviewed
versions.

- [x] Define `RLODraftRequest`, validation finding, review decision, and draft
  job-state contracts.
- [x] Add the idempotent RLO-draft-job migration and expected-state repository
  operations in this phase.
- [x] Snapshot the selected objective candidate, learning brief/lens, source collection,
  evidence, prompt version, and model aliases before generation.
- [x] Add purpose-specific Luna aliases for RLO drafting, evidence verification,
  and pedagogical review; defer a controlled stronger-model comparison to Phase 10.
- [x] Retrieve only the exact evidence selected for the approved candidate. Defer
  additional prerequisite or contradiction retrieval until those relationships
  are explicitly selected in the objective contract.
- [x] Generate exactly one RLO per selected enabling objective candidate using the shared
  schema rather than a parallel draft format.
- [x] Populate concepts, CDT components, misconceptions, assessment items,
  performance context, design brief, Gagné mapping, sources, evidence, rights,
  governance, accessibility, and targeting metadata.
- [x] Validate schema/cross-references deterministically before any semantic
  review call.
- [x] Independently verify every factual concept/component, misconception
  correction, example, and correct assessment answer against its evidence.
- [x] Validate objective/component/assessment alignment, atomicity, assessment
  correctness, prerequisite burden, and unsupported practitioner specificity.
- [x] Route model-owned revision findings through a bounded targeted repair;
  never let repair change source identity.
- [x] Provide an instructional designer draft review showing RLO fields beside source evidence,
  validation findings, and revision history.
- [x] Require explicit instructional designer approval and required governance values before
  invoking the existing RLO catalog ingestion boundary.
- [x] Persist the exact published RLO ID/version and retain the immutable draft
  and validation artifacts.
- [x] Define and implement source dependency behavior: archival, source-version
  supersession impact reporting, and deletion blocking/evidence retention for
  published RLOs.

**Container verification:**

```bash
docker compose --profile test run --rm api-test python -m pytest tests/source_content/test_rlo_drafting.py tests/source_content/test_rlo_grounding.py -q
docker compose run --rm learning-pipeline python -m pytest tests/commissioning tests/validation -q
docker compose --profile commissioning up -d --build
docker compose run --rm learning-pipeline python -m pytest tests/browser/test_rlo_draft_review.py -q
```

**Exit gate:** Each selected objective candidate yields one schema-valid,
evidence-complete draft; unsupported claims block approval; an instructional-
designer-approved draft enters the existing catalog with exact source lineage
and remains usable by commissioning.

### Phase 9 execution record

Completed on 2026-08-25.

- Contracts and persistence: added idempotent Postgres draft jobs, immutable
  revisions, validation findings, one-person instructional designer decisions,
  review history, expected-state transitions, and published dependencies.
- Generation: snapshots the selected objective, learning brief, exact source
  versions/nodes, evidence ledger, prompt version, and model aliases before one
  shared-schema RLO is drafted through LiteLLM.
- Validation: deterministically protects RLO identity, objective wording,
  source/evidence identity, claim evidence, rights, accessibility, and targeting;
  independent grounding and pedagogy passes run before a single bounded repair.
- Admin workflow: added an authenticated review page with a readable content
  preview, exact source excerpts, findings, advanced JSON revision, one
  instructional designer decision, history, and approved-only publication.
- Publication and retention: reuses the existing catalog ingestion boundary,
  records exact RLO/source-version dependencies, exposes impact reporting, and
  blocks deletion of source material used by a published RLO.
- Verification: 27 focused drafting, grounding, API, UI, and Postgres tests; 79
  broader API-owned tests; 116 commissioning/validation tests; and nine LiteLLM
  routing checks passed in containers. The live API was healthy and correctly
  gated the page and endpoint behind authentication.
- Changed assumption: the initial vertical slice executes drafting synchronously.
  Production queue recovery and controlled Luna-versus-stronger-model evaluation
  remain Phase 10 work rather than unmeasured Phase 9 quality claims.
- POC sandbox refinement: removed the separate objective-approval prerequisite;
  selecting a grounded candidate now starts drafting. Added an authenticated
  extraction inspector that pairs the original with ordered Docling nodes and
  exposes previews, visual explanations, diagnostics, segments, and raw
  artifacts. A single-source action runs mapping and objective discovery with
  optional lightweight practitioner context.

---

## Phase 10 — End-to-End Evaluation, Security, and Rollout

**Purpose:** Prove the complete workflow is reliable and operable before broader
use.

- [ ] Add an end-to-end container test from upload through catalog publication
  using fake model clients and representative PDF/PPTX fixtures.
- [ ] Run controlled live Azure evaluations for chart explanation, mapping,
  objectives, evidence verification, and RLO drafting.
- [ ] Report observable extraction diagnostics, retrieval quality, citation
  precision, unsupported claims, instructional designer edits/rejections,
  latency, token use, model cost, OCR rate, retries, and terminal outcomes.
- [ ] Test malformed PDFs/PPTX files, decompression bombs, oversized page
  dimensions, parser timeouts, prompt injection in source text, and unsupported
  embedded objects.
- [ ] Run extraction containers with bounded CPU/memory/time, read-only runtime
  filesystem where practical, and no unnecessary network access.
- [ ] Verify source authorization applies to originals, derivatives, previews,
  indexes, traces, workspaces, drafts, and downloads.
- [ ] Verify logs and Langfuse metadata contain identifiers and metrics but not
  restricted source bodies or credentials.
- [ ] Verify archive, supersession, retention, and permitted deletion propagate
  consistently through object storage, Postgres, Qdrant, caches, and drafts.
- [ ] Test worker crash recovery, stale leases, duplicate delivery,
  re-extraction, reindexing, model timeout, partial mapping, and resume.
- [ ] Add operational dashboards/queries for queue depth, stage age, failures,
  resource saturation, Azure usage, and quality warnings.
- [ ] Document image/model updates, schema migrations, benchmark execution,
  backup/restore, and incident recovery.
- [ ] Run the full repository test suite and browser smoke checks in containers.
- [ ] Record known limitations and obtain product/architecture acceptance for
  initial rollout.

**Container verification:**

```bash
docker compose --profile commissioning up -d --build
docker compose run --rm learning-pipeline python -m pytest -q
docker compose --profile test run --rm api-test python -m pytest -q
docker compose --profile test run --rm source-extraction-test python -m pytest tests/source_content -q
```

**Exit gate:** The measured end-to-end system meets its observable processing,
grounding, accessibility, security, reliability, latency, and cost thresholds;
semantic extraction limitations and operational recovery are documented; and no
known blocking finding remains.

### Phase 10 execution record

Not started.

---

## Global Acceptance Criteria

- [ ] Every accepted PDF/PPTX produces a complete ordered hierarchy or a visible
  blocking extraction finding.
- [ ] Scanned pages use selective OCR without replacing healthy native text.
- [ ] Charts and diagrams retain the original asset and a grounded written
  explanation.
- [ ] Every derived segment, map claim, objective, and RLO evidence entry
  resolves to stable nodes in an immutable source version.
- [ ] Documents larger than a model context window are processed completely
  through bounded hierarchical stages without silent truncation.
- [ ] Optional practitioner context improves relevance but is never required to
  start objective discovery.
- [ ] Objective generation returns a bounded, reviewable shortlist rather than
  one candidate per source topic.
- [ ] An RLO may cite one or multiple sources without losing claim origin or
  source authority.
- [ ] Every factual RLO claim and correct assessment answer is evidence-backed.
- [ ] Generated RLOs remain drafts until schema, evidence, pedagogy, governance,
  and instructional designer review gates pass.
- [ ] Published RLOs remain compatible with the existing catalog,
  commissioning, modality, production, and delivery pipelines.
- [ ] No source data is sent to a processing API other than the approved Azure
  OpenAI route through LiteLLM.
- [ ] Admin interfaces are authenticated, keyboard-complete, semantically
  structured, and understandable without styling.
- [ ] All required tests and smoke checks run in containers.

## Progress Log

| Date | Phase | Result | Evidence |
|---|---|---|---|
| 2026-08-24 | Plan created | 0 of 13 complete | Initial implementation plan derived from approved high-level direction |
| 2026-08-25 | Phase 4 | 5 of 11 complete | Removed extraction and objective review phases; retained mechanical extraction tests and one instructional designer RLO review gate |
| 2026-08-25 | Phase 5 | 6 of 11 complete | Added bounded hierarchy segmentation, ordered source collections, and source-linked hybrid retrieval |
| 2026-08-25 | Phase 9 | 10 of 11 complete | Added grounded RLO drafting, deterministic and semantic validation, one instructional designer review, catalog publication, and source dependency retention |
| 2026-08-25 | POC sandbox refinement | 10 of 11 complete | Exposed extraction artifacts, removed the objective approval gate, and connected single-source objective generation to RLO drafting |
