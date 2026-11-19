# Objective-extraction prompt index

All production prompts for learning-objective extraction live in this directory.
Application services load these Markdown assets through `prompt_assets.py`; they do
not keep alternate prompt text in Python.

| Prompt ID | File | Status | Operation | LiteLLM alias | Structured output |
|---|---|---|---|---|---|
| `source-objective-practitioner-lenses` | `practitioner_lenses.md` (v4) | Executed | Infer source-supported practitioner relevance across Deloitte businesses, specialties, and role levels when Learning Development Services context is absent or incomplete | `source-practitioner-lens` | `LensDraft` |
| `source-objective-curriculum-blueprint` | `document_curriculum_blueprint.md` (v1) | Executed before candidate discovery | Preserve central purpose, ordered instructional domains, importance, and source boundaries across bounded discovery calls | `source-objective-proposal` | `CurriculumBlueprintDraft` |
| `source-objective-structured-signals` | `structured_signal_detection.md` (v2) + decomposition rules (v2) | Executed | Find objective signals in structured material | `source-objective-proposal` | `SignalDetectionDraft` |
| `source-objective-feature-inventory` | `source_feature_inventory.md` (v3) | Executed | Inventory useful source-native instructional features before candidates exist | `source-objective-proposal` | `SourceFeatureDraft` |
| `source-objective-decomposition-rules` | `decomposition_rules.md` (v2) | Included in signal detection and candidate formation | Apply D-1 through D-19 as executable rules | n/a | n/a |
| `source-objective-candidate-formation` | `candidate_formation.md` (v11) + decomposition rules (v2) | Executed iteratively | Form materially new, independently assessable candidates within the five POC2 performance families | `source-objective-proposal` | `ObjectiveProposalDraft` |
| `source-objective-classification-rules` | `classification_rules.md` (v3) | Included in Suggested, Target, and Observed classification | Apply the five-cell POC2 rubric consistently | n/a | n/a |
| `source-objective-classification` | `objective_classification.md` (v5) + classification rules (v3) | Executed once per candidate | Return a supported five-cell classification or an explicit outside-scope result | `source-objective-proposal` | `ObjectiveClassificationDraft` |
| `source-objective-classification-repair` | `objective_classification_repair.md` (v3) + classification rules (v3) | Executed at most once after an invalid classification | Repair classification output without forcing an outside-scope objective into a permitted cell | `source-objective-proposal` | `ObjectiveClassificationDraft` |
| `source-objective-set-coverage-review` | `objective_set_coverage_review.md` (v4) | Executed after initial discovery and once after gap discovery | Assess central-purpose alignment and produce atomic, source-linked missing-performance targets | `source-objective-proposal` | `CurriculumCoverageDraft` |
| `source-objective-coverage-gap-discovery` | `coverage_gap_discovery.md` (v6) | Executed once per eligible missing-performance target in a fixed sweep | Propose in-scope objectives that directly address one named, source-supported target | `source-objective-proposal` | `CoverageGapDraft` |
| `source-related-objective-discovery` | `related_objective_discovery.md` (v2) | Executed once per source-insufficient, non-peripheral target | Propose high-value, in-scope practitioner objectives related to, but not fully supported by, the source | `source-related-objective-discovery` | `RelatedObjectiveDraft` |
| `source-objective-support-assessment` | `objective_support_assessment.md` (v1) | Executed once per related proposal | Reject topic-only adjacency and record source contribution, missing knowledge, and expected LLM contribution | `source-related-objective-discovery` | `ObjectiveSupportAssessmentDraft` |
| `source-objective-gap-target-alignment` | `gap_target_alignment.md` (v1) | Executed for each focused gap proposal | Distinguish direct target resolution, useful supporting material, and off-target material | `source-objective-evidence-verification` | `GapTargetAlignment` |
| `source-objective-candidate-reconciliation` | `candidate_reconciliation.md` | Reserved | Critique an LDS-approved candidate set during a later detail stage | Not wired before initial review | Future `PedagogyCritique` |
| `source-objective-evidence-verification` | `evidence_verification.md` | Reserved | Verify an LDS-approved candidate set during a later detail stage | Not wired before initial review | Future `EvidenceVerification` |
| `source-objective-sme-signals` | `sme_signal_detection.md` | Reserved | Detect intent signals in a future SME-input path | Not wired | Future contract |
| `source-objective-detail-enrichment` | `detail_enrichment.md` | Deprecated reference | Superseded by the single Objective + Source Review gate | Not wired | None |

Edit the relevant file and increment its declared version whenever behavior changes.
Every model call persists the prompt ID, version, SHA-256 hash, exact prompt text,
exact structured input, model alias, and versioned output-contract name.
Candidate-formation runs have pass-specific operation names. Their persisted input
contains the exact compact memory and uncovered claim IDs supplied to that pass.
