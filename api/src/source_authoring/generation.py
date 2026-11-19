"""Checkpointed, evidence-bounded seven-part RLO content generation."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    load_lite_llm_settings,
)
from openai import OpenAI
from pydantic import ValidationError
from rlo_schema import Evidence, EvidenceRole, Source

from src.source_ingestion.segmentation import SourceTokenBudget

from . import draft_repository, repository
from .authoring_contracts import (
    AuthoringClaim,
    AuthoringElement,
    AuthoringElementType,
    AuthoringFinding,
    AuthoringObjective,
    AuthoringPart,
    AuthoringRLORevision,
    ClaimKnowledgeOrigin,
    ClaimVerificationStatus,
    ClassificationDecision,
    ElementOrigin,
    GenerationProvenance,
    GuidanceAssessment,
    LLMKnowledgeProvenance,
    PartStatus,
    RLOClassifications,
    RLOPartKind,
)
from .catalog_adapter import adapt_authoring_rlo
from .cell_scope import (
    authoring_scope_error,
    candidate_scope_error,
    is_poc2_cell,
    poc2_scope_reason,
)
from .draft_contracts import (
    DraftValidationFinding,
    RLODraftJob,
    RLODraftSnapshot,
    RLODraftState,
    RLOGenerationPromptRun,
    RLORevisionAction,
    RLORevisionRecord,
)
from .drafting import (
    DraftSourceMaterial,
    _evidence_segments,
    _locator,
    _segment_excerpt,
)
from .generation_contracts import (
    AuthoringReviewDraft,
    CollectionReviewDraft,
    LLMEnrichmentDraft,
    MappingChallengeDraft,
    PartGenerationDraft,
    SourceMapDraft,
    TargetPlanDraft,
)
from .methodology import PROFILES, get_methodology_profile
from .prompt_assets import PromptAsset, compose_prompt_asset, load_prompt_asset
from .revision import finding_id


RULES_VERSION = "2026-09-15-poc2-five-cell"
GENERATION_GROUP = "rlo_generation"


class EvidenceContextError(ValueError):
    """The immutable evidence exists but cannot be transported or resolved safely."""


def _asset(filename: str, prompt_id: str, *, version: str = "v1") -> PromptAsset:
    return load_prompt_asset(
        filename,
        prompt_id=prompt_id,
        version=version,
        group=GENERATION_GROUP,
    )


CLASSIFICATION_RULES = load_prompt_asset(
    "classification_rules.md",
    prompt_id="source-objective-classification-rules",
    version="v3",
)
AUTHORING_GUIDANCE_POLICY = load_prompt_asset(
    "authoring_guidance_policy.md",
    prompt_id="source-rlo-authoring-guidance-policy",
    version="v1",
    group=GENERATION_GROUP,
)
TARGET_PROMPT = compose_prompt_asset(
    _asset(
        "target_classification.md",
        "source-rlo-target-classification",
        version="v5",
    ),
    CLASSIFICATION_RULES,
)
MAPPING_PROMPT = _asset(
    "source_part_mapping.md", "source-rlo-part-mapping", version="v6"
)
CHALLENGE_PROMPT = _asset(
    "source_mapping_challenge.md", "source-rlo-mapping-challenge", version="v4"
)
SETUP_PROMPT = compose_prompt_asset(
    _asset("setup_generation.md", "source-rlo-setup-generation", version="v7"),
    AUTHORING_GUIDANCE_POLICY,
)
TEACH_SHOW_PROMPT = compose_prompt_asset(
    _asset(
        "teach_show_generation.md",
        "source-rlo-teach-show-generation",
        version="v7",
    ),
    AUTHORING_GUIDANCE_POLICY,
)
ENRICHMENT_PROMPT = _asset(
    "llm_domain_enrichment.md", "source-rlo-domain-enrichment", version="v3"
)
PRACTICE_CHECK_PROMPT = compose_prompt_asset(
    _asset(
        "practice_check_generation.md",
        "source-rlo-practice-check-generation",
        version="v11",
    ),
    AUTHORING_GUIDANCE_POLICY,
)
SENDOFF_PROMPT = compose_prompt_asset(
    _asset("sendoff_generation.md", "source-rlo-sendoff-generation", version="v6"),
    AUTHORING_GUIDANCE_POLICY,
)
GROUNDING_PROMPT = _asset(
    "grounding_validation.md", "source-rlo-grounding-validation", version="v5"
)
PROVENANCE_PROMPT = _asset(
    "provenance_validation.md", "source-rlo-provenance-validation", version="v2"
)
PEDAGOGY_PROMPT = compose_prompt_asset(
    _asset(
        "pedagogy_validation.md",
        "source-rlo-pedagogy-validation",
        version="v11",
    ),
    CLASSIFICATION_RULES,
)
REPAIR_PROMPT = _asset(
    "targeted_repair.md", "source-rlo-targeted-repair", version="v10"
)
COLLECTION_PROMPT = _asset(
    "collection_validation.md", "source-rlo-collection-validation", version="v3"
)


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _hash(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    return {
        key: value
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance((value := getattr(usage, key, None)), int)
    }


class RLOGenerationService:
    """Run one durable child job from approved objective through reviewable RLO."""

    def __init__(self, *, client=None, token_budget=None, store=draft_repository):
        settings = load_lite_llm_settings(required=False)
        self.client = client or OpenAI(base_url=settings.base_url, api_key=settings.api_key)
        self.token_budget = token_budget or SourceTokenBudget()
        self.store = store

    def _operation(
        self,
        *,
        job_id: str,
        operation: str,
        asset: PromptAsset,
        model: ModelAlias,
        content: dict,
        output_type,
        sequence: int,
    ):
        input_hash = _hash(content)
        existing = {
            item.operation: item
            for item in self.store.list_generation_checkpoints(job_id)
        }.get(operation)
        if existing and existing.input_hash == input_hash:
            return output_type.model_validate(existing.payload)
        serialized = _json(content)
        self.token_budget.require_within_limit(serialized)
        response = self.client.responses.parse(
            model=model,
            metadata=build_litellm_metadata(model, operation=operation, job_id=job_id),
            extra_headers=build_langfuse_headers(model, operation=operation, job_id=job_id),
            input=[
                {"role": "system", "content": asset.text},
                {"role": "user", "content": serialized},
            ],
            text_format=output_type,
        )
        if response.output_parsed is None:
            raise ValueError(f"model returned no {operation} result")
        output = response.output_parsed
        self.store.save_generation_checkpoint(
            job_id,
            operation=operation,
            sequence=sequence,
            input_hash=input_hash,
            payload=output.model_dump(mode="json"),
        )
        self.store.record_generation_prompt_run(
            RLOGenerationPromptRun(
                prompt_run_id=str(uuid.uuid4()),
                job_id=job_id,
                operation=operation,
                prompt_id=asset.prompt_id,
                prompt_version=asset.version,
                prompt_sha256=asset.sha256,
                prompt_filename=asset.filename,
                prompt_snapshot=asset.text,
                model_alias=str(model),
                input_snapshot=serialized,
                output_schema=output_type.__name__,
                output_snapshot=output.model_dump_json(),
                usage=_usage(response),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        return output

    @staticmethod
    def _methodology_payload(profile, *, parts=None, include_guidance=True):
        payload = profile.model_dump(mode="json")
        if not include_guidance:
            payload.pop("intent", None)
            payload.pop("guidance", None)
            payload.pop("avoid", None)
            payload.pop("review_dimensions", None)
            return payload
        if parts is not None:
            selected = set(parts)
            payload["guidance"] = [
                item.model_dump(mode="json")
                for item in profile.guidance
                if item.part in selected
            ]
        return payload

    def _progress(
        self,
        job: RLODraftJob,
        state: RLODraftState,
        operation: str,
        completed: int,
    ) -> RLODraftJob:
        return self.store.update_draft_job_progress(
            job.job_id,
            state=state,
            operation=operation,
            completed_operations=completed,
        )

    @staticmethod
    def _workspace_candidate(job: RLODraftJob):
        workspace = repository.get_objective_workspace(
            job.request.workspace_id, job.request.workspace_revision
        )
        if workspace is None:
            raise ValueError("objective workspace revision does not exist")
        candidate = next(
            (
                candidate
                for candidate in workspace.candidates
                if candidate.candidate_id == job.request.candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError("objective candidate does not exist")
        return workspace, candidate

    @staticmethod
    def _snapshot(workspace, candidate, materials: list[DraftSourceMaterial]):
        by_version = {material.source_version_id: material for material in materials}
        candidate_versions = {item.source_version_id for item in candidate.evidence}
        if not candidate_versions <= by_version.keys():
            raise ValueError("source collection does not contain candidate evidence")
        source_ref_by_version = {
            material.source_version_id: f"src-{index:02d}"
            for index, material in enumerate(materials, start=1)
        }
        sources = [
            Source(
                id=source_ref_by_version[material.source_version_id],
                title=material.title,
                reference=material.filename,
                authority="primary",
                ingested_source_id=material.source_id,
                source_version_id=material.source_version_id,
                checksum=material.checksum,
                canonical_locator=material.filename,
            )
            for material in materials
        ]
        evidence = []
        evidence_nodes = []
        for item in candidate.evidence:
            material = by_version[item.source_version_id]
            nodes = {node.node_id: node for node in material.document.nodes}
            if not set(item.node_ids) <= nodes.keys():
                raise EvidenceContextError(
                    "candidate evidence references a missing source node"
                )
            selected_segments = _evidence_segments(material, item.node_ids)
            if not selected_segments:
                raise EvidenceContextError(
                    "candidate evidence has no resolvable source segments"
                )
            excerpt = _segment_excerpt(selected_segments)
            evidence.append(
                Evidence(
                    id=item.evidence_id,
                    source_ref=source_ref_by_version[item.source_version_id],
                    source_version_id=item.source_version_id,
                    node_ids=item.node_ids,
                    segment_ids=[segment.segment_id for segment in selected_segments],
                    locator=_locator(material.document, item.node_ids),
                    role=(
                        EvidenceRole.SUPPORTING_CONTEXT
                        if str(item.role) == "source_anchor"
                        else EvidenceRole(item.role)
                    ),
                    excerpt=excerpt,
                    excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest()
                    if excerpt
                    else None,
                    usage_note=item.rationale,
                )
            )
            evidence_nodes.extend(
                {
                    "evidence_id": item.evidence_id,
                    "source_version_id": item.source_version_id,
                    "node_id": node_id,
                    "text": nodes[node_id].text,
                    "locators": [
                        locator.model_dump(mode="json")
                        for locator in nodes[node_id].locators
                    ],
                }
                for node_id in item.node_ids
            )
        return RLODraftSnapshot(
            candidate=candidate,
            learning_brief=workspace.learning_brief,
            sources=sources,
            evidence=evidence,
            evidence_nodes=evidence_nodes,
            source_features=workspace.source_features,
            prompt_version="source-rlo-generation-v1",
            model_aliases=[
                str(ModelAlias.SOURCE_RLO_DRAFTING),
                str(ModelAlias.SOURCE_RLO_DOMAIN_ENRICHMENT),
                str(ModelAlias.SOURCE_RLO_GROUNDING_REVIEW),
                str(ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW),
            ],
        )

    def _source_tranches(self, materials: list[DraftSourceMaterial]) -> list[list[dict]]:
        tranches: list[list[dict]] = []
        current: list[dict] = []
        current_tokens = 0
        limit = self.token_budget.source_token_limit
        for material in materials:
            nodes = {node.node_id: node for node in material.document.nodes}
            for segment in sorted(material.segments, key=lambda item: item.ordinal):
                entry = {
                    "source_version_id": material.source_version_id,
                    "segment_id": segment.segment_id,
                    "node_ids": segment.node_ids,
                    "hierarchy_path": segment.hierarchy_path,
                    "kinds": list(
                        dict.fromkeys(nodes[node_id].kind for node_id in segment.node_ids)
                    ),
                    "text": segment.text,
                    "chunk_index": segment.ordinal,
                    "locator_start": segment.locator_start.model_dump(mode="json"),
                    "locator_end": segment.locator_end.model_dump(mode="json"),
                }
                if segment.token_count > limit:
                    raise EvidenceContextError(
                        "persisted source segment exceeds tranche token limit"
                    )
                if current and current_tokens + segment.token_count > limit:
                    tranches.append(current)
                    current = []
                    current_tokens = 0
                current.append(entry)
                current_tokens += segment.token_count
        if current:
            tranches.append(current)
        return tranches

    @staticmethod
    def _suggested(candidate) -> ClassificationDecision | None:
        if candidate.content_type_hint is None:
            return None
        try:
            get_methodology_profile(candidate.content_type_hint, candidate.bloom_level)
        except ValueError:
            return None
        classification = candidate.classification
        rationale = "Preliminary classification retained from objective discovery."
        confidence = candidate.confidence
        alternatives = []
        discriminator_question = None
        escalation_required = False
        if classification:
            rationale = (
                f"Kind: {classification.content_kind.rationale} "
                f"Bloom: {classification.bloom.rationale}"
            )
            confidence = classification.combined_confidence
            alternatives = classification.plausible_alternative_cells
            discriminator_question = classification.discriminator_question
            escalation_required = classification.escalation_required
        return ClassificationDecision(
            content_type=candidate.content_type_hint,
            bloom_level=candidate.bloom_level,
            confidence=confidence,
            rationale=rationale,
            provisional=True,
            escalation_required=escalation_required,
            alternatives=alternatives,
            discriminator_question=discriminator_question,
        )

    def _normalize_mapping(self, snapshot, materials, maps, profile):
        document_by_version = {
            material.source_version_id: material.document for material in materials
        }
        node_by_version = {
            source_version_id: {node.node_id: node for node in document.nodes}
            for source_version_id, document in document_by_version.items()
        }
        segment_by_id = {
            segment.segment_id: (material.source_version_id, segment)
            for material in materials
            for segment in material.segments
        }
        source_ref_by_version = {
            source.source_version_id: source.id for source in snapshot.sources
        }
        evidence = list(snapshot.evidence)
        claims: list[AuthoringClaim] = []
        visual_synthesis_claim_ids: set[str] = set()
        claim_key_to_id: dict[tuple, str] = {}
        coverage: dict[str, dict] = {
            item.requirement_id: {"status": PartStatus.ABSENT, "claims": [], "gaps": []}
            for item in profile.requirements
        }

        # Approved objective evidence always remains a first-class factual claim.
        evidence_by_id = {item.id: item for item in snapshot.evidence}
        for item in snapshot.candidate.evidence:
            source_evidence = evidence_by_id[item.evidence_id]
            claim_id = item.claim_id
            if claim_id in {claim.claim_id for claim in claims}:
                claim_id = f"{claim_id}-{len(claims) + 1}"
            claims.append(
                AuthoringClaim(
                    claim_id=claim_id,
                    statement=source_evidence.excerpt or item.rationale,
                    evidence_refs=[item.evidence_id],
                    role=(
                        "supporting_context"
                        if str(item.role) == "source_anchor"
                        else item.role
                    ),
                    assessment_eligible=item.assessment_eligible,
                    requirement_refs=[],
                )
            )

        for source_map in maps:
            local_claims = {}
            for claim in source_map.claims:
                citations = []
                for citation in claim.citations:
                    missing = set(citation.segment_ids) - segment_by_id.keys()
                    if missing:
                        raise EvidenceContextError(
                            "mapped claim cites an unknown source segment"
                        )
                    versions = {
                        segment_by_id[segment_id][0]
                        for segment_id in citation.segment_ids
                    }
                    if len(versions) != 1:
                        raise EvidenceContextError(
                            "one mapped citation spans multiple source versions"
                        )
                    source_version_id = versions.pop()
                    if citation.source_version_id != source_version_id:
                        raise EvidenceContextError(
                            "mapped claim source version does not own its source segments"
                        )
                    citations.append((source_version_id, tuple(citation.segment_ids)))
                key = (claim.statement.strip().casefold(), tuple(citations))
                claim_id = claim_key_to_id.get(key)
                if claim_id is None:
                    claim_id = f"claim-map-{len(claim_key_to_id) + 1:04d}"
                    claim_key_to_id[key] = claim_id
                    evidence_ids = []
                    for source_version_id, segment_ids in citations:
                        evidence_id = f"ev-map-{len(evidence) + 1:04d}"
                        document = document_by_version[source_version_id]
                        selected_segments = [
                            segment_by_id[segment_id][1] for segment_id in segment_ids
                        ]
                        node_ids = list(
                            dict.fromkeys(
                                node_id
                                for segment in selected_segments
                                for node_id in segment.node_ids
                            )
                        )
                        excerpt = _segment_excerpt(selected_segments)
                        evidence.append(
                            Evidence(
                                id=evidence_id,
                                source_ref=source_ref_by_version[source_version_id],
                                source_version_id=source_version_id,
                                node_ids=node_ids,
                                segment_ids=list(segment_ids),
                                locator=_locator(document, node_ids),
                                role=EvidenceRole(claim.role),
                                excerpt=excerpt,
                                excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest()
                                if excerpt
                                else None,
                            )
                        )
                        evidence_ids.append(evidence_id)
                    valid_requirements = [
                        ref for ref in claim.requirement_refs if ref in coverage
                    ]
                    cited_nodes = [
                        node_by_version[source_version_id][node_id]
                        for source_version_id, segment_ids in citations
                        for segment_id in segment_ids
                        for node_id in segment_by_id[segment_id][1].node_ids
                        if node_id in node_by_version[source_version_id]
                    ]
                    if cited_nodes and all(
                        node.kind == "visual_explanation" for node in cited_nodes
                    ):
                        visual_synthesis_claim_ids.add(claim_id)
                    claims.append(
                        AuthoringClaim(
                            claim_id=claim_id,
                            statement=claim.statement,
                            evidence_refs=evidence_ids,
                            role=claim.role,
                            assessment_eligible=claim.assessment_eligible,
                            requirement_refs=valid_requirements,
                            qualifications=claim.qualifications,
                        )
                    )
                local_claims[claim.local_ref] = claim_id
            for item in source_map.coverage:
                if item.requirement_id not in coverage:
                    continue
                target = coverage[item.requirement_id]
                rank = {
                    PartStatus.ABSENT: 0,
                    PartStatus.SOURCE_INSUFFICIENT: 0,
                    PartStatus.PARTIAL: 1,
                    PartStatus.COMPLETE: 2,
                }
                if rank[item.status] > rank[target["status"]]:
                    target["status"] = item.status
                target["claims"].extend(
                    local_claims[ref] for ref in item.claim_refs if ref in local_claims
                )
                if item.gap:
                    target["gaps"].append(item.gap)
        if visual_synthesis_claim_ids:
            evidence_by_id = {item.id: item for item in evidence}
            claim_by_id = {item.claim_id: item for item in claims}
            for claim_id in visual_synthesis_claim_ids:
                claim = claim_by_id[claim_id]
                source_versions = {
                    evidence_by_id[ref].source_version_id for ref in claim.evidence_refs
                }
                same_requirement = [
                    item.claim_id
                    for item in claims
                    if item.claim_id not in visual_synthesis_claim_ids
                    and item.knowledge_origin == ClaimKnowledgeOrigin.SOURCE_DIRECT
                    and set(item.requirement_refs).intersection(claim.requirement_refs)
                    and any(
                        evidence_by_id[ref].source_version_id in source_versions
                        for ref in item.evidence_refs
                    )
                ]
                source_basis = same_requirement or [
                    item.claim_id
                    for item in claims
                    if item.claim_id not in visual_synthesis_claim_ids
                    and item.knowledge_origin == ClaimKnowledgeOrigin.SOURCE_DIRECT
                    and any(
                        evidence_by_id[ref].source_version_id in source_versions
                        for ref in item.evidence_refs
                    )
                ]
                if source_basis:
                    replacement = claim.model_copy(
                        update={
                            "knowledge_origin": ClaimKnowledgeOrigin.SOURCE_SYNTHESIS,
                            "source_claim_refs": list(dict.fromkeys(source_basis)),
                            "origin_rationale": (
                                "Derived interpretation of a source visual, grounded in "
                                "the cited visual artifact and related direct source claims."
                            ),
                        }
                    )
                    claims[claims.index(claim)] = replacement
                    claim_by_id[claim_id] = replacement
        for item in coverage.values():
            item["claims"] = list(dict.fromkeys(item["claims"]))
            item["gaps"] = list(dict.fromkeys(item["gaps"]))
        return list(snapshot.sources), evidence, claims, coverage

    @staticmethod
    def _normalize_enrichment(
        draft: LLMEnrichmentDraft,
        claims: list[AuthoringClaim],
        coverage: dict[str, dict],
        provenance: LLMKnowledgeProvenance,
    ) -> list[AuthoringClaim]:
        known_requirements = set(coverage)
        known_claim_ids = {claim.claim_id for claim in claims}
        enriched = []
        next_claim_number = 1
        for item in draft.claims:
            claim_id = f"claim-llm-{next_claim_number:04d}"
            while claim_id in known_claim_ids:
                next_claim_number += 1
                claim_id = f"claim-llm-{next_claim_number:04d}"
            requirement_refs = [
                ref for ref in item.requirement_refs if ref in known_requirements
            ]
            claim = AuthoringClaim(
                claim_id=claim_id,
                statement=item.statement,
                evidence_refs=[],
                knowledge_origin=ClaimKnowledgeOrigin.LLM_DOMAIN,
                verification_status=ClaimVerificationStatus.UNVERIFIED,
                llm_provenance_ref=provenance.provenance_id,
                origin_rationale=item.origin_rationale,
                role=item.role,
                assessment_eligible=item.assessment_eligible,
                requirement_refs=requirement_refs,
                qualifications=item.qualifications,
            )
            enriched.append(claim)
            known_claim_ids.add(claim_id)
            next_claim_number += 1
            for requirement_id in requirement_refs:
                coverage[requirement_id]["claims"].append(claim_id)
        for item in coverage.values():
            item["claims"] = list(dict.fromkeys(item["claims"]))
        return enriched

    @staticmethod
    def _element_origin(claim_refs: list[str], claims: dict[str, AuthoringClaim]):
        if not claim_refs:
            return ElementOrigin.INSTRUCTIONAL_SCAFFOLD
        origins = {claims[claim_ref].knowledge_origin for claim_ref in claim_refs}
        if origins <= {
            ClaimKnowledgeOrigin.SOURCE_DIRECT,
            ClaimKnowledgeOrigin.SOURCE_SYNTHESIS,
        }:
            return ElementOrigin.SOURCE
        if origins == {ClaimKnowledgeOrigin.LLM_DOMAIN}:
            return ElementOrigin.LLM_DOMAIN
        return ElementOrigin.MIXED

    @staticmethod
    def _source_elements(claims, coverage, profile):
        claim_by_id = {claim.claim_id: claim for claim in claims}
        elements: dict[RLOPartKind, list[AuthoringElement]] = {
            part: [] for part in RLOPartKind
        }
        element_type = {
            RLOPartKind.SETUP: AuthoringElementType.PRIOR_KNOWLEDGE,
            RLOPartKind.TEACH: AuthoringElementType.EXPLANATION,
            RLOPartKind.SHOW: AuthoringElementType.WORKED_EXAMPLE,
            RLOPartKind.SEND_OFF: AuthoringElementType.TRANSFER_PROMPT,
        }
        for requirement in profile.requirements:
            if requirement.part not in element_type:
                continue
            claim_refs = [
                claim_ref
                for claim_ref in coverage[requirement.requirement_id]["claims"]
                if claim_by_id[claim_ref].knowledge_origin
                != ClaimKnowledgeOrigin.LLM_DOMAIN
            ]
            if not claim_refs:
                continue
            evidence_refs = list(
                dict.fromkeys(
                    ref for claim_ref in claim_refs for ref in claim_by_id[claim_ref].evidence_refs
                )
            )
            elements[requirement.part].append(
                AuthoringElement(
                    element_id=f"source-{requirement.requirement_id}",
                    element_type=element_type[requirement.part],
                    content="\n\n".join(claim_by_id[ref].statement for ref in claim_refs),
                    origin=RLOGenerationService._element_origin(claim_refs, claim_by_id),
                    claim_refs=claim_refs,
                    evidence_refs=evidence_refs,
                    requirement_refs=[requirement.requirement_id],
                )
            )
        return elements

    @staticmethod
    def _assessment_with_eligible_claims(assessment, claim_by_id):
        if assessment is None:
            return None

        def eligible_refs(refs):
            return [
                ref
                for ref in refs
                if ref not in claim_by_id or claim_by_id[ref].assessment_eligible
            ]

        payload = assessment.model_dump(mode="json")
        payload["claim_refs"] = eligible_refs(assessment.claim_refs)
        payload["options"] = [
            {
                **option.model_dump(mode="json"),
                "claim_refs": eligible_refs(option.claim_refs),
            }
            for option in assessment.options or []
        ] or None
        return type(assessment).model_validate(payload)

    @staticmethod
    def _append_generated(elements, draft, claims, profile, sequence):
        claim_by_id = {claim.claim_id: claim for claim in claims}
        requirements = {item.requirement_id for item in profile.requirements}
        guidance = {item.guidance_id for item in profile.guidance}
        for item in draft.elements:
            if not set(item.claim_refs) <= claim_by_id.keys():
                raise ValueError("generated element references an unknown claim")
            if not set(item.requirement_refs) <= requirements:
                raise ValueError("generated element references an unknown methodology requirement")
            if not set(item.guidance_refs) <= guidance:
                raise ValueError("generated element references unknown methodology guidance")
            evidence_refs = list(
                dict.fromkeys(
                    ref for claim_ref in item.claim_refs for ref in claim_by_id[claim_ref].evidence_refs
                )
            )
            element_id = item.replace_element_id or (
                f"generated-{sequence:02d}-{item.part.value}-"
                f"{len(elements[item.part]) + 1:03d}"
            )
            generated = AuthoringElement(
                element_id=element_id,
                element_type=item.element_type,
                content=item.content,
                assessment=RLOGenerationService._assessment_with_eligible_claims(
                    item.assessment, claim_by_id
                ),
                origin=(
                    ElementOrigin.MIXED
                    if item.part in {RLOPartKind.PRACTICE, RLOPartKind.CHECK}
                    and item.claim_refs
                    else RLOGenerationService._element_origin(
                        item.claim_refs, claim_by_id
                    )
                ),
                claim_refs=item.claim_refs,
                evidence_refs=evidence_refs,
                generation_note=item.generation_note,
                requirement_refs=item.requirement_refs,
                guidance_refs=item.guidance_refs,
            )
            if item.replace_element_id:
                for part_elements in elements.values():
                    for index, existing in enumerate(part_elements):
                        if existing.element_id == item.replace_element_id:
                            part_elements[index] = generated
                            break
                    else:
                        continue
                    break
                else:
                    raise ValueError("repair references an unknown authoring element")
            else:
                elements[item.part].append(generated)

    @staticmethod
    def _admissible_pedagogy_findings(
        findings: list[AuthoringFinding],
    ) -> list[AuthoringFinding]:
        prohibited_demands = (
            "own terms",
            "own words",
            "learner generated explanation",
            "produce an explanation",
        )
        guidance_only_phrases = (
            "preferred shape",
            "profile requested",
            "profile request",
            "methodology guidance",
        )
        admitted = []
        for finding in findings:
            normalized = re.sub(r"[^a-z0-9]+", " ", finding.message.casefold())
            if any(phrase in normalized for phrase in prohibited_demands):
                continue
            if finding.severity == "warning" and any(
                phrase in normalized for phrase in guidance_only_phrases
            ):
                continue
            admitted.append(finding)
        return admitted

    @staticmethod
    def _parts(job, snapshot, profile, claims, coverage, elements):
        parts = []
        for ordinal, kind in enumerate(RLOPartKind, start=1):
            requirements = [
                item.requirement_id for item in profile.requirements if item.part == kind
            ]
            part_elements = elements[kind]
            covered = {
                ref for element in part_elements for ref in element.requirement_refs
            }
            if set(requirements) <= covered:
                status = PartStatus.COMPLETE
            elif part_elements:
                status = PartStatus.PARTIAL
            else:
                status = PartStatus.ABSENT
            gaps = [
                gap
                for requirement_id in requirements
                if requirement_id not in covered
                for gap in coverage[requirement_id]["gaps"]
            ]
            if kind == RLOPartKind.COVER:
                status = PartStatus.COMPLETE
                part_elements = [
                    AuthoringElement(
                        element_id="cover-metadata",
                        element_type=AuthoringElementType.METADATA,
                        content={
                            "rlo_id": job.request.rlo_id,
                            "version": job.request.rlo_version,
                            "objective": snapshot.candidate.statement,
                            "duration_minutes": snapshot.candidate.expected_effort_minutes,
                        },
                        origin=ElementOrigin.INSTRUCTIONAL_SCAFFOLD,
                        generation_note="Application-owned RLO metadata.",
                        requirement_refs=requirements,
                    )
                ]
            parts.append(
                AuthoringPart(
                    kind=kind,
                    ordinal=ordinal,
                    status=status,
                    requirement_refs=requirements,
                    elements=part_elements,
                    gaps=list(dict.fromkeys(gaps)),
                )
            )
        return parts

    @staticmethod
    def _deterministic_findings(authoring: AuthoringRLORevision) -> list[AuthoringFinding]:
        findings = []
        for part in authoring.parts:
            if part.kind == RLOPartKind.COVER:
                continue
            if part.status == PartStatus.SOURCE_INSUFFICIENT:
                findings.append(
                    AuthoringFinding(
                        code="source_insufficient",
                        severity="escalate",
                        category="grounding",
                        path=f"parts.{part.kind.value}",
                        message="The approved sources do not support the substantive Teach requirements.",
                    )
                )
            elif part.status in {PartStatus.ABSENT, PartStatus.PARTIAL}:
                findings.append(
                    AuthoringFinding(
                        code="part_incomplete",
                        severity="error",
                        category="pedagogy",
                        path=f"parts.{part.kind.value}",
                        message="One or more methodology requirements remain unfilled.",
                        repairable=True,
                    )
                )
        teach = next(part for part in authoring.parts if part.kind == RLOPartKind.TEACH)
        if not any(element.claim_refs for element in teach.elements):
            findings.append(
                AuthoringFinding(
                    code="teach_has_no_substantive_claims",
                    severity="escalate",
                    category="pedagogy",
                    path="parts.teach",
                    message="Teach has no substantive claims from any declared origin.",
                )
            )
        llm_claims = [
            claim
            for claim in authoring.claims
            if claim.knowledge_origin == ClaimKnowledgeOrigin.LLM_DOMAIN
        ]
        if llm_claims:
            findings.append(
                AuthoringFinding(
                    code="llm_domain_review_priority",
                    severity="warning",
                    category="grounding",
                    path="claims",
                    message=(
                        f"{len(llm_claims)} substantive claim(s) came from model "
                        "knowledge. Provenance is recorded, but factual correctness "
                        "is not independently verified."
                    ),
                )
            )
        return findings

    @staticmethod
    def _admissible_guidance_assessments(profile, assessments):
        known = {item.guidance_id for item in profile.guidance}
        by_id = {}
        for item in assessments:
            if item.guidance_id not in known or item.guidance_id in by_id:
                continue
            by_id[item.guidance_id] = GuidanceAssessment(
                guidance_id=item.guidance_id,
                status=item.status,
                explanation=item.explanation,
                affected_paths=item.affected_paths,
            )
        return [
            by_id[item.guidance_id]
            for item in profile.guidance
            if item.guidance_id in by_id
        ]

    def _process_scoped_revision(self, job: RLODraftJob) -> RLODraftJob:
        pending = job.pending_revision
        authoring = job.authoring
        if pending is None or authoring is None:
            raise ValueError("scoped revision requires a pending request and authoring")
        plan = pending.plan
        selected_ids = set(plan.selected_finding_ids)
        selected = [
            finding
            for finding in job.findings
            if finding_id(finding) in selected_ids
        ]
        if len(selected) != len(selected_ids):
            raise ValueError("one or more revision findings became stale")

        elements = {
            part.kind: list(part.elements) for part in authoring.parts
        }
        original_elements = {
            element.element_id: element.model_dump(mode="json")
            for part in authoring.parts
            for element in part.elements
            if element.element_id in plan.affected_element_ids
        }
        element_parts = {
            element.element_id: part.kind
            for part in authoring.parts
            for element in part.elements
        }
        operation_prefix = f"scoped-revision-{pending.revision_id}"
        job = self._progress(
            job,
            RLODraftState.REPAIRING,
            "Repairing reviewer-selected findings",
            job.completed_operations,
        )
        repair = self._operation(
            job_id=job.job_id,
            operation=f"{operation_prefix}-repair",
            asset=REPAIR_PROMPT,
            model=ModelAlias.SOURCE_RLO_DRAFTING,
            content={
                "authoring": self._scoped_repair_context(authoring, plan),
                "repairable_findings": [
                    item.model_dump(mode="json") for item in selected
                ],
                "reviewer_instruction": pending.instruction,
                "allowed_element_ids": plan.affected_element_ids,
                "repair_policy_sha256": REPAIR_PROMPT.sha256,
            },
            output_type=PartGenerationDraft,
            sequence=job.completed_operations + 1,
        )
        allowed = set(plan.affected_element_ids)
        if repair.source_insufficient:
            return self._stop_scoped_revision(
                job,
                pending,
                status="failed",
                reason=repair.insufficiency_reason or "The selected repair is unsupported.",
                actual_calls=1,
            )
        if not repair.elements:
            return self._stop_scoped_revision(
                job,
                pending,
                status="no_change",
                reason="The repair returned no element changes.",
                actual_calls=1,
            )
        for element in repair.elements:
            if (
                element.replace_element_id not in allowed
                or element_parts.get(element.replace_element_id) != element.part
            ):
                raise ValueError("repair attempted to change an element outside its scope")
        self._append_generated(
            elements, repair, authoring.claims, authoring.methodology_profile,
            job.completed_operations + 1,
        )
        revised_elements = {
            element.element_id: element.model_dump(mode="json")
            for part_elements in elements.values()
            for element in part_elements
            if element.element_id in allowed
        }
        if original_elements == revised_elements:
            return self._stop_scoped_revision(
                job,
                pending,
                status="no_change",
                reason="The repair made no material change to the selected elements.",
                actual_calls=1,
            )

        revision_number = job.revision + 1
        revised_authoring = AuthoringRLORevision.model_validate(
            {
                **authoring.model_dump(mode="json"),
                "revision": revision_number,
                "authoring_revision_id": (
                    f"{job.request.rlo_id}:{job.request.rlo_version}:{revision_number}"
                ),
                "parts": [
                    part.model_copy(update={"elements": elements[part.kind]}).model_dump(
                        mode="json"
                    )
                    for part in authoring.parts
                ],
                "findings": [],
            }
        )
        job = self._progress(
            job,
            RLODraftState.VALIDATING,
            f"Running scoped {plan.required_validator} review",
            job.completed_operations + 1,
        )
        if plan.required_validator == "provenance":
            asset = PROVENANCE_PROMPT
            model = ModelAlias.SOURCE_RLO_GROUNDING_REVIEW
        else:
            asset = PEDAGOGY_PROMPT
            model = ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW
        review = self._operation(
            job_id=job.job_id,
            operation=f"{operation_prefix}-validate-{plan.required_validator}",
            asset=asset,
            model=model,
            content={
                "authoring": revised_authoring.model_dump(mode="json"),
                "validation_scope": {
                    "element_ids": plan.affected_element_ids,
                    "report_only_findings_affecting_this_scope": True,
                },
                "validation_policy_sha256": asset.sha256,
            },
            output_type=AuthoringReviewDraft,
            sequence=job.completed_operations + 1,
        )
        scoped_findings = [
            item
            for item in [
                *self._deterministic_findings(revised_authoring),
                *self._admissible_pedagogy_findings(review.findings),
            ]
            if any(
                element_id in f"{item.path} {item.message}"
                for element_id in plan.affected_element_ids
            )
            or (
                plan.action == RLORevisionAction.REPAIR_ASSESSMENT
                and item.category == "classification"
            )
        ]
        observed = review.observed_classification
        target = revised_authoring.classifications.target
        if observed is not None and (
            observed.content_type != target.content_type
            or observed.bloom_level != target.bloom_level
        ):
            scoped_findings.append(
                AuthoringFinding(
                    code="target_observed_mismatch",
                    severity="error",
                    category="classification",
                    path="classifications.observed",
                    message=(
                        "The scoped revision still does not implement its Target "
                        "content-kind × Bloom cell."
                    ),
                    repairable=False,
                )
            )
        remaining = [
            AuthoringFinding(**item.model_dump(mode="json"))
            for item in job.findings
            if finding_id(item) not in selected_ids
        ]
        combined = [*remaining, *scoped_findings]
        unique = {}
        for item in combined:
            unique[finding_id(item)] = item
        final_findings = list(unique.values())
        classifications = revised_authoring.classifications
        if observed is not None:
            classifications = classifications.model_copy(
                update={"observed": observed}
            )
        revised_authoring = revised_authoring.model_copy(
            update={
                "classifications": classifications,
                "findings": final_findings,
                "guidance_assessments": (
                    self._admissible_guidance_assessments(
                        revised_authoring.methodology_profile,
                        review.guidance_assessments,
                    )
                    or revised_authoring.guidance_assessments
                ),
            }
        )
        final_ids = {finding_id(item) for item in final_findings}
        repeated = sorted(selected_ids & final_ids)
        resolved = sorted(selected_ids - final_ids)
        has_error = any(
            item.severity in {"error", "escalate"} for item in final_findings
        )
        catalog = None if has_error else adapt_authoring_rlo(revised_authoring)
        state = RLODraftState.VALIDATION_FAILED if has_error else RLODraftState.IN_REVIEW
        record = self._revision_record(
            job.job_id,
            pending,
            status="completed",
            actual_calls=2,
            resolved=resolved,
            repeated=repeated,
        )
        final = job.model_copy(
            update={
                "state": state,
                "current_operation": "Scoped revision ready for review",
                "completed_operations": job.completed_operations + 1,
                "revision": revision_number,
                "authoring": revised_authoring,
                "draft": catalog,
                "findings": [
                    DraftValidationFinding(**item.model_dump(mode="json"))
                    for item in final_findings
                ],
                "pending_revision": None,
                "revision_history": [*job.revision_history, record],
                "retryable": False,
                "error_message": None,
            }
        )
        result = self.store.save_draft_job(
            final, expected_state=job.state, save_revision=catalog is not None
        )
        if result.batch_id:
            self.store.refresh_generation_batch(result.batch_id)
        return result

    @staticmethod
    def _scoped_repair_context(authoring, plan):
        included_parts = set(plan.affected_parts)
        if plan.action == RLORevisionAction.REPAIR_ASSESSMENT:
            included_parts.update({"teach", "show", "practice", "check"})
        elif plan.action == RLORevisionAction.REPAIR_CONTENT:
            included_parts.add("teach")
        parts = [
            part
            for part in authoring.parts
            if part.kind.value in included_parts
        ]
        claim_ids = {
            claim_ref
            for part in parts
            for element in part.elements
            for claim_ref in element.claim_refs
        }
        if plan.action == RLORevisionAction.REPAIR_ASSESSMENT:
            claim_ids.update(
                claim.claim_id
                for claim in authoring.claims
                if claim.assessment_eligible
            )
        claims = [
            claim for claim in authoring.claims if claim.claim_id in claim_ids
        ]
        evidence_ids = {
            evidence_ref for claim in claims for evidence_ref in claim.evidence_refs
        }
        return {
            "rlo_id": authoring.rlo_id,
            "title": authoring.title,
            "objective": authoring.objective.model_dump(mode="json"),
            "classifications": authoring.classifications.model_dump(mode="json"),
            "methodology_profile": authoring.methodology_profile.model_dump(mode="json"),
            "parts": [part.model_dump(mode="json") for part in parts],
            "claims": [claim.model_dump(mode="json") for claim in claims],
            "evidence": [
                item.model_dump(mode="json")
                for item in authoring.evidence
                if item.id in evidence_ids
            ],
            "llm_knowledge_provenance": [
                item.model_dump(mode="json")
                for item in authoring.llm_knowledge_provenance
                if any(claim.llm_provenance_ref == item.provenance_id for claim in claims)
            ],
            "revision_scope": {
                "allowed_parts": plan.affected_parts,
                "allowed_element_ids": plan.affected_element_ids,
            },
        }

    def _revision_record(
        self,
        job_id,
        pending,
        *,
        status,
        actual_calls,
        reason=None,
        resolved=None,
        repeated=None,
    ):
        runs = [
            run
            for run in self.store.list_generation_prompt_runs(job_id)
            if run.operation.startswith(f"scoped-revision-{pending.revision_id}-")
        ]
        usage = {
            key: sum(
                run.usage.get(key, 0)
                for run in runs
                if isinstance(run.usage.get(key, 0), int)
            )
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        return RLORevisionRecord(
            revision_id=pending.revision_id,
            action=pending.plan.action,
            selected_finding_ids=pending.plan.selected_finding_ids,
            affected_element_ids=pending.plan.affected_element_ids,
            maximum_model_calls=pending.plan.maximum_model_calls,
            actual_model_calls=actual_calls,
            usage={key: value for key, value in usage.items() if value},
            status=status,
            stop_reason=reason,
            resolved_finding_ids=resolved or [],
            repeated_finding_ids=repeated or [],
            requested_by=pending.reviewer,
            requested_at=pending.requested_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _stop_scoped_revision(
        self, job, pending, *, status, reason, actual_calls
    ) -> RLODraftJob:
        record = self._revision_record(
            job.job_id,
            pending,
            status=status,
            actual_calls=actual_calls,
            reason=reason,
        )
        stopped = job.model_copy(
            update={
                "state": pending.base_state,
                "current_operation": "Scoped revision stopped without replacing the draft",
                "pending_revision": None,
                "revision_history": [*job.revision_history, record],
                "retryable": False,
                "error_message": None,
            }
        )
        return self.store.save_draft_job(stopped, expected_state=job.state)

    def process(self, job_id: str) -> RLODraftJob:
        job = self.store.get_draft_job(job_id)
        if job is None:
            raise ValueError("RLO generation job does not exist")
        if job.state not in {RLODraftState.PLANNING, RLODraftState.QUEUED}:
            raise ValueError(f"RLO generation job cannot run from {job.state}")
        try:
            if job.pending_revision is not None:
                scope_error = authoring_scope_error(job.authoring)
                if scope_error:
                    return self._stop_scoped_revision(
                        job,
                        job.pending_revision,
                        status="failed",
                        reason=f"RLO is outside POC2 authoring scope: {scope_error}",
                        actual_calls=0,
                    )
                return self._process_scoped_revision(job)
            workspace, candidate = self._workspace_candidate(job)
            scope_error = candidate_scope_error(candidate)
            if scope_error:
                stopped = job.model_copy(
                    update={
                        "state": RLODraftState.FAILED,
                        "current_operation": "POC2 scope check",
                        "error_message": (
                            f"Objective is outside POC2 authoring scope: {scope_error}"
                        ),
                        "retryable": False,
                    }
                )
                return self.store.save_draft_job(stopped, expected_state=job.state)
            materials = self.store.load_collection_source_materials(workspace.collection_id)
            snapshot = self._snapshot(workspace, candidate, materials)
            sequence = 1
            target = self._operation(
                job_id=job_id,
                operation="target-classification",
                asset=TARGET_PROMPT,
                model=ModelAlias.SOURCE_RLO_DRAFTING,
                content={
                    "approved_objective": candidate.model_dump(mode="json"),
                    "revision_instructions": [
                        review.note for review in job.reviews if review.note
                    ],
                    "suggested": self._suggested(candidate).model_dump(mode="json")
                    if self._suggested(candidate)
                    else None,
                    "valid_profiles": [
                        profile.model_dump(mode="json") for profile in PROFILES.values()
                    ],
                    "sibling_objectives": [
                        {"candidate_id": item.candidate_id, "statement": item.statement}
                        for item in workspace.candidates
                    ],
                },
                output_type=TargetPlanDraft,
                sequence=sequence,
            )
            if not is_poc2_cell(
                target.classification.content_type,
                target.classification.bloom_level,
            ):
                raise ValueError(
                    poc2_scope_reason(
                        target.classification.content_type,
                        target.classification.bloom_level,
                    )
                )
            profile = get_methodology_profile(
                target.classification.content_type, target.classification.bloom_level
            )
            job = self._progress(job, RLODraftState.MAPPING_SOURCE, "Mapping source evidence", 1)

            maps = []
            for index, tranche in enumerate(self._source_tranches(materials), start=1):
                sequence += 1
                maps.append(
                    self._operation(
                        job_id=job_id,
                        operation=f"source-mapping-{index:04d}",
                        asset=MAPPING_PROMPT,
                        model=ModelAlias.SOURCE_RLO_DRAFTING,
                        content={
                            "approved_objective": candidate.model_dump(mode="json"),
                            "target_classification": target.model_dump(mode="json"),
                            "methodology_profile": self._methodology_payload(
                                profile, include_guidance=False
                            ),
                            "source_features": [
                                feature.model_dump(mode="json")
                                for feature in workspace.source_features
                                if candidate.candidate_id in feature.candidate_ids
                            ],
                            "source_segments": tranche,
                            "tranche": {"index": index},
                            "mapping_policy_sha256": MAPPING_PROMPT.sha256,
                        },
                        output_type=SourceMapDraft,
                        sequence=sequence,
                    )
                )
                job = self._progress(
                    job,
                    RLODraftState.MAPPING_SOURCE,
                    f"Mapped source tranche {index}",
                    index + 1,
                )
            sources, evidence, claims, coverage = self._normalize_mapping(
                snapshot, materials, maps, profile
            )
            sequence += 1
            challenge = self._operation(
                job_id=job_id,
                operation="source-mapping-challenge",
                asset=CHALLENGE_PROMPT,
                model=ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
                content={
                    "approved_objective": candidate.statement,
                    "methodology_profile": self._methodology_payload(
                        profile, include_guidance=False
                    ),
                    "claims": [claim.model_dump(mode="json") for claim in claims],
                    "evidence": [item.model_dump(mode="json") for item in evidence],
                    "coverage": coverage,
                },
                output_type=MappingChallengeDraft,
                sequence=sequence,
            )
            for requirement_id in challenge.downgrade_requirement_ids:
                if requirement_id in coverage:
                    coverage[requirement_id]["status"] = PartStatus.PARTIAL
            for requirement_id in challenge.missed_requirement_ids:
                if requirement_id in coverage:
                    coverage[requirement_id]["status"] = PartStatus.ABSENT
            self.store.save_generation_checkpoint(
                job_id,
                operation="normalized-source-map",
                sequence=sequence + 1,
                input_hash=_hash({"maps": [item.model_dump(mode="json") for item in maps], "challenge": challenge.model_dump(mode="json")}),
                payload={
                    "sources": [item.model_dump(mode="json") for item in sources],
                    "evidence": [item.model_dump(mode="json") for item in evidence],
                    "claims": [item.model_dump(mode="json") for item in claims],
                    "coverage": {
                        key: {**value, "status": str(value["status"])}
                        for key, value in coverage.items()
                    },
                    "rejected_segment_ids": list(
                        dict.fromkeys(
                            segment_id
                            for source_map in maps
                            for segment_id in source_map.rejected_segment_ids
                        )
                    ),
                },
            )
            missing_requirements = [
                {
                    "requirement_id": requirement.requirement_id,
                    "part": requirement.part,
                    "description": requirement.description,
                    "source_status": coverage[requirement.requirement_id]["status"],
                    "source_gaps": coverage[requirement.requirement_id]["gaps"],
                }
                for requirement in profile.requirements
                if requirement.substantive
                and coverage[requirement.requirement_id]["status"] != PartStatus.COMPLETE
            ]
            support_profile = candidate.support_profile
            stated_knowledge_gaps = (
                support_profile.missing_knowledge if support_profile else []
            )
            llm_knowledge_provenance: list[LLMKnowledgeProvenance] = []
            unresolved_enrichment_gaps: list[str] = []
            if missing_requirements or stated_knowledge_gaps:
                job = self._progress(
                    job,
                    RLODraftState.ENRICHING_KNOWLEDGE,
                    "Adding explicitly attributed domain knowledge",
                    job.completed_operations + 1,
                )
                sequence += 1
                enrichment_content = {
                    "approved_objective": candidate.model_dump(mode="json"),
                    "target": target.model_dump(mode="json"),
                    "methodology_profile": self._methodology_payload(
                        profile, include_guidance=False
                    ),
                    "source_claims": [claim.model_dump(mode="json") for claim in claims],
                    "missing_requirements": missing_requirements,
                    "objective_support_gaps": stated_knowledge_gaps,
                    "anticipated_llm_contributions": (
                        support_profile.anticipated_llm_contributions
                        if support_profile
                        else []
                    ),
                    "enrichment_policy_sha256": ENRICHMENT_PROMPT.sha256,
                }
                enrichment = self._operation(
                    job_id=job_id,
                    operation="llm-domain-enrichment",
                    asset=ENRICHMENT_PROMPT,
                    model=ModelAlias.SOURCE_RLO_DOMAIN_ENRICHMENT,
                    content=enrichment_content,
                    output_type=LLMEnrichmentDraft,
                    sequence=sequence,
                )
                provenance = LLMKnowledgeProvenance(
                    provenance_id=f"llm-knowledge-{_hash(enrichment_content)[:16]}",
                    operation="llm-domain-enrichment",
                    model_alias=str(ModelAlias.SOURCE_RLO_DOMAIN_ENRICHMENT),
                    prompt_id=ENRICHMENT_PROMPT.prompt_id,
                    prompt_version=ENRICHMENT_PROMPT.version,
                    prompt_filename=ENRICHMENT_PROMPT.filename,
                    prompt_sha256=ENRICHMENT_PROMPT.sha256,
                    input_sha256=_hash(enrichment_content),
                    generated_at=datetime.now(timezone.utc).isoformat(),
                )
                claims.extend(
                    self._normalize_enrichment(enrichment, claims, coverage, provenance)
                )
                llm_knowledge_provenance.append(provenance)
                unresolved_enrichment_gaps = enrichment.unresolved_gaps
            job = self._progress(job, RLODraftState.GENERATING_PARTS, "Generating missing RLO parts", job.completed_operations + 1)
            elements = self._source_elements(claims, coverage, profile)
            generation_specs = (
                ("generate-teach-show", TEACH_SHOW_PROMPT, [RLOPartKind.TEACH, RLOPartKind.SHOW]),
                ("generate-practice-check", PRACTICE_CHECK_PROMPT, [RLOPartKind.PRACTICE, RLOPartKind.CHECK]),
                ("generate-setup", SETUP_PROMPT, [RLOPartKind.SETUP]),
                ("generate-sendoff", SENDOFF_PROMPT, [RLOPartKind.SEND_OFF]),
            )
            for operation, asset, kinds in generation_specs:
                sequence += 1
                operation_content = {
                    "approved_objective": candidate.model_dump(mode="json"),
                    "revision_instructions": [
                        review.note for review in job.reviews if review.note
                    ],
                    "target": target.model_dump(mode="json"),
                    "methodology_profile": self._methodology_payload(
                        profile, parts=kinds
                    ),
                    "claims": [claim.model_dump(mode="json") for claim in claims],
                    "evidence": [item.model_dump(mode="json") for item in evidence],
                    "existing_elements": {
                        kind.value: [item.model_dump(mode="json") for item in elements[kind]]
                        for kind in kinds
                    },
                    "assembled_rlo_context": {
                        kind.value: [
                            item.model_dump(mode="json") for item in elements[kind]
                        ]
                        for kind in RLOPartKind
                        if kind not in kinds and elements[kind]
                    },
                    "missing_requirements": [
                        item.model_dump(mode="json")
                        for item in profile.requirements
                        if item.part in kinds
                        and item.requirement_id not in {
                            ref for kind in kinds for element in elements[kind]
                            for ref in element.requirement_refs
                        }
                    ],
                    "generation_policy_sha256": asset.sha256,
                }
                result = self._operation(
                    job_id=job_id,
                    operation=operation,
                    asset=asset,
                    model=ModelAlias.SOURCE_RLO_DRAFTING,
                    content=operation_content,
                    output_type=PartGenerationDraft,
                    sequence=sequence,
                )
                self._append_generated(elements, result, claims, profile, sequence)
                if result.source_insufficient and result.insufficiency_reason:
                    unresolved_enrichment_gaps.append(result.insufficiency_reason)
                job = self._progress(
                    job,
                    RLODraftState.GENERATING_PARTS,
                    operation.replace("-", " ").title(),
                    job.completed_operations + 1,
                )

            job = self._progress(job, RLODraftState.ASSEMBLING, "Assembling seven-part RLO", job.completed_operations)
            suggested = self._suggested(candidate)
            classifications = RLOClassifications(
                suggested=suggested,
                target=target.classification,
            )
            parts = self._parts(job, snapshot, profile, claims, coverage, elements)
            sibling_ids = {item.candidate_id for item in workspace.candidates}

            def relationships(values):
                def convert(value):
                    if value not in sibling_ids:
                        return value
                    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
                    return f"rlo-{safe}"

                return type(values)(
                    prerequisites=[convert(value) for value in values.prerequisites],
                    corequisites=[convert(value) for value in values.corequisites],
                    follow_ons=[convert(value) for value in values.follow_ons],
                    related_rlos=[convert(value) for value in values.related_rlos],
                )

            authoring = AuthoringRLORevision(
                rlo_id=job.request.rlo_id,
                version=job.request.rlo_version,
                revision=1,
                title=candidate.statement.removeprefix("The learner will be able to ").rstrip("."),
                topic=candidate.scope,
                domain=workspace.learning_brief.lenses[0].title,
                estimated_duration_minutes=candidate.expected_effort_minutes,
                objective=AuthoringObjective(
                    candidate_id=candidate.candidate_id,
                    statement=candidate.statement,
                    performance_context=candidate.performance_context,
                    evidence_refs=[item.evidence_id for item in candidate.evidence],
                ),
                broader_outcome=candidate.terminal_outcome,
                classifications=classifications,
                methodology_profile=profile,
                sources=sources,
                evidence=evidence,
                claims=claims,
                llm_knowledge_provenance=llm_knowledge_provenance,
                parts=parts,
                relationships=relationships(target.relationship_candidate_ids),
                provenance=GenerationProvenance(
                    rules_version=RULES_VERSION,
                    authoring_schema_version="source-rlo-authoring-v3",
                    methodology_profile_id=profile.profile_id,
                    methodology_profile_version=profile.version,
                    operation_ids=[
                        item.operation
                        for item in self.store.list_generation_checkpoints(job_id)
                        if not item.operation.startswith(
                            ("validate-", "targeted-repair", "collection-validation-")
                        )
                    ],
                ),
                authoring_revision_id=f"{job.request.rlo_id}:{job.request.rlo_version}:1",
            )
            job = self._progress(job, RLODraftState.VALIDATING, "Validating grounding and pedagogy", job.completed_operations + 1)
            sequence += 1
            grounding = self._operation(
                job_id=job_id,
                operation="validate-grounding",
                asset=GROUNDING_PROMPT,
                model=ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
                content={
                    "authoring": authoring.model_dump(mode="json"),
                    "validation_policy_sha256": GROUNDING_PROMPT.sha256,
                },
                output_type=AuthoringReviewDraft,
                sequence=sequence,
            )
            sequence += 1
            provenance_review = self._operation(
                job_id=job_id,
                operation="validate-provenance",
                asset=PROVENANCE_PROMPT,
                model=ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
                content={
                    "authoring": authoring.model_dump(mode="json"),
                    "validation_policy_sha256": PROVENANCE_PROMPT.sha256,
                },
                output_type=AuthoringReviewDraft,
                sequence=sequence,
            )
            sequence += 1
            pedagogy = self._operation(
                job_id=job_id,
                operation="validate-pedagogy",
                asset=PEDAGOGY_PROMPT,
                model=ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW,
                content={
                    "authoring": authoring.model_dump(mode="json"),
                    "validation_policy_sha256": PEDAGOGY_PROMPT.sha256,
                },
                output_type=AuthoringReviewDraft,
                sequence=sequence,
            )
            findings = [
                *self._deterministic_findings(authoring),
                *self._admissible_pedagogy_findings(grounding.findings),
                *self._admissible_pedagogy_findings(provenance_review.findings),
                *self._admissible_pedagogy_findings(pedagogy.findings),
            ]
            findings.extend(
                AuthoringFinding(
                    code="unresolved_knowledge_gap",
                    severity="escalate",
                    category="grounding",
                    path="claims",
                    message=gap,
                )
                for gap in dict.fromkeys(unresolved_enrichment_gaps)
            )
            observed = pedagogy.observed_classification or target.classification
            if (
                observed.content_type != target.classification.content_type
                or observed.bloom_level != target.classification.bloom_level
            ):
                findings.append(
                    AuthoringFinding(
                        code="target_observed_mismatch",
                        severity="error",
                        category="classification",
                        path="classifications.observed",
                        message=(
                            "The completed RLO does not implement its Target content-kind × "
                            "Bloom cell."
                        ),
                        repairable=True,
                    )
                )
            authoring = authoring.model_copy(
                update={
                    "classifications": classifications.model_copy(update={"observed": observed}),
                    "findings": findings,
                    "guidance_assessments": self._admissible_guidance_assessments(
                        profile, pedagogy.guidance_assessments
                    ),
                }
            )
            repairable = [
                item for item in findings if item.severity == "error" and item.repairable
            ]
            if repairable:
                job = job.model_copy(
                    update={
                        "authoring": authoring,
                        "findings": [
                            DraftValidationFinding(**item.model_dump(mode="json"))
                            for item in findings
                        ],
                    }
                )
                job = self.store.save_draft_job(job, expected_state=job.state)
                job = self._progress(
                    job,
                    RLODraftState.REPAIRING,
                    "Repairing named validation findings",
                    job.completed_operations,
                )
                sequence += 1
                repair = self._operation(
                    job_id=job_id,
                    operation="targeted-repair",
                    asset=REPAIR_PROMPT,
                    model=ModelAlias.SOURCE_RLO_DRAFTING,
                    content={
                        "authoring": authoring.model_dump(mode="json"),
                        "repairable_findings": [
                            item.model_dump(mode="json") for item in repairable
                        ],
                        "repair_policy_sha256": REPAIR_PROMPT.sha256,
                    },
                    output_type=PartGenerationDraft,
                    sequence=sequence,
                )
                self._append_generated(elements, repair, claims, profile, sequence)
                if repair.source_insufficient and repair.insufficiency_reason:
                    unresolved_enrichment_gaps.append(repair.insufficiency_reason)
                repaired_parts = self._parts(
                    job, snapshot, profile, claims, coverage, elements
                )
                authoring = AuthoringRLORevision.model_validate(
                    {
                        **authoring.model_dump(mode="json"),
                        "parts": [part.model_dump(mode="json") for part in repaired_parts],
                        "findings": [],
                    }
                )
                job = self._progress(
                    job,
                    RLODraftState.VALIDATING,
                    "Revalidating repaired RLO",
                    job.completed_operations + 1,
                )
                sequence += 1
                grounding = self._operation(
                    job_id=job_id,
                    operation="validate-grounding-after-repair",
                    asset=GROUNDING_PROMPT,
                    model=ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
                    content={
                        "authoring": authoring.model_dump(mode="json"),
                        "validation_policy_sha256": GROUNDING_PROMPT.sha256,
                    },
                    output_type=AuthoringReviewDraft,
                    sequence=sequence,
                )
                sequence += 1
                provenance_review = self._operation(
                    job_id=job_id,
                    operation="validate-provenance-after-repair",
                    asset=PROVENANCE_PROMPT,
                    model=ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
                    content={
                        "authoring": authoring.model_dump(mode="json"),
                        "validation_policy_sha256": PROVENANCE_PROMPT.sha256,
                    },
                    output_type=AuthoringReviewDraft,
                    sequence=sequence,
                )
                sequence += 1
                pedagogy = self._operation(
                    job_id=job_id,
                    operation="validate-pedagogy-after-repair",
                    asset=PEDAGOGY_PROMPT,
                    model=ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW,
                    content={
                        "authoring": authoring.model_dump(mode="json"),
                        "validation_policy_sha256": PEDAGOGY_PROMPT.sha256,
                    },
                    output_type=AuthoringReviewDraft,
                    sequence=sequence,
                )
                observed = pedagogy.observed_classification or target.classification
                findings = [
                    *self._deterministic_findings(authoring),
                    *self._admissible_pedagogy_findings(grounding.findings),
                    *self._admissible_pedagogy_findings(provenance_review.findings),
                    *self._admissible_pedagogy_findings(pedagogy.findings),
                ]
                findings.extend(
                    AuthoringFinding(
                        code="unresolved_knowledge_gap",
                        severity="escalate",
                        category="grounding",
                        path="claims",
                        message=gap,
                    )
                    for gap in dict.fromkeys(unresolved_enrichment_gaps)
                )
                if (
                    observed.content_type != target.classification.content_type
                    or observed.bloom_level != target.classification.bloom_level
                ):
                    findings.append(
                        AuthoringFinding(
                            code="target_observed_mismatch",
                            severity="error",
                            category="classification",
                            path="classifications.observed",
                            message=(
                                "The repaired RLO still does not implement its Target "
                                "content-kind × Bloom cell."
                            ),
                        )
                    )
                authoring = authoring.model_copy(
                    update={
                        "classifications": classifications.model_copy(
                            update={"observed": observed}
                        ),
                        "findings": findings,
                        "guidance_assessments": self._admissible_guidance_assessments(
                            profile, pedagogy.guidance_assessments
                        ),
                    }
                )
                second_repairable = [
                    item
                    for item in findings
                    if item.severity == "error" and item.repairable
                ]
                if second_repairable:
                    job = job.model_copy(
                        update={
                            "authoring": authoring,
                            "findings": [
                                DraftValidationFinding(**item.model_dump(mode="json"))
                                for item in findings
                            ],
                        }
                    )
                    job = self.store.save_draft_job(job, expected_state=job.state)
                    job = self._progress(
                        job,
                        RLODraftState.REPAIRING,
                        "Repairing remaining validation findings",
                        job.completed_operations,
                    )
                    sequence += 1
                    second_repair = self._operation(
                        job_id=job_id,
                        operation="targeted-repair-2",
                        asset=REPAIR_PROMPT,
                        model=ModelAlias.SOURCE_RLO_DRAFTING,
                        content={
                            "authoring": authoring.model_dump(mode="json"),
                            "repairable_findings": [
                                item.model_dump(mode="json")
                                for item in second_repairable
                            ],
                            "repair_policy_sha256": REPAIR_PROMPT.sha256,
                        },
                        output_type=PartGenerationDraft,
                        sequence=sequence,
                    )
                    self._append_generated(
                        elements, second_repair, claims, profile, sequence
                    )
                    if (
                        second_repair.source_insufficient
                        and second_repair.insufficiency_reason
                    ):
                        unresolved_enrichment_gaps.append(
                            second_repair.insufficiency_reason
                        )
                    repaired_parts = self._parts(
                        job, snapshot, profile, claims, coverage, elements
                    )
                    authoring = AuthoringRLORevision.model_validate(
                        {
                            **authoring.model_dump(mode="json"),
                            "parts": [
                                part.model_dump(mode="json") for part in repaired_parts
                            ],
                            "findings": [],
                        }
                    )
                    job = self._progress(
                        job,
                        RLODraftState.VALIDATING,
                        "Revalidating second repair",
                        job.completed_operations + 1,
                    )
                    sequence += 1
                    grounding = self._operation(
                        job_id=job_id,
                        operation="validate-grounding-after-repair-2",
                        asset=GROUNDING_PROMPT,
                        model=ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
                        content={
                            "authoring": authoring.model_dump(mode="json"),
                            "validation_policy_sha256": GROUNDING_PROMPT.sha256,
                        },
                        output_type=AuthoringReviewDraft,
                        sequence=sequence,
                    )
                    sequence += 1
                    provenance_review = self._operation(
                        job_id=job_id,
                        operation="validate-provenance-after-repair-2",
                        asset=PROVENANCE_PROMPT,
                        model=ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
                        content={
                            "authoring": authoring.model_dump(mode="json"),
                            "validation_policy_sha256": PROVENANCE_PROMPT.sha256,
                        },
                        output_type=AuthoringReviewDraft,
                        sequence=sequence,
                    )
                    sequence += 1
                    pedagogy = self._operation(
                        job_id=job_id,
                        operation="validate-pedagogy-after-repair-2",
                        asset=PEDAGOGY_PROMPT,
                        model=ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW,
                        content={
                            "authoring": authoring.model_dump(mode="json"),
                            "validation_policy_sha256": PEDAGOGY_PROMPT.sha256,
                        },
                        output_type=AuthoringReviewDraft,
                        sequence=sequence,
                    )
                    observed = pedagogy.observed_classification or target.classification
                    findings = [
                        *self._deterministic_findings(authoring),
                        *self._admissible_pedagogy_findings(grounding.findings),
                        *self._admissible_pedagogy_findings(
                            provenance_review.findings
                        ),
                        *self._admissible_pedagogy_findings(pedagogy.findings),
                    ]
                    findings.extend(
                        AuthoringFinding(
                            code="unresolved_knowledge_gap",
                            severity="escalate",
                            category="grounding",
                            path="claims",
                            message=gap,
                        )
                        for gap in dict.fromkeys(unresolved_enrichment_gaps)
                    )
                    if (
                        observed.content_type != target.classification.content_type
                        or observed.bloom_level != target.classification.bloom_level
                    ):
                        findings.append(
                            AuthoringFinding(
                                code="target_observed_mismatch",
                                severity="error",
                                category="classification",
                                path="classifications.observed",
                                message=(
                                    "The twice-repaired RLO still does not implement "
                                    "its Target content-kind × Bloom cell."
                                ),
                            )
                        )
                    authoring = authoring.model_copy(
                        update={
                            "classifications": classifications.model_copy(
                                update={"observed": observed}
                            ),
                            "findings": findings,
                            "guidance_assessments": self._admissible_guidance_assessments(
                                profile, pedagogy.guidance_assessments
                            ),
                        }
                    )
            catalog = None
            has_error = any(item.severity in {"error", "escalate"} for item in findings)
            if not has_error:
                catalog = adapt_authoring_rlo(authoring)
            state = RLODraftState.VALIDATION_FAILED if has_error else RLODraftState.IN_REVIEW
            final = job.model_copy(
                update={
                    "state": state,
                    "current_operation": "Ready for Instructional Designer review",
                    "completed_operations": job.completed_operations + 2,
                    "snapshot": snapshot,
                    "authoring": authoring,
                    "draft": catalog,
                    "revision": 1,
                    "findings": [
                        DraftValidationFinding(**item.model_dump(mode="json"))
                        for item in findings
                    ],
                    "retryable": state in {
                        RLODraftState.VALIDATION_FAILED,
                    },
                    "error_message": None,
                }
            )
            result = self.store.save_draft_job(
                final,
                expected_state=job.state,
                save_revision=catalog is not None,
            )
            if result.batch_id:
                self.store.refresh_generation_batch(result.batch_id)
            return result
        except Exception as exc:
            current = self.store.get_draft_job(job_id)
            if current and current.pending_revision is not None:
                prefix = f"scoped-revision-{current.pending_revision.revision_id}-"
                actual_calls = sum(
                    run.operation.startswith(prefix)
                    for run in self.store.list_generation_prompt_runs(job_id)
                )
                return self._stop_scoped_revision(
                    current,
                    current.pending_revision,
                    status="failed",
                    reason=str(exc),
                    actual_calls=actual_calls,
                )
            if (
                isinstance(exc, ValidationError)
                and current
                and current.state == RLODraftState.REPAIRING
                and current.authoring is not None
            ):
                invalid_repair = AuthoringFinding(
                    code="REPAIR_OUTPUT_INVALID",
                    severity="escalate",
                    category="pedagogy",
                    path="targeted-repair",
                    message=(
                        "The targeted repair response did not satisfy the generated "
                        "element contract. The pre-repair authoring and validation "
                        "findings were preserved for review."
                    ),
                    repairable=False,
                )
                authoring = current.authoring.model_copy(
                    update={
                        "findings": [*current.authoring.findings, invalid_repair]
                    }
                )
                validation_failed = current.model_copy(
                    update={
                        "state": RLODraftState.VALIDATION_FAILED,
                        "current_operation": "Ready for Instructional Designer review",
                        "authoring": authoring,
                        "findings": [
                            *current.findings,
                            DraftValidationFinding(
                                **invalid_repair.model_dump(mode="json")
                            ),
                        ],
                        "retryable": True,
                        "error_message": None,
                    }
                )
                result = self.store.save_draft_job(
                    validation_failed,
                    expected_state=current.state,
                )
                if result.batch_id:
                    self.store.refresh_generation_batch(result.batch_id)
                return result
            if current and current.state in {
                RLODraftState.PLANNING,
                RLODraftState.MAPPING_SOURCE,
                RLODraftState.ENRICHING_KNOWLEDGE,
                RLODraftState.GENERATING_PARTS,
                RLODraftState.ASSEMBLING,
                RLODraftState.VALIDATING,
                RLODraftState.REPAIRING,
            }:
                failed = current.model_copy(
                    update={
                        "state": RLODraftState.FAILED,
                        "current_operation": (
                            "Evidence context invalid"
                            if isinstance(exc, EvidenceContextError)
                            else current.current_operation
                        ),
                        "error_message": str(exc),
                        "retryable": True,
                    }
                )
                self.store.save_draft_job(failed, expected_state=current.state)
                if failed.batch_id:
                    self.store.refresh_generation_batch(failed.batch_id)
            raise

    def process_collection(self, batch_id: str) -> None:
        """Run the deferred cross-RLO review after an objective set is finalized."""

        batch = self.store.get_generation_batch(batch_id)
        if batch is None:
            raise ValueError("RLO generation batch does not exist")
        if not batch.finalized or str(batch.state) not in {"in_review", "complete"}:
            raise ValueError("RLO generation batch is not ready for collection validation")
        siblings = self.store.list_draft_jobs(batch_id=batch_id)
        reviewable = [
            sibling.authoring.model_dump(mode="json")
            for sibling in siblings
            if sibling.authoring is not None
        ]
        if not reviewable:
            self.store.complete_collection_validation(batch_id, [])
            return
        anchor = next(sibling for sibling in siblings if sibling.authoring is not None)
        checkpoints = self.store.list_generation_checkpoints(anchor.job_id)
        collection = self._operation(
            job_id=anchor.job_id,
            operation=f"collection-validation-{batch_id}",
            asset=COLLECTION_PROMPT,
            model=ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW,
            content={"rlos": reviewable},
            output_type=CollectionReviewDraft,
            sequence=max((item.sequence for item in checkpoints), default=0) + 1,
        )
        self.store.complete_collection_validation(batch_id, collection.findings)
