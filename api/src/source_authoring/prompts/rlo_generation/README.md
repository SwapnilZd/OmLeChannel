# RLO-generation prompt index

All production prompts for seven-part RLO generation live here. Edit the relevant
Markdown file and increment its declared version whenever behavior changes. The
application persists the exact prompt, input, structured output, hashes, model alias,
and token usage for every operation.

| Prompt ID | File | Version | LiteLLM alias | Output |
| --- | --- | --- | --- | --- |
| `source-rlo-target-classification` | `target_classification.md` + shared classification rules (v3) | v5 | `source-rlo-drafting` | `TargetPlanDraft` |
| `source-rlo-part-mapping` | `source_part_mapping.md` | v6 | `source-rlo-drafting` | `SourceMapDraft` |
| `source-rlo-mapping-challenge` | `source_mapping_challenge.md` | v4 | `source-rlo-grounding-review` | `MappingChallengeDraft` |
| `source-rlo-domain-enrichment` | `llm_domain_enrichment.md` | v3 | `source-rlo-domain-enrichment` | `LLMEnrichmentDraft` |
| `source-rlo-setup-generation` | `setup_generation.md` + `authoring_guidance_policy.md` (v1) | v7 | `source-rlo-drafting` | `PartGenerationDraft` |
| `source-rlo-teach-show-generation` | `teach_show_generation.md` + `authoring_guidance_policy.md` (v1) | v7 | `source-rlo-drafting` | `PartGenerationDraft` |
| `source-rlo-practice-check-generation` | `practice_check_generation.md` + `authoring_guidance_policy.md` (v1) | v11 | `source-rlo-drafting` | `PartGenerationDraft` |
| `source-rlo-sendoff-generation` | `sendoff_generation.md` + `authoring_guidance_policy.md` (v1) | v6 | `source-rlo-drafting` | `PartGenerationDraft` |
| `source-rlo-grounding-validation` | `grounding_validation.md` | v5 | `source-rlo-grounding-review` | `AuthoringReviewDraft` |
| `source-rlo-provenance-validation` | `provenance_validation.md` | v2 | `source-rlo-grounding-review` | `AuthoringReviewDraft` |
| `source-rlo-pedagogy-validation` | `pedagogy_validation.md` + shared classification rules (v3) | v11 | `source-rlo-pedagogy-review` | `AuthoringReviewDraft` |
| `source-rlo-targeted-repair` | `targeted_repair.md` | v10 | `source-rlo-drafting` | `PartGenerationDraft` |
| `source-rlo-collection-validation` | `collection_validation.md` | v3 | `source-rlo-pedagogy-review` | `CollectionReviewDraft` |

The four `legacy_catalog_*.md` assets keep the superseded catalog-shaped drafting
and JSON-edit validation path inspectable while that prototype API remains
available. They are not used by the seven-part generation worker.
