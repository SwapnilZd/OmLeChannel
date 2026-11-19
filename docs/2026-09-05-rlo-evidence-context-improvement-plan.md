# RLO Evidence Context Improvement Plan

## Goal

Ensure RLO mapping, generation, repair, and validation receive the complete source
spans that support each claim. Large tables and other structured elements must remain
readable without copying an entire source document into every model call or confusing
a context-packaging failure with genuinely insufficient source material.

This is a generalized pipeline correction. It must not contain logic tailored to a
particular document, standard, table, or objective.

## Current-state findings

The extraction itself is not imposing a 2,000-character limit:

- Docling exports complete table items to Markdown and the immutable extracted
  document retains that text.
- Source mapping currently reads source tranches of up to the configured 15,000-token
  limit.
- Ingestion also persists approximately 1,200-token `SourceSegment` records with
  stable segment IDs, node IDs, hierarchy paths, and locators.

The loss occurs after source mapping:

1. RLO mapping cites only node IDs, even when a node was divided into chunks.
2. `_excerpt()` reconstructs evidence from the complete node and blindly keeps its
   first 2,000 characters.
3. The portable `Evidence` schema also limits `excerpt` to 2,000 characters.
4. Grounding validation receives the authoring payload containing that shortened
   excerpt, rather than the exact source span that the mapper read.
5. A repair pass can then interpret missing evidence text as missing source content
   and mark the RLO `source_insufficient`.

The observed failure illustrates why character limits are unsuitable. The relevant
table node is 4,499 characters but only 381 `o200k_base` tokens. Its first data row
starts after character 2,250, so the 2,000-character excerpt contains only the header
and Markdown separator even though the complete table easily fits in a model request.

The repository pins Docling 2.119.0. That version includes `HybridChunker`, which
performs hierarchy-aware, token-aware splitting and supports repeated table headers.
The current adapter does not use it; it flattens Docling items and applies the
repository's generic token splitter afterward.

## Design decisions

### 1. Cite exact source segments, not an ambiguous portion of a node

`node_id` remains the canonical link to the extracted document hierarchy. A
`segment_id` identifies the exact bounded text supplied to a model. Claims and RLO
evidence will retain both:

- node IDs for document lineage and page/slide inspection;
- segment IDs for exact model-readable grounding;
- source-version ID to prevent cross-version citation drift; and
- a hash of the selected text.

The service, not the model, resolves segment IDs to text and validates that every
segment belongs to the cited source version and node.

### 2. Use token budgets for model context

Remove the character-based evidence limit. Each source segment remains bounded by the
existing ingestion segment token limit, while the complete evidence packet is bounded
by the existing source-request token budget. A claim may cite multiple segments.

If all selected evidence does not fit in one validation request, validation will run
over deterministic claim groups and aggregate findings. It will not truncate evidence
silently.

### 3. Separate portable evidence from model context assembly

The canonical RLO stores precise lineage and bounded, hash-verified excerpts. The
generation service assembles model context by resolving those segment references from
immutable extraction artifacts. UI inspection can fetch the same exact spans on
demand.

This prevents the size of a convenient preview field from becoming the factual limit
of generation or validation.

### 4. Treat evidence transport failures as system failures

Missing, corrupt, mismatched, or truncated evidence is not proof that the source is
insufficient. Those conditions must produce a retryable evidence-context error.
`source_insufficient` remains a semantic outcome used only when valid source spans
were reviewed and do not support the approved objective.

## Phased implementation

### Phase 1: Add a precise evidence-span contract

- [x] Use the versioned `SourceSegment` evidence-span contract containing source version,
  segment ID, node IDs, locator range, token count, text hash, and text.
- [x] Extend source-mapping citations to return allowed segment IDs in addition to
  source version and node lineage.
- [x] Derive node IDs from the cited segments and reject invented, mismatched, or
  ambiguous segment references deterministically.
- [x] Extend the RLO evidence contract with exact segment references and remove the
  2,000-character schema restriction.
- [x] Continue hashing the actual excerpt stored in the RLO.
- [ ] Version affected persisted contracts directly; existing prototype RLOs do not
  require a compatibility adapter.

**Exit gate:** Two different chunks from the same large node can be cited and resolved
independently without relying on character offsets or a node prefix.

### Phase 2: Produce structure-aware source segments

- [x] Run Docling's `HybridChunker` while the `DoclingDocument` is available for PDF
  and PPTX extraction.
- [x] Configure its `OpenAITokenizer` with `o200k_base` and the existing segment token
  limit so token accounting matches the rest of the source pipeline.
- [x] Enable repeated table headers and overflow handling so every split table span
  retains its column context without discarding a wide data row.
- [x] Map Docling chunk metadata and document-item references back to stable canonical
  node IDs, hierarchy paths, and page/slide locators.
- [x] Retain a hierarchy-aware fallback for non-Docling sources such as EPUB; make its
  table path line-aware and repeat table headers when a table must be divided.
- [ ] Record the segmenter name, configuration, and artifact revision in the immutable
  extraction manifest.
- [ ] Rebuild derived segment artifacts from stored canonical extraction data where
  possible; do not rerun OCR merely to change chunking.

**Exit gate:** Oversized tables split on meaningful boundaries, every table span is
within its token budget, and each span independently identifies its headers, source
node, and locator.

### Phase 3: Use persisted segments throughout RLO generation

- [x] Load verified `segments.json` alongside each source document in
  `DraftSourceMaterial`.
- [x] Replace the generation service's independent node rechunking with deterministic
  batches of persisted source segments under the configured 15,000-token tranche
  limit.
- [x] Include stable segment IDs in mapping prompts and require mapped claims to cite
  those IDs.
- [x] Build normalized RLO evidence from cited segment text rather than from the first
  characters of the parent node.
- [x] Persist selected and rejected segment IDs in the normalized source-map
  checkpoint for inspection and replay.
- [x] Preserve objective evidence by resolving its node references to the relevant
  persisted segments before RLO generation begins.

**Exit gate:** The exact text seen during source mapping is the text recoverable from
the resulting claim and evidence records.

### Phase 4: Assemble complete, bounded validation context

- [ ] Add one deterministic evidence-context builder used by generation challenge,
  grounding review, pedagogy review where needed, and targeted repair.
- [x] Supply each operation with the claims it is reviewing and the complete cited
  segment text, qualifications, source version, and locators.
- [ ] Pack claim groups up to the existing source-request token limit and make multiple
  calls when necessary.
- [ ] Aggregate findings by stable claim and element IDs and deduplicate repeated
  findings from overlapping evidence.
- [x] Fail before a model call when evidence hashes or segment ownership do not
  validate.
- [x] Prevent targeted repair from converting evidence-context errors into
  `source_insufficient`.
- [ ] Record evidence packet IDs, token counts, and prompt snapshots in the existing
  generation checkpoints.

**Exit gate:** No validator or repair operation receives a cited claim without its
resolvable source text, and no operation silently shortens that text.

### Phase 5: Improve admin inspection and operational diagnosis

- [x] Show the exact cited segment or segments in Source Lineage, with an expandable
  full-text view and page/slide locator.
- [ ] Identify table chunks and show repeated headers with their selected rows.
- [ ] Distinguish `source_insufficient`, `evidence_context_invalid`, and ordinary
  validation findings in job status and review UI.
- [ ] Display evidence-packet token counts and segment counts in the sandbox trace.
- [ ] Keep portable RLO payloads readable by loading larger source spans on demand
  rather than rendering all evidence expanded by default.

**Exit gate:** An admin can tell whether the source lacks support, retrieval selected
the wrong span, or the pipeline failed to transport otherwise valid evidence.

## Verification plan

All automated and smoke verification will run in containers.

- [x] Add a synthetic Markdown-table regression fixture whose separator pushes the
  first data row beyond 2,000 characters while the table remains well below the token
  limit.
- [x] Verify that a mapped claim, generated content, grounding validator, and repair
  pass all receive the relevant row from that fixture.
- [x] Add an oversized-table fixture that must produce multiple chunks with repeated
  headers and intact rows.
- [x] Verify precise citation when multiple segments share one node ID and overlap.
- [x] Verify ordinary paragraphs, headings, lists, PDF tables, PPTX tables, and EPUB
  tables preserve ordering and lineage.
- [ ] Verify an evidence packet larger than one request becomes multiple bounded
  validation calls with complete aggregated findings.
- [x] Verify missing or hash-mismatched segments produce a retryable system failure,
  not `source_insufficient`.
- [ ] Re-run a representative end-to-end objective-to-RLO job and inspect prompt
  snapshots to confirm exact selected text is present at mapping, generation,
  validation, and repair stages.

## Success criteria

- No model-facing evidence is limited by a fixed character prefix.
- Every generated substantive claim and assessment answer resolves to exact immutable
  source segments.
- Large structured elements remain readable within configurable token budgets.
- Validation can process evidence larger than one request through bounded calls.
- Source insufficiency reflects source semantics, not lost or malformed context.
- The solution behaves consistently across sources and contains no document-specific
  rules.

## References

- [Docling chunking concepts](https://docling-project.github.io/docling/concepts/chunking/)
- [Docling hybrid chunking example](https://docling-project.github.io/docling/_generated/examples/hybrid_chunking/)
- [Docling advanced chunking and serialization](https://docling-project.github.io/docling/_generated/examples/advanced_chunking_and_serialization/)
- [DoclingDocument reference](https://docling-project.github.io/docling/reference/docling_document/)
