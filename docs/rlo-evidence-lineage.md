# RLO evidence lineage

RLOs generated from ingested content keep bibliographic sources and claim-level evidence separate:

- `sources[].reference` and `concepts[].source_refs` remain human-readable bibliography.
- An ingested source also records its stable source ID, immutable version ID, checksum, and optional canonical locator.
- `evidence[]` points to exact extracted node IDs, the token-bounded source segments
  supplied to models, and a human-readable page or slide location. Its excerpt is the
  complete cited segment text and is protected by a SHA-256 hash.
- Objectives, concepts, misconceptions, components, assessment items, and assessment options use `evidence_refs` to identify the evidence supporting their claims.

`objective_defining` evidence may define the objective and assessment boundary. `supporting_context` may enrich instruction but cannot support an objective, assessment item, or assessment option. For example, a coffee-machine manual can support testing the machine procedure, while information about Colombian soil may add flavor context without creating soil-science exam questions.

The portable RLO validates evidence and source references, source-version agreement,
unique IDs, and excerpt hashes. Grounded RLO drafting additionally verifies that each
segment belongs to the cited immutable source version and nodes. The RLO does not
duplicate the complete extracted document hierarchy or use a character prefix as
model context.

The current RLOs are prototypes. These fields extend the active contract directly; no historical schema migration or legacy compatibility layer is being introduced. Future RLO revision and reprocessing work is tracked in `BACKLOG.md`.
