"""Bounded, evidence-backed learning-objective discovery."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any

from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    load_lite_llm_settings,
)
from openai import OpenAI
from pydantic import Field, ValidationError, model_validator

from src.source_ingestion.contracts import CollectionMap, ExtractedDocument, MapClaim, StrictModel
from src.source_ingestion.segmentation import SourceTokenBudget, TokenBudgetExceeded

from . import repository
from .cell_scope import is_poc2_cell
from .contracts import (
    CandidateCoverageAssignment,
    CriticFinding,
    CurriculumCoverageRole,
    CurriculumCoverageReport,
    CurriculumCoverageState,
    CurriculumDomain,
    CurriculumDomainCoverage,
    CurriculumFragmentationFinding,
    CurriculumGapCandidateRejection,
    CurriculumGapDiscoveryRecord,
    CurriculumGapTarget,
    CurriculumGapTargetDiscoveryRecord,
    CurriculumImportance,
    DecompositionSignal,
    DocumentCurriculumBlueprint,
    EvidenceRole,
    GapEvidenceSufficiency,
    GapTargetAlignment,
    GapTargetAlignmentState,
    LearningBrief,
    ObjectiveClassification,
    ObjectiveCandidate,
    ObjectiveConfidence,
    ObjectiveContentType,
    ObjectiveDiscoveryBasis,
    ObjectiveEvidence,
    ObjectiveRejection,
    ObjectiveScopeStatus,
    ObjectiveSupportProfile,
    ObjectiveWorkspace,
    PractitionerInstructions,
    PractitionerLens,
    SourceFeature,
    SourceFeatureStatus,
    SourceFeatureType,
    SourceSupportLevel,
)
from .prompt_assets import PromptAsset, compose_prompt_asset, load_prompt_asset


OBJECTIVE_ID_NAMESPACE = uuid.UUID("ba23cc9b-a4c7-43b5-9a93-c3dcbd74f313")
MAX_DISCOVERY_PASSES = 4
DISCOVERY_MEMORY_LIMIT = 100
LENS_MODEL = ModelAlias.SOURCE_PRACTITIONER_LENS
PROPOSAL_MODEL = ModelAlias.SOURCE_OBJECTIVE_PROPOSAL
TARGET_ALIGNMENT_MODEL = ModelAlias.SOURCE_OBJECTIVE_EVIDENCE_VERIFICATION
RELATED_OBJECTIVE_MODEL = ModelAlias.SOURCE_RELATED_OBJECTIVE_DISCOVERY


class InvalidGapAlignment(ValueError):
    """A single gap-alignment result cannot be safely retained."""


LENS_PROMPT = load_prompt_asset(
    "practitioner_lenses.md",
    prompt_id="source-objective-practitioner-lenses",
    version="v4",
)
DECOMPOSITION_RULES = load_prompt_asset(
    "decomposition_rules.md",
    prompt_id="source-objective-decomposition-rules",
    version="v2",
)
CLASSIFICATION_RULES = load_prompt_asset(
    "classification_rules.md",
    prompt_id="source-objective-classification-rules",
    version="v3",
)
PROPOSAL_PROMPT = compose_prompt_asset(
    load_prompt_asset(
        "candidate_formation.md",
        prompt_id="source-objective-candidate-formation",
        version="v11",
    ),
    DECOMPOSITION_RULES,
)
CLASSIFICATION_PROMPT = compose_prompt_asset(
    load_prompt_asset(
        "objective_classification.md",
        prompt_id="source-objective-classification",
        version="v5",
    ),
    CLASSIFICATION_RULES,
)
CLASSIFICATION_REPAIR_PROMPT = compose_prompt_asset(
    load_prompt_asset(
        "objective_classification_repair.md",
        prompt_id="source-objective-classification-repair",
        version="v3",
    ),
    CLASSIFICATION_RULES,
)
BLUEPRINT_PROMPT = load_prompt_asset(
    "document_curriculum_blueprint.md",
    prompt_id="source-objective-curriculum-blueprint",
    version="v1",
)
COVERAGE_PROMPT = load_prompt_asset(
    "objective_set_coverage_review.md",
    prompt_id="source-objective-set-coverage-review",
    version="v4",
)
GAP_PROMPT = load_prompt_asset(
    "coverage_gap_discovery.md",
    prompt_id="source-objective-coverage-gap-discovery",
    version="v6",
)
TARGET_ALIGNMENT_PROMPT = load_prompt_asset(
    "gap_target_alignment.md",
    prompt_id="source-objective-gap-target-alignment",
    version="v1",
)
RELATED_OBJECTIVE_PROMPT = load_prompt_asset(
    "related_objective_discovery.md",
    prompt_id="source-related-objective-discovery",
    version="v2",
)
SUPPORT_ASSESSMENT_PROMPT = load_prompt_asset(
    "objective_support_assessment.md",
    prompt_id="source-objective-support-assessment",
    version="v1",
)
SIGNAL_PROMPT = compose_prompt_asset(
    load_prompt_asset(
        "structured_signal_detection.md",
        prompt_id="source-objective-structured-signals",
        version="v2",
    ),
    DECOMPOSITION_RULES,
)
FEATURE_PROMPT = load_prompt_asset(
    "source_feature_inventory.md",
    prompt_id="source-objective-feature-inventory",
    version="v3",
)


class LensDraft(StrictModel):
    lenses: list[PractitionerLens] = Field(min_length=1, max_length=4)
    assumptions: list[str] = Field(default_factory=list)


class ProposedEvidenceUse(StrictModel):
    claim_id: str = Field(min_length=1)
    role: EvidenceRole
    rationale: str = Field(min_length=1)


class ProposedObjective(StrictModel):
    candidate_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    observable_behavior: str = Field(min_length=1)
    performance_context: str = Field(min_length=1)
    practitioner_relevance: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    confidence: ObjectiveConfidence
    confidence_rationale: str = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)
    terminal_outcome: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    expected_effort_minutes: int = Field(ge=1)
    evidence_uses: list[ProposedEvidenceUse] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    selected_reason: str = Field(min_length=1)
    priority: int = Field(ge=1)
    source_feature_ids: list[str] = Field(default_factory=list)
    support_profile: ObjectiveSupportProfile | None = None


class ProposedSourceFeature(StrictModel):
    feature_id: str = Field(min_length=1)
    feature_type: SourceFeatureType
    status: SourceFeatureStatus
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_uses: list[ProposedEvidenceUse] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)


class ProposedSignal(StrictModel):
    signal_id: str = Field(min_length=1)
    rule_id: str = Field(pattern=r"^D-(?:[1-9]|1[0-9])$")
    signal_type: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    confidence: ObjectiveConfidence
    evidence_uses: list[ProposedEvidenceUse] = Field(min_length=1)


class SignalDetectionDraft(StrictModel):
    signals: list[ProposedSignal] = Field(default_factory=list)


class SourceFeatureDraft(StrictModel):
    source_features: list[ProposedSourceFeature] = Field(default_factory=list)


class ObjectiveProposalDraft(StrictModel):
    candidates: list[ProposedObjective] = Field(default_factory=list)
    signals: list[ProposedSignal] = Field(default_factory=list)
    source_features: list[ProposedSourceFeature] = Field(default_factory=list)


class CurriculumDomainDraft(StrictModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    importance: CurriculumImportance
    rationale: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    hierarchy_refs: list[str] = Field(default_factory=list)


class CurriculumBlueprintDraft(StrictModel):
    central_purpose: str = Field(min_length=1)
    central_claim_ids: list[str] = Field(min_length=1)
    intended_use: str = Field(min_length=1)
    boundaries: list[str] = Field(default_factory=list)
    domains: list[CurriculumDomainDraft] = Field(min_length=1)
    integrative_performances: list[str] = Field(default_factory=list)
    reference_topics: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class CurriculumGapTargetDraft(StrictModel):
    performance: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_sufficiency: GapEvidenceSufficiency
    sufficiency_rationale: str = Field(min_length=1)
    search_warranted: bool


class CurriculumDomainCoverageDraft(StrictModel):
    domain_id: str = Field(min_length=1)
    state: CurriculumCoverageState
    candidate_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    gap_targets: list[CurriculumGapTargetDraft] = Field(default_factory=list)


class CurriculumCoverageDraft(StrictModel):
    assignments: list[CandidateCoverageAssignment] = Field(default_factory=list)
    domain_coverage: list[CurriculumDomainCoverageDraft] = Field(min_length=1)
    peripheral_candidate_ids: list[str] = Field(default_factory=list)
    fragmentation_findings: list[CurriculumFragmentationFinding] = Field(
        default_factory=list
    )
    missing_integrative_performances: list[str] = Field(default_factory=list)
    source_insufficiencies: list[str] = Field(default_factory=list)
    reviewer_questions: list[str] = Field(default_factory=list)


class CoverageGapDraft(StrictModel):
    target_id: str = Field(min_length=1)
    candidates: list[ProposedObjective] = Field(default_factory=list)


class CoverageGapSweep(StrictModel):
    proposals: list[ProposedObjective] = Field(default_factory=list)
    records: list[CurriculumGapDiscoveryRecord] = Field(default_factory=list)


class RelatedObjectiveDraft(StrictModel):
    target_id: str = Field(min_length=1)
    candidates: list[ProposedObjective] = Field(default_factory=list)


class ObjectiveSupportAssessmentDraft(StrictModel):
    candidate_id: str = Field(min_length=1)
    accepted: bool
    support_profile: ObjectiveSupportProfile | None = None
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def accepted_candidate_has_support(self) -> "ObjectiveSupportAssessmentDraft":
        if self.accepted and self.support_profile is None:
            raise ValueError("accepted related objectives require a support profile")
        if not self.accepted and not self.rejection_reason:
            raise ValueError("rejected related objectives require a reason")
        return self


class ObjectiveClassificationDraft(StrictModel):
    candidate_id: str = Field(min_length=1)
    scope_status: ObjectiveScopeStatus = ObjectiveScopeStatus.SUPPORTED
    classification: ObjectiveClassification | None = None
    scope_reason: str | None = None

    @model_validator(mode="after")
    def scope_result_is_consistent(self):
        if self.scope_status == ObjectiveScopeStatus.SUPPORTED:
            if self.classification is None:
                raise ValueError("supported objectives require classification")
            if not is_poc2_cell(
                self.classification.content_kind.value,
                self.classification.bloom.value,
            ):
                raise ValueError("classification is outside the five POC2 cells")
            for cell in self.classification.plausible_alternative_cells:
                kind, bloom = cell.split("-", 1)
                if not is_poc2_cell(kind, bloom):
                    raise ValueError(
                        "classification alternative is outside the five POC2 cells"
                    )
        elif self.scope_status == ObjectiveScopeStatus.OUTSIDE_POC2_SCOPE:
            if self.classification is not None:
                raise ValueError("outside-scope objectives cannot have classification")
            if not self.scope_reason:
                raise ValueError("outside-scope objectives require a reason")
        else:
            raise ValueError("model classification cannot return needs_review")
        return self


class EvidenceVerification(StrictModel):
    candidate_id: str = Field(min_length=1)
    supported: bool
    unsupported_parts: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class PedagogyCritique(StrictModel):
    candidate_id: str = Field(min_length=1)
    accepted: bool
    findings: list[CriticFinding] = Field(default_factory=list)
    duplicate_group: str | None = None
    recommended_rank: int = Field(ge=1)


class RepositoryWorkspaceStore:
    def load(self, workspace_id: str) -> ObjectiveWorkspace | None:
        return repository.get_objective_workspace(workspace_id)

    def save_brief(self, brief: LearningBrief) -> LearningBrief:
        return repository.save_learning_brief(brief)

    def model_metadata(self, workspace_id: str, revision: int) -> dict:
        return repository.get_workspace_model_metadata(workspace_id, revision)

    def save_workspace(
        self,
        workspace: ObjectiveWorkspace,
        *,
        created_by: str | None,
        model_metadata: dict,
    ) -> ObjectiveWorkspace:
        repository.create_objective_workspace(
            workspace.workspace_id,
            workspace.collection_id,
            created_by=created_by,
        )
        return repository.save_workspace_revision(
            workspace,
            model_metadata=model_metadata,
        )


def _stable_id(kind: str, *values: str) -> str:
    return str(uuid.uuid5(OBJECTIVE_ID_NAMESPACE, ":".join((kind, *values))))


def _usage(response) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        key: value
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance((value := getattr(usage, key, None)), int)
    }


class ObjectiveDiscoveryService:
    def __init__(
        self,
        *,
        client=None,
        store=None,
        token_budget=None,
        progress_callback=None,
        findings_callback=None,
        checkpoint_loader=None,
        checkpoint_saver=None,
    ) -> None:
        settings = load_lite_llm_settings(required=False)
        self.client = client or OpenAI(base_url=settings.base_url, api_key=settings.api_key)
        self.store = store or RepositoryWorkspaceStore()
        self.token_budget = token_budget or SourceTokenBudget()
        self.model_usage: dict[str, list[dict[str, int]]] = defaultdict(list)
        self.prompt_runs: list[dict[str, str]] = []
        self.progress_callback = progress_callback
        self.findings_callback = findings_callback
        self.checkpoint_loader = checkpoint_loader
        self.checkpoint_saver = checkpoint_saver

    def _publish_preliminary_findings(
        self,
        draft: ObjectiveProposalDraft,
        *,
        batches_completed: int,
        batch_count: int,
        discovery_pass: int,
        new_candidates: int,
    ) -> None:
        if not self.findings_callback:
            return
        self.findings_callback(
            {
                "preliminary_candidates": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "statement": candidate.statement,
                        "confidence": str(candidate.confidence),
                        "practitioner_relevance": candidate.practitioner_relevance,
                    }
                    for candidate in draft.candidates
                ],
                "preliminary_candidate_count": len(draft.candidates),
                "preliminary_feature_count": len(draft.source_features),
                "preliminary_signal_count": len(draft.signals),
                "discovery_batches_completed": batches_completed,
                "discovery_batch_count": batch_count,
                "discovery_pass_completed": discovery_pass,
                "new_candidates_this_pass": new_candidates,
                "findings_status": "unverified",
            }
        )

    def _parse(
        self,
        *,
        model: ModelAlias,
        operation: str,
        prompt: PromptAsset,
        content: dict[str, Any],
        text_format,
        job_id: str,
    ):
        serialized = json.dumps(content, separators=(",", ":"), sort_keys=True)
        self.token_budget.require_within_limit(serialized)
        input_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        output_schema = f"{text_format.__name__}:v1"
        if self.progress_callback:
            self.progress_callback(operation, "running")
        checkpoint = (
            self.checkpoint_loader(
                job_id,
                operation=operation,
                model_alias=str(model),
                prompt_sha256=prompt.sha256,
                input_sha256=input_sha256,
                output_schema=output_schema,
            )
            if self.checkpoint_loader
            else None
        )
        if checkpoint is not None:
            parsed = text_format.model_validate(checkpoint)
        else:
            response = self.client.responses.parse(
                model=model,
                metadata=build_litellm_metadata(model, operation=operation, job_id=job_id),
                extra_headers=build_langfuse_headers(model, operation=operation, job_id=job_id),
                input=[
                    {"role": "system", "content": prompt.text},
                    {"role": "user", "content": serialized},
                ],
                text_format=text_format,
            )
            if response.output_parsed is None:
                raise ValueError("model returned no objective-discovery result")
            parsed = text_format.model_validate(
                response.output_parsed.model_dump(mode="json")
            )
            if self.checkpoint_saver:
                self.checkpoint_saver(
                    job_id,
                    operation=operation,
                    model_alias=str(model),
                    prompt_sha256=prompt.sha256,
                    input_sha256=input_sha256,
                    output_schema=output_schema,
                    output_payload=parsed.model_dump(mode="json"),
                )
            self.model_usage[str(model)].append(_usage(response))
        if self.progress_callback:
            self.progress_callback(operation, "completed")
        self.prompt_runs.append(
            {
                "prompt_run_id": str(uuid.uuid4()),
                "prompt_id": prompt.prompt_id,
                "prompt_version": prompt.version,
                "prompt_sha256": prompt.sha256,
                "prompt_filename": prompt.filename,
                "prompt_snapshot": prompt.text,
                "operation": operation,
                "model_alias": str(model),
                "input_sha256": input_sha256,
                "input_snapshot": serialized,
                "input_artifact_ref": f"inline-sha256:{input_sha256}",
                "output_schema": output_schema,
            }
        )
        return parsed

    def _brief_revision(
        self,
        collection_map: CollectionMap,
        instructions: PractitionerInstructions | None,
    ) -> str:
        value = json.dumps(
            instructions.model_dump(mode="json") if instructions else {},
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(value.encode()).hexdigest()[:12]
        return f"{collection_map.map_revision}:{digest}"

    def create_learning_brief(
        self,
        collection_map: CollectionMap,
        instructions: PractitionerInstructions | None = None,
    ) -> LearningBrief:
        revision = self._brief_revision(collection_map, instructions)
        draft = self._parse(
            model=LENS_MODEL,
            operation="propose-lenses",
            prompt=LENS_PROMPT,
            content={
                "collection_id": collection_map.collection_id,
                "claims": [claim.model_dump(mode="json") for claim in collection_map.claims],
                "agreements": collection_map.agreements,
                "conflicts": [
                    conflict.model_dump(mode="json") for conflict in collection_map.conflicts
                ],
                "gaps": collection_map.gaps,
                "admin_instructions": instructions.model_dump(mode="json")
                if instructions
                else None,
            },
            text_format=LensDraft,
            job_id=collection_map.collection_id,
        )
        lenses = [
            lens.model_copy(update={"inferred": instructions is None}) for lens in draft.lenses
        ]
        brief = LearningBrief(
            brief_id=_stable_id("brief", collection_map.map_id, revision),
            collection_id=collection_map.collection_id,
            instructions=instructions,
            lenses=lenses,
            assumptions=draft.assumptions,
            exclusions=instructions.exclusions if instructions else [],
            source_map_revision=collection_map.map_revision,
            brief_revision=revision,
        )
        return self.store.save_brief(brief)

    def _resolve_evidence(
        self,
        proposal: ProposedObjective,
        claims: dict[str, MapClaim],
        documents: dict[str, ExtractedDocument],
    ) -> tuple[list[ObjectiveEvidence], list[str]]:
        evidence = []
        errors = []
        for use in proposal.evidence_uses:
            claim = claims.get(use.claim_id)
            if claim is None:
                errors.append(f"unknown_claim:{use.claim_id}")
                continue
            for citation_index, citation in enumerate(claim.citations):
                document = documents.get(citation.source_version_id)
                if document is None:
                    errors.append(f"unknown_source:{citation.source_version_id}")
                    continue
                nodes = {node.node_id for node in document.nodes}
                missing = set(citation.node_ids) - nodes
                if missing:
                    errors.append(f"missing_nodes:{use.claim_id}")
                    continue
                evidence.append(
                    ObjectiveEvidence(
                        evidence_id=_stable_id(
                            "evidence",
                            proposal.candidate_id,
                            use.claim_id,
                            citation.source_version_id,
                            str(citation_index),
                        ),
                        claim_id=use.claim_id,
                        source_version_id=citation.source_version_id,
                        node_ids=citation.node_ids,
                        role=use.role,
                        rationale=use.rationale,
                        assessment_eligible=use.role == EvidenceRole.OBJECTIVE_DEFINING,
                    )
                )
        support = proposal.support_profile
        if support is None or support.discovery_basis == ObjectiveDiscoveryBasis.SOURCE_DERIVED:
            if not any(item.assessment_eligible for item in evidence):
                errors.append("no_objective_defining_evidence")
        else:
            if not any(item.role == EvidenceRole.SOURCE_ANCHOR for item in evidence):
                errors.append("no_source_anchor_evidence")
            if not set(support.source_claim_ids) <= {item.claim_id for item in evidence}:
                errors.append("support_profile_claim_mismatch")
        return evidence, errors

    def _evidence_payload(
        self,
        evidence: list[ObjectiveEvidence],
        documents: dict[str, ExtractedDocument],
    ) -> list[dict[str, Any]]:
        values = []
        for item in evidence:
            by_id = {node.node_id: node for node in documents[item.source_version_id].nodes}
            for node_id in item.node_ids:
                node = by_id[node_id]
                values.append(
                    {
                        "evidence_id": item.evidence_id,
                        "source_version_id": item.source_version_id,
                        "node_id": node_id,
                        "role": str(item.role),
                        "assessment_eligible": item.assessment_eligible,
                        "text": node.text,
                        "locators": [locator.model_dump(mode="json") for locator in node.locators],
                    }
                )
        return values

    @staticmethod
    def _hierarchy_outline(
        collection_map: CollectionMap,
        documents: dict[str, ExtractedDocument],
    ) -> list[dict[str, Any]]:
        structural_terms = ("title", "heading", "header", "section", "chapter")
        outline = []
        for source in sorted(collection_map.sources, key=lambda item: item.ordinal):
            document = documents[source.source_version_id]
            for node in sorted(document.nodes, key=lambda item: item.ordinal_path):
                kind = f"{node.kind} {node.role}".lower()
                if not node.child_ids and not any(term in kind for term in structural_terms):
                    continue
                hierarchy_ref = (
                    f"{source.source_version_id}:"
                    f"{'.'.join(str(value) for value in node.ordinal_path)}"
                )
                outline.append(
                    {
                        "hierarchy_ref": hierarchy_ref,
                        "source_version_id": source.source_version_id,
                        "parent_id": node.parent_id,
                        "ordinal_path": node.ordinal_path,
                        "kind": node.kind,
                        "role": node.role,
                        "text": (node.text or "")[:500],
                    }
                )
        return outline

    def _bounded_batches(self, values, payload_builder) -> list[list[Any]]:
        batches = []
        pending = []
        for value in values:
            candidate = [*pending, value]
            serialized = json.dumps(
                payload_builder(candidate), separators=(",", ":"), sort_keys=True
            )
            try:
                self.token_budget.require_within_limit(serialized)
            except TokenBudgetExceeded:
                if not pending:
                    raise
                batches.append(pending)
                pending = [value]
            else:
                pending = candidate
        if pending:
            batches.append(pending)
        return batches

    def _create_curriculum_blueprint(
        self,
        collection_map: CollectionMap,
        documents: dict[str, ExtractedDocument],
        brief: LearningBrief,
        workspace_id: str,
    ) -> DocumentCurriculumBlueprint:
        outline = self._hierarchy_outline(collection_map, documents)

        def payload(claims, *, mode, partial_blueprints=None):
            claim_ids = {claim.claim_id for claim in claims}
            return {
                "mode": mode,
                "collection_id": collection_map.collection_id,
                "source_map_revision": collection_map.map_revision,
                "learning_brief": brief.model_dump(mode="json"),
                "source_hierarchy": (
                    [] if mode == "consolidate_partial_blueprints" else outline
                ),
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "relationships": [
                    relationship.model_dump(mode="json")
                    for relationship in collection_map.relationships
                    if relationship.source_claim_id in claim_ids
                    and relationship.target_claim_id in claim_ids
                ],
                "partial_blueprints": partial_blueprints or [],
            }

        try:
            draft = self._parse(
                model=PROPOSAL_MODEL,
                operation="build-curriculum-blueprint",
                prompt=BLUEPRINT_PROMPT,
                content=payload(collection_map.claims, mode="complete_source"),
                text_format=CurriculumBlueprintDraft,
                job_id=workspace_id,
            )
        except TokenBudgetExceeded:
            batches = self._bounded_batches(
                collection_map.claims,
                lambda claims: payload(claims, mode="source_portion"),
            )
            partials = [
                self._parse(
                    model=PROPOSAL_MODEL,
                    operation=f"build-curriculum-blueprint-part-{index:04d}",
                    prompt=BLUEPRINT_PROMPT,
                    content=payload(batch, mode="source_portion"),
                    text_format=CurriculumBlueprintDraft,
                    job_id=workspace_id,
                )
                for index, batch in enumerate(batches, start=1)
            ]

            consolidation_count = 0

            def consolidate(values: list[CurriculumBlueprintDraft]):
                nonlocal consolidation_count
                if len(values) == 1:
                    return values[0]
                consolidation_count += 1
                content = payload(
                    [],
                    mode="consolidate_partial_blueprints",
                    partial_blueprints=[
                        value.model_dump(mode="json") for value in values
                    ],
                )
                try:
                    return self._parse(
                        model=PROPOSAL_MODEL,
                        operation=(
                            "consolidate-curriculum-blueprint-"
                            f"{consolidation_count:04d}"
                        ),
                        prompt=BLUEPRINT_PROMPT,
                        content=content,
                        text_format=CurriculumBlueprintDraft,
                        job_id=workspace_id,
                    )
                except TokenBudgetExceeded:
                    midpoint = len(values) // 2
                    if midpoint == 0:
                        raise
                    return consolidate(
                        [consolidate(values[:midpoint]), consolidate(values[midpoint:])]
                    )

            draft = consolidate(partials)

        known_claim_ids = {claim.claim_id for claim in collection_map.claims}
        known_hierarchy_refs = {item["hierarchy_ref"] for item in outline}
        central_claim_ids = list(
            dict.fromkeys(
                claim_id
                for claim_id in draft.central_claim_ids
                if claim_id in known_claim_ids
            )
        )
        if not central_claim_ids:
            raise ValueError("curriculum blueprint has no valid central claims")
        blueprint_id = _stable_id(
            "curriculum-blueprint",
            collection_map.map_id,
            brief.brief_revision,
        )
        domains = []
        for ordinal, domain in enumerate(draft.domains, start=1):
            claim_ids = list(
                dict.fromkeys(
                    claim_id
                    for claim_id in domain.claim_ids
                    if claim_id in known_claim_ids
                )
            )
            if not claim_ids:
                continue
            domains.append(
                CurriculumDomain(
                    domain_id=_stable_id(
                        "curriculum-domain", blueprint_id, str(ordinal), domain.title
                    ),
                    title=domain.title,
                    description=domain.description,
                    ordinal=len(domains) + 1,
                    importance=domain.importance,
                    rationale=domain.rationale,
                    claim_ids=claim_ids,
                    hierarchy_refs=list(
                        dict.fromkeys(
                            ref
                            for ref in domain.hierarchy_refs
                            if ref in known_hierarchy_refs
                        )
                    ),
                )
            )
        if not domains:
            raise ValueError("curriculum blueprint has no grounded domains")
        return DocumentCurriculumBlueprint(
            blueprint_id=blueprint_id,
            collection_id=collection_map.collection_id,
            source_map_revision=collection_map.map_revision,
            central_purpose=draft.central_purpose,
            central_claim_ids=central_claim_ids,
            intended_use=draft.intended_use,
            boundaries=draft.boundaries,
            domains=domains,
            integrative_performances=draft.integrative_performances,
            reference_topics=draft.reference_topics,
            uncertainties=draft.uncertainties,
        )

    def _propose_objectives(
        self,
        collection_map: CollectionMap,
        brief: LearningBrief,
        blueprint: DocumentCurriculumBlueprint,
        workspace_id: str,
    ) -> ObjectiveProposalDraft:
        def domain_ids_for_claims(claim_ids: set[str]) -> list[str]:
            return [
                domain.domain_id
                for domain in blueprint.domains
                if claim_ids.intersection(domain.claim_ids)
            ]

        def content(claims: list[MapClaim]) -> dict[str, Any]:
            return {
                "learning_brief": brief.model_dump(mode="json"),
                "curriculum_blueprint": blueprint.model_dump(mode="json"),
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "relationships": [
                    relationship.model_dump(mode="json")
                    for relationship in collection_map.relationships
                    if relationship.source_claim_id in {claim.claim_id for claim in claims}
                    and relationship.target_claim_id in {claim.claim_id for claim in claims}
                ],
                "conflicts": [
                    conflict.model_dump(mode="json") for conflict in collection_map.conflicts
                ],
            }

        def compact_memory(candidate: ProposedObjective) -> dict[str, Any]:
            claim_ids = list(
                dict.fromkeys(use.claim_id for use in candidate.evidence_uses)
            )
            return {
                "candidate_id": candidate.candidate_id,
                "statement": candidate.statement,
                "observable_behavior": candidate.observable_behavior,
                "claim_ids": claim_ids,
                "curriculum_domain_ids": domain_ids_for_claims(set(claim_ids)),
            }

        def candidate_key(candidate: ProposedObjective) -> str:
            return " ".join(candidate.statement.lower().split())

        def run_pass(
            claims: list[MapClaim],
            batch_index: int | str | None,
            prior_candidates: list[ProposedObjective],
            batch_position: int,
            batch_count: int,
        ) -> ObjectiveProposalDraft:
            base = content(claims)
            if batch_index is not None:
                base = {**base, "batch_index": batch_index}
            signal_draft = self._parse(
                model=PROPOSAL_MODEL,
                operation="detect-objective-signals",
                prompt=SIGNAL_PROMPT,
                content=base,
                text_format=SignalDetectionDraft,
                job_id=workspace_id,
            )
            feature_draft = self._parse(
                model=PROPOSAL_MODEL,
                operation="inventory-source-features",
                prompt=FEATURE_PROMPT,
                content=base,
                text_format=SourceFeatureDraft,
                job_id=workspace_id,
            )
            found: list[ProposedObjective] = []
            seen_keys = {candidate_key(candidate) for candidate in prior_candidates}
            seen_ids = {candidate.candidate_id for candidate in prior_candidates}
            claim_ids = {claim.claim_id for claim in claims}
            for discovery_pass in range(1, MAX_DISCOVERY_PASSES + 1):
                memory_candidates = [*prior_candidates, *found]
                covered_claim_ids = {
                    use.claim_id
                    for candidate in memory_candidates
                    for use in candidate.evidence_uses
                    if use.claim_id in claim_ids
                }
                covered_domain_ids = set(
                    domain_ids_for_claims(covered_claim_ids)
                )
                request_memory = memory_candidates[-DISCOVERY_MEMORY_LIMIT:]
                while True:
                    try:
                        draft = self._parse(
                            model=PROPOSAL_MODEL,
                            operation=f"form-objective-candidates-pass-{discovery_pass}",
                            prompt=PROPOSAL_PROMPT,
                            content={
                                **base,
                                "detected_signals": [
                                    signal.model_dump(mode="json")
                                    for signal in signal_draft.signals
                                ],
                                "source_features": [
                                    feature.model_dump(mode="json")
                                    for feature in feature_draft.source_features
                                ],
                                "discovery_context": {
                                    "pass_number": discovery_pass,
                                    "maximum_passes": MAX_DISCOVERY_PASSES,
                                    "prior_candidate_memory": [
                                        compact_memory(candidate)
                                        for candidate in request_memory
                                    ],
                                    "uncovered_claim_ids": sorted(
                                        claim_ids - covered_claim_ids
                                    ),
                                    "covered_curriculum_domain_ids": sorted(
                                        covered_domain_ids
                                    ),
                                    "underrepresented_curriculum_domain_ids": [
                                        domain.domain_id
                                        for domain in blueprint.domains
                                        if domain.importance == CurriculumImportance.CORE
                                        and domain.domain_id not in covered_domain_ids
                                    ],
                                },
                            },
                            text_format=ObjectiveProposalDraft,
                            job_id=workspace_id,
                        )
                        break
                    except TokenBudgetExceeded:
                        if not request_memory:
                            raise
                        request_memory = request_memory[max(1, len(request_memory) // 2) :]
                new_candidates = []
                for candidate in draft.candidates:
                    key = candidate_key(candidate)
                    if key in seen_keys:
                        continue
                    if candidate.candidate_id in seen_ids:
                        candidate = candidate.model_copy(
                            update={
                                "candidate_id": _stable_id(
                                    "candidate-pass",
                                    workspace_id,
                                    str(batch_index),
                                    str(discovery_pass),
                                    candidate.candidate_id,
                                    key,
                                )
                            }
                        )
                    seen_keys.add(key)
                    seen_ids.add(candidate.candidate_id)
                    new_candidates.append(candidate)
                if not new_candidates and discovery_pass >= 2:
                    break
                found.extend(new_candidates)
                if new_candidates:
                    self._publish_preliminary_findings(
                        ObjectiveProposalDraft(
                            candidates=[*prior_candidates, *found],
                            signals=signal_draft.signals,
                            source_features=feature_draft.source_features,
                        ),
                        batches_completed=batch_position,
                        batch_count=batch_count,
                        discovery_pass=discovery_pass,
                        new_candidates=len(new_candidates),
                    )
            return ObjectiveProposalDraft(
                candidates=found,
                signals=signal_draft.signals,
                source_features=feature_draft.source_features,
            )

        if not collection_map.claims:
            return ObjectiveProposalDraft()
        try:
            return run_pass(collection_map.claims, None, [], 1, 1)
        except TokenBudgetExceeded:
            batches: list[list[MapClaim]] = []
            pending: list[MapClaim] = []
            for claim in collection_map.claims:
                candidate = [*pending, claim]
                try:
                    self.token_budget.require_within_limit(
                        json.dumps(content(candidate), separators=(",", ":"), sort_keys=True),
                        complete_request_limit=self.token_budget.request_token_limit,
                        reserved_tokens=self.token_budget.source_token_limit,
                    )
                except TokenBudgetExceeded:
                    if not pending:
                        raise
                    batches.append(pending)
                    pending = [claim]
                else:
                    pending = candidate
            if pending:
                batches.append(pending)
            candidates = []
            signals = []
            source_features = []

            def run_adaptive_batch(
                batch: list[MapClaim], batch_key: int | str
            ) -> None:
                try:
                    draft = run_pass(
                        batch,
                        batch_key,
                        candidates,
                        len(completed_batches) + 1,
                        max(len(batches), len(completed_batches) + 1),
                    )
                except TokenBudgetExceeded:
                    if len(batch) < 2:
                        raise
                    midpoint = len(batch) // 2
                    run_adaptive_batch(batch[:midpoint], f"{batch_key}.1")
                    run_adaptive_batch(batch[midpoint:], f"{batch_key}.2")
                    return
                candidates.extend(draft.candidates)
                signals.extend(draft.signals)
                source_features.extend(draft.source_features)
                completed_batches.append(batch_key)

            completed_batches: list[int | str] = []
            for batch_index, batch in enumerate(batches):
                run_adaptive_batch(batch, batch_index)
            unique = {}
            for candidate in candidates:
                unique.setdefault(candidate.candidate_id, candidate)
            unique_features = {}
            for feature in source_features:
                unique_features.setdefault(feature.feature_id, feature)
            unique_signals = {}
            for signal in signals:
                unique_signals.setdefault(signal.signal_id, signal)
            return ObjectiveProposalDraft(
                candidates=list(unique.values()),
                signals=list(unique_signals.values()),
                source_features=list(unique_features.values()),
            )

    def _classify_objective(
        self,
        proposal: ProposedObjective,
        *,
        brief: LearningBrief,
        claims: dict[str, MapClaim],
        sibling_statements: list[str],
        workspace_id: str,
    ) -> ObjectiveClassificationDraft:
        evidence_claims = [
            claims[use.claim_id].model_dump(mode="json")
            for use in proposal.evidence_uses
            if use.claim_id in claims
        ]
        content = {
            "candidate": proposal.model_dump(mode="json"),
            "objective_defining_claims": evidence_claims,
            "learning_brief": brief.model_dump(mode="json"),
            "sibling_objective_statements": sibling_statements,
        }
        return self._classify_content(
            proposal.candidate_id,
            content=content,
            workspace_id=workspace_id,
        )

    def classify_revised_candidate(
        self,
        candidate: ObjectiveCandidate,
        *,
        brief: LearningBrief,
        sibling_statements: list[str],
        workspace_id: str,
    ) -> ObjectiveClassificationDraft:
        """Reclassify reviewer-edited performance text before it can be approved."""

        content = {
            "candidate": candidate.model_dump(
                mode="json",
                exclude={
                    "classification",
                    "content_type_hint",
                    "bloom_level",
                    "poc2_scope_status",
                    "poc2_scope_reason",
                },
            ),
            "objective_defining_claims": [
                item.model_dump(mode="json") for item in candidate.evidence
            ],
            "learning_brief": brief.model_dump(mode="json"),
            "sibling_objective_statements": sibling_statements,
        }
        return self._classify_content(
            candidate.candidate_id,
            content=content,
            workspace_id=workspace_id,
        )

    def _classify_content(
        self,
        candidate_id: str,
        *,
        content: dict,
        workspace_id: str,
    ) -> ObjectiveClassificationDraft:
        try:
            draft = self._parse(
                model=PROPOSAL_MODEL,
                operation=f"classify-objective-{candidate_id}",
                prompt=CLASSIFICATION_PROMPT,
                content=content,
                text_format=ObjectiveClassificationDraft,
                job_id=workspace_id,
            )
        except ValidationError as exc:
            draft = self._parse(
                model=PROPOSAL_MODEL,
                operation=f"classify-objective-{candidate_id}-repair",
                prompt=CLASSIFICATION_REPAIR_PROMPT,
                content={
                    **content,
                    "validation_errors": json.loads(exc.json(include_url=False)),
                },
                text_format=ObjectiveClassificationDraft,
                job_id=workspace_id,
            )
        if draft.candidate_id != candidate_id:
            raise ValueError("classification result does not match objective candidate")
        return draft

    def _materialize_candidates(
        self,
        proposals: list[ProposedObjective],
        *,
        brief: LearningBrief,
        collection_map: CollectionMap,
        documents: dict[str, ExtractedDocument],
        workspace_id: str,
        sibling_statements: list[str],
        proposed_feature_ids: set[str],
        rank_start: int = 1,
    ) -> tuple[list[ObjectiveCandidate], list[ObjectiveRejection]]:
        claims = {claim.claim_id: claim for claim in collection_map.claims}
        candidates = []
        rejected = []
        for rank, proposal in enumerate(proposals, start=rank_start):
            evidence, evidence_errors = self._resolve_evidence(proposal, claims, documents)
            if evidence_errors:
                rejected.append(
                    ObjectiveRejection(
                        candidate_id=proposal.candidate_id,
                        statement=proposal.statement,
                        reason_codes=evidence_errors,
                        explanation="Candidate evidence could not be resolved to source nodes.",
                    )
                )
                continue
            classification = None
            scope_status = ObjectiveScopeStatus.NEEDS_REVIEW
            scope_reason = None
            classification_error = None
            try:
                classification_result = self._classify_objective(
                    proposal,
                    brief=brief,
                    claims=claims,
                    sibling_statements=sibling_statements,
                    workspace_id=workspace_id,
                )
                classification = classification_result.classification
                scope_status = classification_result.scope_status
                scope_reason = classification_result.scope_reason
            except ValidationError as exc:
                classification_error = str(exc)
            try:
                support_profile = proposal.support_profile or ObjectiveSupportProfile(
                    discovery_basis=ObjectiveDiscoveryBasis.SOURCE_DERIVED,
                    source_support_level=SourceSupportLevel.SUBSTANTIAL,
                    source_relationship=proposal.rationale,
                    source_contributions=[
                        "The cited source claims support the complete learner performance."
                    ],
                    source_claim_ids=list(
                        dict.fromkeys(item.claim_id for item in evidence)
                    ),
                )
                candidates.append(
                    ObjectiveCandidate(
                        candidate_id=proposal.candidate_id,
                        statement=proposal.statement,
                        observable_behavior=proposal.observable_behavior,
                        performance_context=proposal.performance_context,
                        practitioner_relevance=proposal.practitioner_relevance,
                        bloom_level=classification.bloom.value
                        if classification
                        else None,
                        content_type_hint=classification.content_kind.value
                        if classification
                        else None,
                        scope=proposal.scope,
                        prerequisites=proposal.prerequisites,
                        rationale=proposal.rationale,
                        confidence=proposal.confidence,
                        confidence_rationale=proposal.confidence_rationale,
                        rule_ids=proposal.rule_ids,
                        terminal_outcome=proposal.terminal_outcome,
                        assumptions=[
                            *proposal.assumptions,
                            *(
                                [
                                    "Provisional classification unavailable; "
                                    "LDS review is required."
                                ]
                                if classification_error
                                else []
                            ),
                        ],
                        expected_effort_minutes=proposal.expected_effort_minutes,
                        evidence=evidence,
                        dependencies=proposal.dependencies,
                        conflicts=self._relevant_conflicts(collection_map, evidence),
                        selected_reason=proposal.selected_reason,
                        rank=rank,
                        source_feature_ids=[
                            feature_id
                            for feature_id in proposal.source_feature_ids
                            if feature_id in proposed_feature_ids
                        ],
                        classification=classification,
                        poc2_scope_status=scope_status,
                        poc2_scope_reason=scope_reason,
                        support_profile=support_profile,
                    )
                )
            except ValidationError as exc:
                rejected.append(
                    ObjectiveRejection(
                        candidate_id=proposal.candidate_id,
                        statement=proposal.statement,
                        reason_codes=["invalid_candidate_schema"],
                        explanation=str(exc),
                    )
                )
        return candidates, rejected

    @staticmethod
    def _compact_candidate(candidate: ObjectiveCandidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "statement": candidate.statement,
            "observable_behavior": candidate.observable_behavior,
            "performance_context": candidate.performance_context,
            "practitioner_relevance": candidate.practitioner_relevance,
            "scope": candidate.scope,
            "content_kind": str(candidate.content_type_hint)
            if candidate.content_type_hint
            else None,
            "bloom_level": candidate.bloom_level,
            "support_profile": candidate.support_profile.model_dump(mode="json")
            if candidate.support_profile
            else None,
            "claim_ids": list(
                dict.fromkeys(item.claim_id for item in candidate.evidence)
            ),
        }

    def _review_curriculum_coverage(
        self,
        blueprint: DocumentCurriculumBlueprint,
        candidates: list[ObjectiveCandidate],
        claims: list[MapClaim],
        *,
        workspace_id: str,
        workspace_revision: int,
        pass_name: str,
        gap_candidate_ids: list[str] | None = None,
        gap_discovery_records: list[CurriculumGapDiscoveryRecord] | None = None,
    ) -> CurriculumCoverageReport:
        compact_candidates = [self._compact_candidate(item) for item in candidates]
        gap_audit = [
            {
                "domain_id": record.domain_id,
                "targets": [
                    {
                        "target_id": item.target.target_id,
                        "performance": item.target.performance,
                        "direct_candidate_ids": item.direct_candidate_ids,
                        "supporting_candidate_ids": item.supporting_candidate_ids,
                        "no_candidate_found": item.no_candidate_found,
                    }
                    for item in record.target_records
                ],
            }
            for record in (gap_discovery_records or [])
        ]

        def payload(values, *, mode, partial_reviews=None):
            return {
                "mode": mode,
                "curriculum_blueprint": blueprint.model_dump(mode="json"),
                "curriculum_claims": [
                    {"claim_id": claim.claim_id, "statement": claim.statement}
                    for claim in claims
                ],
                "candidates": values,
                "partial_reviews": partial_reviews or [],
                "initial_gap_discovery": gap_audit,
            }

        try:
            draft = self._parse(
                model=PROPOSAL_MODEL,
                operation=f"review-objective-set-coverage-{pass_name}",
                prompt=COVERAGE_PROMPT,
                content=payload(compact_candidates, mode="complete_candidate_set"),
                text_format=CurriculumCoverageDraft,
                job_id=workspace_id,
            )
        except TokenBudgetExceeded:
            batches = self._bounded_batches(
                compact_candidates,
                lambda values: payload(values, mode="candidate_subset"),
            )
            partials = [
                self._parse(
                    model=PROPOSAL_MODEL,
                    operation=(
                        f"review-objective-set-coverage-{pass_name}-part-{index:04d}"
                    ),
                    prompt=COVERAGE_PROMPT,
                    content=payload(batch, mode="candidate_subset"),
                    text_format=CurriculumCoverageDraft,
                    job_id=workspace_id,
                )
                for index, batch in enumerate(batches, start=1)
            ]
            consolidation_count = 0

            def consolidate(values: list[CurriculumCoverageDraft]):
                nonlocal consolidation_count
                if len(values) == 1:
                    return values[0]
                consolidation_count += 1
                content = payload(
                    [],
                    mode="consolidate_partial_reviews",
                    partial_reviews=[value.model_dump(mode="json") for value in values],
                )
                try:
                    return self._parse(
                        model=PROPOSAL_MODEL,
                        operation=(
                            f"consolidate-objective-set-coverage-{pass_name}-"
                            f"{consolidation_count:04d}"
                        ),
                        prompt=COVERAGE_PROMPT,
                        content=content,
                        text_format=CurriculumCoverageDraft,
                        job_id=workspace_id,
                    )
                except TokenBudgetExceeded:
                    midpoint = len(values) // 2
                    if midpoint == 0:
                        raise
                    return consolidate(
                        [consolidate(values[:midpoint]), consolidate(values[midpoint:])]
                    )

            draft = consolidate(partials)

        candidate_ids = {candidate.candidate_id for candidate in candidates}
        domain_ids = {domain.domain_id for domain in blueprint.domains}
        assignment_ids = [assignment.candidate_id for assignment in draft.assignments]
        if len(assignment_ids) != len(set(assignment_ids)) or set(assignment_ids) != candidate_ids:
            raise ValueError("coverage review must assign every candidate exactly once")
        for assignment in draft.assignments:
            if not set(assignment.domain_ids) <= domain_ids:
                raise ValueError("coverage assignment references an unknown domain")
            if (
                assignment.role != CurriculumCoverageRole.PERIPHERAL
                and not assignment.domain_ids
            ):
                raise ValueError("non-peripheral coverage requires a curriculum domain")
        covered_domain_ids = [item.domain_id for item in draft.domain_coverage]
        if (
            len(covered_domain_ids) != len(set(covered_domain_ids))
            or set(covered_domain_ids) != domain_ids
        ):
            raise ValueError("coverage review must assess every curriculum domain")
        coverage_findings = []
        coverage_reviewer_questions = list(draft.reviewer_questions)
        domains_by_id = {domain.domain_id: domain for domain in blueprint.domains}
        for item in draft.domain_coverage:
            if not set(item.candidate_ids) <= candidate_ids:
                raise ValueError("domain coverage references an unknown candidate")
            domain = domains_by_id[item.domain_id]
            targets = []
            for target in item.gap_targets:
                domain_claim_ids = set(domain.claim_ids)
                valid_claim_ids = [
                    claim_id
                    for claim_id in dict.fromkeys(target.claim_ids)
                    if claim_id in domain_claim_ids
                ]
                if valid_claim_ids != list(dict.fromkeys(target.claim_ids)):
                    target = target.model_copy(
                        update={
                            "claim_ids": valid_claim_ids,
                            "evidence_sufficiency": GapEvidenceSufficiency.INSUFFICIENT,
                            "sufficiency_rationale": (
                                "The model cited evidence outside this curriculum domain. "
                                "Those references were removed, so the remaining domain "
                                "evidence requires reviewer confirmation."
                            ),
                            "search_warranted": False,
                        }
                    )
                    coverage_reviewer_questions.append(
                        f'Does the gap target "{target.performance}" need to be '
                        f'reframed using only evidence assigned to "{domain.title}"?'
                    )
                if target.search_warranted and (
                    target.evidence_sufficiency
                    != GapEvidenceSufficiency.SUFFICIENT
                    or not target.claim_ids
                ):
                    raise ValueError(
                        "coverage gap target search lacks sufficient source evidence"
                    )
                targets.append(
                    CurriculumGapTarget(
                        target_id=_stable_id(
                            "curriculum-gap-target",
                            blueprint.blueprint_id,
                            domain.domain_id,
                            " ".join(target.performance.lower().split()),
                            *sorted(target.claim_ids),
                        ),
                        domain_id=domain.domain_id,
                        **target.model_dump(mode="json"),
                    )
                )
            warranted_targets = [target for target in targets if target.search_warranted]
            if warranted_targets and domain.importance == CurriculumImportance.PERIPHERAL:
                raise ValueError("peripheral domains cannot warrant gap discovery")
            coverage_findings.append(
                CurriculumDomainCoverage(
                    domain_id=item.domain_id,
                    state=item.state,
                    candidate_ids=item.candidate_ids,
                    rationale=item.rationale,
                    missing_performances=[target.performance for target in targets],
                    gap_targets=targets,
                    gap_discovery_warranted=bool(warranted_targets),
                    gap_discovery_rationale=(
                        f"{len(warranted_targets)} source-supported missing "
                        "performance target(s) warrant focused discovery."
                        if warranted_targets
                        else None
                    ),
                )
            )
        if not set(draft.peripheral_candidate_ids) <= candidate_ids:
            raise ValueError("coverage review references an unknown peripheral candidate")
        for finding in draft.fragmentation_findings:
            if not set(finding.candidate_ids) <= candidate_ids:
                raise ValueError("fragmentation finding references an unknown candidate")

        report_id = _stable_id(
            "curriculum-coverage",
            blueprint.blueprint_id,
            str(workspace_revision),
            pass_name,
            *sorted(candidate_ids),
        )
        return CurriculumCoverageReport(
            report_id=report_id,
            blueprint_id=blueprint.blueprint_id,
            workspace_revision=workspace_revision,
            assignments=draft.assignments,
            domain_coverage=coverage_findings,
            peripheral_candidate_ids=list(dict.fromkeys(draft.peripheral_candidate_ids)),
            fragmentation_findings=draft.fragmentation_findings,
            missing_integrative_performances=draft.missing_integrative_performances,
            source_insufficiencies=draft.source_insufficiencies,
            reviewer_questions=list(dict.fromkeys(coverage_reviewer_questions)),
            gap_candidate_ids=gap_candidate_ids or [],
            gap_discovery_records=gap_discovery_records or [],
        )

    @staticmethod
    def _compact_proposal(proposal: ProposedObjective) -> dict[str, Any]:
        return {
            "candidate_id": proposal.candidate_id,
            "statement": proposal.statement,
            "observable_behavior": proposal.observable_behavior,
            "claim_ids": list(
                dict.fromkeys(use.claim_id for use in proposal.evidence_uses)
            ),
        }

    def _align_gap_proposal(
        self,
        *,
        target: CurriculumGapTarget,
        proposal: ProposedObjective,
        claims: list[MapClaim],
        brief: LearningBrief,
        workspace_id: str,
    ) -> GapTargetAlignment:
        alignment = self._parse(
            model=TARGET_ALIGNMENT_MODEL,
            operation=(
                f"align-gap-target-{target.target_id}-candidate-"
                f"{proposal.candidate_id}"
            ),
            prompt=TARGET_ALIGNMENT_PROMPT,
            content={
                "gap_target": target.model_dump(mode="json"),
                "candidate": proposal.model_dump(mode="json"),
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "learning_brief": brief.model_dump(mode="json"),
            },
            text_format=GapTargetAlignment,
            job_id=workspace_id,
        )
        if alignment.target_id != target.target_id:
            raise InvalidGapAlignment("gap alignment does not match the selected target")
        if alignment.candidate_id != proposal.candidate_id:
            raise InvalidGapAlignment("gap alignment does not match the proposed objective")
        supplied_claim_ids = {claim.claim_id for claim in claims}
        proposal_claim_ids = {item.claim_id for item in proposal.evidence_uses}
        allowed_claim_ids = supplied_claim_ids & proposal_claim_ids
        claim_ids_used = list(
            dict.fromkeys(
                claim_id
                for claim_id in alignment.claim_ids_used
                if claim_id in allowed_claim_ids
            )
        )
        if claim_ids_used != alignment.claim_ids_used:
            alignment = alignment.model_copy(
                update={"claim_ids_used": claim_ids_used}
            )
        if (
            alignment.alignment
            in {GapTargetAlignmentState.DIRECT, GapTargetAlignmentState.SUPPORTING}
            and not alignment.claim_ids_used
        ):
            raise InvalidGapAlignment(
                "retained gap alignment requires proposal evidence"
            )
        return alignment

    def _discover_coverage_gaps(
        self,
        collection_map: CollectionMap,
        brief: LearningBrief,
        blueprint: DocumentCurriculumBlueprint,
        coverage: CurriculumCoverageReport,
        candidates: list[ObjectiveCandidate],
        workspace_id: str,
    ) -> CoverageGapSweep:
        coverage_by_domain = {
            item.domain_id: item for item in coverage.domain_coverage
        }
        incomplete_domains = [
            domain
            for domain in blueprint.domains
            if coverage_by_domain[domain.domain_id].state
            in {CurriculumCoverageState.PARTIAL, CurriculumCoverageState.MISSING}
        ]
        eligible_targets = [
            (domain, target_index, target)
            for domain in incomplete_domains
            for target_index, target in enumerate(
                coverage_by_domain[domain.domain_id].gap_targets, start=1
            )
            if target.search_warranted
            and domain.importance
            in {CurriculumImportance.CORE, CurriculumImportance.SUPPORTING}
        ]
        records_by_domain = {
            domain.domain_id: CurriculumGapDiscoveryRecord(
                domain_id=domain.domain_id,
                initial_state=coverage_by_domain[domain.domain_id].state,
                warranted=any(
                    target.search_warranted
                    for target in coverage_by_domain[domain.domain_id].gap_targets
                ),
                selected_for_discovery=any(
                    target.search_warranted
                    for target in coverage_by_domain[domain.domain_id].gap_targets
                ),
                eligibility_rationale=(
                    coverage_by_domain[domain.domain_id].gap_discovery_rationale
                    or "The coverage review did not warrant another focused search."
                ),
                target_records=[
                    CurriculumGapTargetDiscoveryRecord(
                        target=target,
                        selected_for_discovery=target.search_warranted,
                    )
                    for target in coverage_by_domain[domain.domain_id].gap_targets
                ],
                no_candidate_found=True,
            )
            for domain in incomplete_domains
        }
        if not eligible_targets:
            return CoverageGapSweep(records=list(records_by_domain.values()))
        claims_by_id = {claim.claim_id: claim for claim in collection_map.claims}
        memory = [self._compact_candidate(candidate) for candidate in candidates]
        known_candidate_ids = {candidate.candidate_id for candidate in candidates}
        seen_statements = {
            " ".join(candidate.statement.lower().split()) for candidate in candidates
        }
        proposals = []

        for domain, target_index, target in eligible_targets:
            target_claims = [
                claims_by_id[claim_id]
                for claim_id in target.claim_ids
                if claim_id in claims_by_id
            ]
            domain_record = records_by_domain[domain.domain_id]
            target_record = next(
                item
                for item in domain_record.target_records
                if item.target.target_id == target.target_id
            )
            operation = (
                f"discover-curriculum-gap-{domain.ordinal:04d}-"
                f"target-{target_index:02d}"
            )

            def payload(claims):
                claim_ids = {claim.claim_id for claim in claims}
                return {
                    "learning_brief": brief.model_dump(mode="json"),
                    "curriculum_context": {
                        "blueprint_id": blueprint.blueprint_id,
                        "central_purpose": blueprint.central_purpose,
                        "intended_use": blueprint.intended_use,
                        "boundaries": blueprint.boundaries,
                    },
                    "selected_domain": {
                        **domain.model_dump(mode="json"),
                    },
                    "selected_gap_target": target.model_dump(mode="json"),
                    "claims": [claim.model_dump(mode="json") for claim in claims],
                    "relationships": [
                        relationship.model_dump(mode="json")
                        for relationship in collection_map.relationships
                        if relationship.source_claim_id in claim_ids
                        and relationship.target_claim_id in claim_ids
                    ],
                    "existing_candidate_memory": memory[-DISCOVERY_MEMORY_LIMIT:],
                }

            prompt_start = len(self.prompt_runs)
            try:
                drafts = [
                    (
                        self._parse(
                            model=PROPOSAL_MODEL,
                            operation=operation,
                            prompt=GAP_PROMPT,
                            content=payload(target_claims),
                            text_format=CoverageGapDraft,
                            job_id=workspace_id,
                        ),
                        {claim.claim_id for claim in target_claims},
                    )
                ]
            except TokenBudgetExceeded:
                batches = self._bounded_batches(target_claims, payload)
                drafts = [
                    (
                        self._parse(
                            model=PROPOSAL_MODEL,
                            operation=f"{operation}-part-{index:04d}",
                            prompt=GAP_PROMPT,
                            content=payload(batch),
                            text_format=CoverageGapDraft,
                            job_id=workspace_id,
                        ),
                        {claim.claim_id for claim in batch},
                    )
                    for index, batch in enumerate(batches, start=1)
                ]
            model_proposal_ids = []
            rejections = []
            alignments = []
            direct_candidate_ids = []
            supporting_candidate_ids = []
            for draft, supplied_claim_ids in drafts:
                if draft.target_id != target.target_id:
                    raise ValueError("gap proposal result uses the wrong target ID")
                for proposal in draft.candidates:
                    original_id = proposal.candidate_id
                    key = " ".join(proposal.statement.lower().split())
                    if any(
                        use.claim_id not in supplied_claim_ids
                        for use in proposal.evidence_uses
                    ):
                        rejections.append(
                            CurriculumGapCandidateRejection(
                                candidate_id=original_id,
                                reason_codes=["claim_outside_selected_domain_batch"],
                            )
                        )
                        model_proposal_ids.append(original_id)
                        continue
                    if key in seen_statements:
                        rejections.append(
                            CurriculumGapCandidateRejection(
                                candidate_id=original_id,
                                reason_codes=["exact_duplicate"],
                            )
                        )
                        model_proposal_ids.append(original_id)
                        continue
                    if proposal.candidate_id in known_candidate_ids:
                        proposal = proposal.model_copy(
                            update={
                                "candidate_id": _stable_id(
                                    "coverage-gap-candidate",
                                    workspace_id,
                                    domain.domain_id,
                                    proposal.candidate_id,
                                    key,
                                )
                            }
                        )
                    known_candidate_ids.add(proposal.candidate_id)
                    seen_statements.add(key)
                    model_proposal_ids.append(proposal.candidate_id)
                    try:
                        alignment = self._align_gap_proposal(
                            target=target,
                            proposal=proposal,
                            claims=[
                                claim
                                for claim in target_claims
                                if claim.claim_id in supplied_claim_ids
                            ],
                            brief=brief,
                            workspace_id=workspace_id,
                        )
                    except InvalidGapAlignment:
                        rejections.append(
                            CurriculumGapCandidateRejection(
                                candidate_id=proposal.candidate_id,
                                reason_codes=["invalid_gap_alignment"],
                            )
                        )
                        continue
                    alignments.append(alignment)
                    if alignment.alignment == GapTargetAlignmentState.OFF_TARGET:
                        rejections.append(
                            CurriculumGapCandidateRejection(
                                candidate_id=proposal.candidate_id,
                                reason_codes=["off_target_gap_proposal"],
                            )
                        )
                        continue
                    proposals.append(proposal)
                    if alignment.alignment == GapTargetAlignmentState.DIRECT:
                        direct_candidate_ids.append(proposal.candidate_id)
                    else:
                        supporting_candidate_ids.append(proposal.candidate_id)
                    memory.append(self._compact_proposal(proposal))
            target_record = target_record.model_copy(
                update={
                    "prompt_run_ids": [
                        run["prompt_run_id"] for run in self.prompt_runs[prompt_start:]
                    ],
                    "proposed_candidate_ids": list(dict.fromkeys(model_proposal_ids)),
                    "alignments": alignments,
                    "direct_candidate_ids": direct_candidate_ids,
                    "supporting_candidate_ids": supporting_candidate_ids,
                    "rejections": rejections,
                    "no_candidate_found": not (
                        direct_candidate_ids or supporting_candidate_ids
                    ),
                }
            )
            target_records = [
                target_record
                if item.target.target_id == target.target_id
                else item
                for item in domain_record.target_records
            ]
            domain_proposed_ids = list(
                dict.fromkeys(
                    candidate_id
                    for item in target_records
                    for candidate_id in item.proposed_candidate_ids
                )
            )
            domain_accepted_ids = list(
                dict.fromkeys(
                    candidate_id
                    for item in target_records
                    for candidate_id in [
                        *item.direct_candidate_ids,
                        *item.supporting_candidate_ids,
                    ]
                )
            )
            records_by_domain[domain.domain_id] = domain_record.model_copy(
                update={
                    "prompt_run_ids": list(
                        dict.fromkeys(
                            run_id
                            for item in target_records
                            for run_id in item.prompt_run_ids
                        )
                    ),
                    "proposed_candidate_ids": domain_proposed_ids,
                    "accepted_candidate_ids": domain_accepted_ids,
                    "rejections": [
                        rejection
                        for item in target_records
                        for rejection in item.rejections
                    ],
                    "target_records": target_records,
                    "no_candidate_found": not domain_accepted_ids,
                }
            )

        return CoverageGapSweep(
            proposals=proposals,
            records=[records_by_domain[domain.domain_id] for domain in incomplete_domains],
        )

    def _discover_related_objectives(
        self,
        collection_map: CollectionMap,
        brief: LearningBrief,
        blueprint: DocumentCurriculumBlueprint,
        coverage: CurriculumCoverageReport,
        candidates: list[ObjectiveCandidate],
        workspace_id: str,
    ) -> list[ProposedObjective]:
        """Propose useful performances that are anchored in, but exceed, the source."""

        claims_by_id = {claim.claim_id: claim for claim in collection_map.claims}
        domains_by_id = {domain.domain_id: domain for domain in blueprint.domains}
        seen = {" ".join(candidate.statement.lower().split()) for candidate in candidates}
        known_candidate_ids = {candidate.candidate_id for candidate in candidates}
        memory = [self._compact_candidate(candidate) for candidate in candidates]
        proposals: list[ProposedObjective] = []
        for finding in coverage.domain_coverage:
            domain = domains_by_id[finding.domain_id]
            if domain.importance == CurriculumImportance.PERIPHERAL:
                continue
            for target_index, target in enumerate(finding.gap_targets, start=1):
                if target.evidence_sufficiency != GapEvidenceSufficiency.INSUFFICIENT:
                    continue
                source_claims = [
                    claims_by_id[claim_id]
                    for claim_id in target.claim_ids
                    if claim_id in claims_by_id
                ]
                if not source_claims:
                    continue
                discovery = self._parse(
                    model=RELATED_OBJECTIVE_MODEL,
                    operation=(
                        f"discover-related-objectives-{domain.ordinal:04d}-"
                        f"target-{target_index:02d}"
                    ),
                    prompt=RELATED_OBJECTIVE_PROMPT,
                    content={
                        "learning_brief": brief.model_dump(mode="json"),
                        "curriculum_context": {
                            "central_purpose": blueprint.central_purpose,
                            "intended_use": blueprint.intended_use,
                            "boundaries": blueprint.boundaries,
                        },
                        "selected_domain": domain.model_dump(mode="json"),
                        "selected_gap_target": target.model_dump(mode="json"),
                        "source_anchor_claims": [
                            claim.model_dump(mode="json") for claim in source_claims
                        ],
                        "existing_candidate_memory": memory[-DISCOVERY_MEMORY_LIMIT:],
                    },
                    text_format=RelatedObjectiveDraft,
                    job_id=workspace_id,
                )
                if discovery.target_id != target.target_id:
                    raise ValueError("related discovery result uses the wrong target ID")
                supplied_claim_ids = {claim.claim_id for claim in source_claims}
                for proposal in discovery.candidates:
                    key = " ".join(proposal.statement.lower().split())
                    if key in seen or proposal.candidate_id in known_candidate_ids:
                        continue
                    proposal_claim_ids = {
                        item.claim_id for item in proposal.evidence_uses
                    }
                    if not proposal_claim_ids or not proposal_claim_ids <= supplied_claim_ids:
                        continue
                    anchored = proposal.model_copy(
                        update={
                            "evidence_uses": [
                                item.model_copy(update={"role": EvidenceRole.SOURCE_ANCHOR})
                                for item in proposal.evidence_uses
                            ]
                        }
                    )
                    assessment = self._parse(
                        model=RELATED_OBJECTIVE_MODEL,
                        operation=f"assess-objective-support-{proposal.candidate_id}",
                        prompt=SUPPORT_ASSESSMENT_PROMPT,
                        content={
                            "candidate": anchored.model_dump(mode="json"),
                            "selected_gap_target": target.model_dump(mode="json"),
                            "source_anchor_claims": [
                                claim.model_dump(mode="json") for claim in source_claims
                            ],
                            "learning_brief": brief.model_dump(mode="json"),
                        },
                        text_format=ObjectiveSupportAssessmentDraft,
                        job_id=workspace_id,
                    )
                    if assessment.candidate_id != proposal.candidate_id:
                        raise ValueError("support assessment uses the wrong candidate ID")
                    if not assessment.accepted or assessment.support_profile is None:
                        continue
                    profile = assessment.support_profile
                    if (
                        profile.discovery_basis
                        != ObjectiveDiscoveryBasis.SOURCE_RELATED
                        or not set(profile.source_claim_ids) <= proposal_claim_ids
                    ):
                        continue
                    accepted = anchored.model_copy(update={"support_profile": profile})
                    proposals.append(accepted)
                    seen.add(key)
                    known_candidate_ids.add(accepted.candidate_id)
                    memory.append(self._compact_proposal(accepted))
        return proposals

    def _resolve_feature(
        self,
        proposal: ProposedSourceFeature,
        claims: dict[str, MapClaim],
        documents: dict[str, ExtractedDocument],
    ) -> SourceFeature | None:
        evidence = []
        for use in proposal.evidence_uses:
            claim = claims.get(use.claim_id)
            if claim is None:
                continue
            for citation_index, citation in enumerate(claim.citations):
                document = documents.get(citation.source_version_id)
                if document is None:
                    continue
                known_nodes = {node.node_id for node in document.nodes}
                if not set(citation.node_ids) <= known_nodes:
                    continue
                evidence.append(
                    ObjectiveEvidence(
                        evidence_id=_stable_id(
                            "feature-evidence",
                            proposal.feature_id,
                            use.claim_id,
                            citation.source_version_id,
                            str(citation_index),
                        ),
                        claim_id=use.claim_id,
                        source_version_id=citation.source_version_id,
                        node_ids=citation.node_ids,
                        role=use.role,
                        rationale=use.rationale,
                        assessment_eligible=False,
                    )
                )
        if proposal.status != SourceFeatureStatus.NOT_FOUND and not evidence:
            return None
        return SourceFeature(
            feature_id=proposal.feature_id,
            feature_type=proposal.feature_type,
            status=proposal.status,
            title=proposal.title,
            description=proposal.description,
            rationale=proposal.rationale,
            evidence=evidence,
            candidate_ids=proposal.candidate_ids,
        )

    def _resolve_signal(
        self,
        proposal: ProposedSignal,
        claims: dict[str, MapClaim],
        documents: dict[str, ExtractedDocument],
    ) -> DecompositionSignal | None:
        evidence = []
        for use in proposal.evidence_uses:
            claim = claims.get(use.claim_id)
            if claim is None:
                continue
            for citation_index, citation in enumerate(claim.citations):
                document = documents.get(citation.source_version_id)
                if document is None:
                    continue
                known_nodes = {node.node_id for node in document.nodes}
                if not set(citation.node_ids) <= known_nodes:
                    continue
                evidence.append(
                    ObjectiveEvidence(
                        evidence_id=_stable_id(
                            "signal-evidence",
                            proposal.signal_id,
                            use.claim_id,
                            citation.source_version_id,
                            str(citation_index),
                        ),
                        claim_id=use.claim_id,
                        source_version_id=citation.source_version_id,
                        node_ids=citation.node_ids,
                        role=use.role,
                        rationale=use.rationale,
                        assessment_eligible=False,
                    )
                )
        if not evidence:
            return None
        return DecompositionSignal(
            signal_id=proposal.signal_id,
            rule_id=proposal.rule_id,
            signal_type=proposal.signal_type,
            interpretation=proposal.interpretation,
            confidence=proposal.confidence,
            evidence=evidence,
        )

    def _relevant_conflicts(
        self,
        collection_map: CollectionMap,
        evidence: list[ObjectiveEvidence],
    ) -> list[str]:
        evidence_nodes = {
            (item.source_version_id, node_id)
            for item in evidence
            for node_id in item.node_ids
        }
        return [
            conflict.description
            for conflict in collection_map.conflicts
            if any(
                (citation.source_version_id, node_id) in evidence_nodes
                for citation in conflict.citations
                for node_id in citation.node_ids
            )
        ]

    def discover(
        self,
        collection_map: CollectionMap,
        documents: dict[str, ExtractedDocument],
        *,
        instructions: PractitionerInstructions | None = None,
        workspace_id: str | None = None,
        created_by: str | None = None,
    ) -> ObjectiveWorkspace:
        self.model_usage = defaultdict(list)
        self.prompt_runs: list[dict[str, str]] = []
        source_ids = {source.source_version_id for source in collection_map.sources}
        if set(documents) != source_ids:
            raise ValueError("objective documents must match collection-map sources")
        brief = self.create_learning_brief(collection_map, instructions)
        workspace_id = workspace_id or _stable_id(
            "workspace", collection_map.collection_id, created_by or "admin"
        )
        existing = self.store.load(workspace_id)
        if (
            existing
            and existing.learning_brief.brief_revision == brief.brief_revision
            and existing.curriculum_blueprint is not None
            and existing.curriculum_coverage is not None
        ):
            if hasattr(self.store, "model_metadata"):
                metadata = self.store.model_metadata(existing.workspace_id, existing.revision)
                self.prompt_runs = list(metadata.get("prompt_runs", []))
            return existing
        workspace_revision = (existing.revision + 1) if existing else 1
        blueprint = self._create_curriculum_blueprint(
            collection_map, documents, brief, workspace_id
        )
        proposal_draft = self._propose_objectives(
            collection_map, brief, blueprint, workspace_id
        )
        ordered = sorted(
            proposal_draft.candidates,
            key=lambda candidate: (candidate.priority, candidate.candidate_id),
        )
        claims = {claim.claim_id: claim for claim in collection_map.claims}
        sibling_statements = [candidate.statement for candidate in ordered]
        proposed_feature_ids = {
            feature.feature_id for feature in proposal_draft.source_features
        }
        candidates, rejected = self._materialize_candidates(
            ordered,
            brief=brief,
            collection_map=collection_map,
            documents=documents,
            workspace_id=workspace_id,
            sibling_statements=sibling_statements,
            proposed_feature_ids=proposed_feature_ids,
        )
        coverage = self._review_curriculum_coverage(
            blueprint,
            candidates,
            collection_map.claims,
            workspace_id=workspace_id,
            workspace_revision=workspace_revision,
            pass_name="initial",
        )
        gap_sweep = self._discover_coverage_gaps(
            collection_map,
            brief,
            blueprint,
            coverage,
            candidates,
            workspace_id,
        )
        gap_candidates = []
        gap_rejected = []
        if gap_sweep.proposals:
            ordered_gap = sorted(
                gap_sweep.proposals,
                key=lambda candidate: (candidate.priority, candidate.candidate_id),
            )
            gap_candidates, gap_rejected = self._materialize_candidates(
                ordered_gap,
                brief=brief,
                collection_map=collection_map,
                documents=documents,
                workspace_id=workspace_id,
                sibling_statements=[
                    *[candidate.statement for candidate in candidates],
                    *[candidate.statement for candidate in ordered_gap],
                ],
                proposed_feature_ids=proposed_feature_ids,
                rank_start=len(candidates) + 1,
            )
            rejected.extend(gap_rejected)
            candidates.extend(gap_candidates)
        related_proposals = self._discover_related_objectives(
            collection_map,
            brief,
            blueprint,
            coverage,
            candidates,
            workspace_id,
        )
        if related_proposals:
            related_candidates, related_rejected = self._materialize_candidates(
                related_proposals,
                brief=brief,
                collection_map=collection_map,
                documents=documents,
                workspace_id=workspace_id,
                sibling_statements=[
                    *[candidate.statement for candidate in candidates],
                    *[candidate.statement for candidate in related_proposals],
                ],
                proposed_feature_ids=proposed_feature_ids,
                rank_start=len(candidates) + 1,
            )
            candidates.extend(related_candidates)
            rejected.extend(related_rejected)
        accepted_gap_ids = {candidate.candidate_id for candidate in gap_candidates}
        materialization_rejections = {
            item.candidate_id: item.reason_codes for item in gap_rejected
        }
        gap_records = []
        for record in gap_sweep.records:
            target_records = []
            for target_record in record.target_records:
                retained_ids = [
                    *target_record.direct_candidate_ids,
                    *target_record.supporting_candidate_ids,
                ]
                added_rejections = [
                    CurriculumGapCandidateRejection(
                        candidate_id=candidate_id,
                        reason_codes=materialization_rejections[candidate_id],
                    )
                    for candidate_id in retained_ids
                    if candidate_id in materialization_rejections
                ]
                direct_ids = sorted(
                    set(target_record.direct_candidate_ids) & accepted_gap_ids
                )
                supporting_ids = sorted(
                    set(target_record.supporting_candidate_ids) & accepted_gap_ids
                )
                target_records.append(
                    target_record.model_copy(
                        update={
                            "direct_candidate_ids": direct_ids,
                            "supporting_candidate_ids": supporting_ids,
                            "rejections": [
                                *target_record.rejections,
                                *added_rejections,
                            ],
                            "no_candidate_found": not (
                                direct_ids or supporting_ids
                            ),
                        }
                    )
                )
            accepted_ids = sorted(
                {
                    candidate_id
                    for item in target_records
                    for candidate_id in [
                        *item.direct_candidate_ids,
                        *item.supporting_candidate_ids,
                    ]
                }
            )
            gap_records.append(
                record.model_copy(
                    update={
                        "accepted_candidate_ids": accepted_ids,
                        "rejections": [
                            rejection
                            for item in target_records
                            for rejection in item.rejections
                        ],
                        "target_records": target_records,
                        "no_candidate_found": not accepted_ids,
                    }
                )
            )
        coverage = self._review_curriculum_coverage(
            blueprint,
            candidates,
            collection_map.claims,
            workspace_id=workspace_id,
            workspace_revision=workspace_revision,
            pass_name="final",
            gap_candidate_ids=sorted(accepted_gap_ids),
            gap_discovery_records=gap_records,
        )
        source_features = [
            feature
            for proposal in proposal_draft.source_features
            if (feature := self._resolve_feature(proposal, claims, documents)) is not None
        ]
        signals = [
            signal
            for proposal in proposal_draft.signals
            if (signal := self._resolve_signal(proposal, claims, documents)) is not None
        ]
        feature_ids_by_candidate: dict[str, list[str]] = defaultdict(list)
        for feature in source_features:
            for candidate_id in feature.candidate_ids:
                feature_ids_by_candidate[candidate_id].append(feature.feature_id)
        for candidate in candidates:
            candidate_claims = {item.claim_id for item in candidate.evidence}
            candidate_nodes = {
                (item.source_version_id, node_id)
                for item in candidate.evidence
                for node_id in item.node_ids
            }
            for feature in source_features:
                if any(
                    item.claim_id in candidate_claims
                    or any(
                        (item.source_version_id, node_id) in candidate_nodes
                        for node_id in item.node_ids
                    )
                    for item in feature.evidence
                ):
                    feature_ids_by_candidate[candidate.candidate_id].append(
                        feature.feature_id
                    )
        candidates = [
            candidate.model_copy(
                update={
                    "source_feature_ids": list(
                        dict.fromkeys(
                            [
                                *candidate.source_feature_ids,
                                *feature_ids_by_candidate[candidate.candidate_id],
                            ]
                        )
                    ),
                }
            )
            for candidate in candidates
        ]
        workspace = ObjectiveWorkspace(
            workspace_id=workspace_id,
            collection_id=collection_map.collection_id,
            revision=workspace_revision,
            learning_brief=brief,
            curriculum_blueprint=blueprint,
            curriculum_coverage=coverage,
            candidates=candidates,
            signals=signals,
            source_features=source_features,
            rejected=rejected,
            duplicate_groups=[],
            critic_findings={},
        )
        return self.store.save_workspace(
            workspace,
            created_by=created_by,
            model_metadata={
                "aliases": [
                    str(LENS_MODEL),
                    str(PROPOSAL_MODEL),
                    str(TARGET_ALIGNMENT_MODEL),
                ],
                "usage": dict(self.model_usage),
                "prompt_runs": self.prompt_runs,
            },
        )
