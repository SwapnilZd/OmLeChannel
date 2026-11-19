"""Catalog API client and deterministic RLO discovery policy."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from rlo_schema import RLO

from ..adapters.rlo import RLOCompatibilityError, adapt_stored_rlo
from ..contracts import (
    ContentGap,
    ContentGapReport,
    GapSeverity,
    LearningCommissionRequest,
    LearningSearchIntent,
    RelevanceBand,
    RLOCandidateMatch,
)

RETRIEVAL_POLICY_VERSION = "retrieval-v2"
RRF_K = 60
DEFAULT_RESULT_LIMIT = 10
STRONG_THRESHOLD = 0.65
ACCEPTABLE_THRESHOLD = 0.52
WEAK_THRESHOLD = 0.35
INSUFFICIENT_MESSAGE = (
    "The catalog does not contain sufficient approved RLO content for this request. "
    "Add or revise RLOs before creating a course blueprint."
)
_PROFICIENCY_LEVEL = {
    "beginner": "introductory",
    "intermediate": "intermediate",
    "advanced": "advanced",
}
_LEVEL_ORDER = {"introductory": 0, "intermediate": 1, "advanced": 2}


class CatalogUnavailableError(RuntimeError):
    pass


class CatalogSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rlo_id: str
    rlo_version: str
    score: float
    title: str
    topic: str
    domain: str
    level: str
    language: str
    locale: str
    estimated_duration_minutes: int | None
    governance_status: str
    audience: list[str] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    service_line_tags: list[str] = Field(default_factory=list)
    competency_tags: list[str] = Field(default_factory=list)
    regulatory_tags: list[str] = Field(default_factory=list)
    storage_uri: str


class CatalogSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    hits: list[CatalogSearchHit]


class CatalogBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index_revision: str
    embedding_model: str
    results: list[CatalogSearchResult]


class CatalogClient:
    """Typed HTTP boundary; commissioning never accesses Qdrant directly."""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=20)

    async def search_batch(self, payload: dict[str, Any]) -> CatalogBatchResponse:
        try:
            response = await self.client.post(f"{self.base_url}/api/rlo-search/batch", json=payload)
            response.raise_for_status()
            return CatalogBatchResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise CatalogUnavailableError(f"RLO catalog search failed: {exc}") from exc

    async def get_exact(self, rlo_id: str, rlo_version: str) -> dict[str, Any]:
        url = (
            f"{self.base_url}/api/rlos/{quote(rlo_id, safe='')}/versions/"
            f"{quote(rlo_version, safe='')}"
        )
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CatalogUnavailableError(
                f"Exact RLO {rlo_id}@{rlo_version} could not be hydrated: {exc}"
            ) from exc

    async def get_versions(self, rlo_id: str) -> list[dict[str, Any]]:
        url = f"{self.base_url}/api/rlos/{quote(rlo_id, safe='')}/versions"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, list):
                raise ValueError("catalog returned a non-list versions response")
            return value
        except (httpx.HTTPError, ValueError) as exc:
            raise CatalogUnavailableError(f"RLO version lookup failed: {exc}") from exc


@dataclass(frozen=True)
class RetrievalOutcome:
    candidates: tuple[RLOCandidateMatch, ...]
    gap_report: ContentGapReport
    index_revision: str
    embedding_model: str
    compatibility_errors: tuple[str, ...] = ()


def _overlap(left: list[str], right: tuple[str, ...]) -> list[str]:
    wanted = {value.casefold() for value in right}
    return [value for value in left if value.casefold() in wanted]


def _semantic_tag_matches(tags: list[str], values: tuple[str, ...]) -> list[str]:
    haystack = " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()) for value in values)
    matches = []
    for tag in tags:
        normalized = re.sub(r"[^a-z0-9]+", " ", tag.casefold()).strip()
        if normalized and normalized in haystack:
            matches.append(tag)
    return matches


def _band(score: float) -> RelevanceBand:
    if score >= STRONG_THRESHOLD:
        return RelevanceBand.STRONG
    if score >= ACCEPTABLE_THRESHOLD:
        return RelevanceBand.ACCEPTABLE
    if score >= WEAK_THRESHOLD:
        return RelevanceBand.WEAK
    return RelevanceBand.FORBIDDEN


class RLODiscoveryService:
    def __init__(self, catalog: CatalogClient, *, result_limit: int = DEFAULT_RESULT_LIMIT) -> None:
        self.catalog = catalog
        self.result_limit = result_limit

    async def discover(
        self,
        request: LearningCommissionRequest,
        intent: LearningSearchIntent,
    ) -> RetrievalOutcome:
        industry_filter = (
            list(request.audience.industries) if request.industry_filter_mode == "required" else []
        )
        query_ids = [f"facet-{index + 1}" for index in range(len(intent.search_queries))]
        payload = {
            "queries": [
                {
                    "query_id": query_id,
                    "text": text,
                    "limit": self.result_limit,
                    "filters": {
                        "languages": [request.audience.language],
                        "locales": [request.audience.locale],
                        "statuses": ["approved"],
                        "industry_tags": industry_filter,
                        "excluded_rlo_ids": list(request.excluded_rlo_ids),
                        "active_only": True,
                    },
                }
                for query_id, text in zip(query_ids, intent.search_queries, strict=True)
            ]
        }
        response = await self.catalog.search_batch(payload)
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for result in response.results:
            for rank, hit in enumerate(result.hits, start=1):
                key = (hit.rlo_id, hit.rlo_version)
                entry = by_key.setdefault(key, {"hit": hit, "scores": {}, "rrf": 0.0})
                entry["scores"][result.query_id] = hit.score
                entry["rrf"] += 1 / (RRF_K + rank)

        hydrated = await asyncio.gather(
            *(self.catalog.get_exact(*key) for key in by_key),
            return_exceptions=True,
        )
        candidates: list[RLOCandidateMatch] = []
        hydrated_rlos: dict[tuple[str, str], RLO] = {}
        compatibility_errors: list[str] = []
        for (key, entry), raw in zip(by_key.items(), hydrated, strict=True):
            if isinstance(raw, BaseException):
                compatibility_errors.append(f"{key[0]}@{key[1]}: {raw}")
                continue
            try:
                shared = RLO.model_validate(raw)
                hit: CatalogSearchHit = entry["hit"]
                if (shared.id, shared.version) != key:
                    raise RLOCompatibilityError(shared.id, "hydrated document identity differs from search hit")
                if shared.governance.status.value != hit.governance_status:
                    raise RLOCompatibilityError(shared.id, "governance state differs from search index")
                assembly_rlo = adapt_stored_rlo(shared)
            except (RLOCompatibilityError, ValueError) as exc:
                compatibility_errors.append(f"{key[0]}@{key[1]}: {exc}")
                continue

            hydrated_rlos[key] = shared

            reasons = ["Semantic match to " + ", ".join(sorted(entry["scores"]))]
            boost = 0.0
            industries = _overlap(hit.industry_tags, request.audience.industries)
            roles = _overlap(hit.role_tags, request.audience.roles)
            service_lines = _overlap(hit.service_line_tags, request.audience.service_lines)
            competencies = _semantic_tag_matches(
                hit.competency_tags,
                (intent.primary_subject,) + intent.skills + intent.required_concepts,
            )
            regulatory = _semantic_tag_matches(
                hit.regulatory_tags,
                (request.request_text,)
                + request.stated_goals
                + tuple(request.audience.business_context.values()),
            )
            if industries:
                boost += min(0.08, 0.04 * len(industries))
                reasons.append("Industry match: " + ", ".join(industries))
            if roles:
                boost += min(0.08, 0.04 * len(roles))
                reasons.append("Role match: " + ", ".join(roles))
            if service_lines:
                boost += min(0.08, 0.04 * len(service_lines))
                reasons.append("Service-line match: " + ", ".join(service_lines))
            if competencies:
                boost += min(0.06, 0.03 * len(competencies))
                reasons.append("Competency match: " + ", ".join(competencies))
            if regulatory:
                boost += min(0.06, 0.03 * len(regulatory))
                reasons.append("Regulatory-context match: " + ", ".join(regulatory))
            target_level = _PROFICIENCY_LEVEL[request.audience.target_proficiency.value]
            distance = abs(_LEVEL_ORDER.get(hit.level, 99) - _LEVEL_ORDER[target_level])
            if distance == 0:
                boost += 0.05
                reasons.append(f"Content level matches target proficiency ({target_level})")
            elif distance == 1:
                boost += 0.02
                reasons.append(f"Content level is adjacent to target proficiency ({target_level})")
            if hit.rlo_id in request.required_rlo_ids:
                boost += 0.1
                reasons.append("Explicitly required by requester")

            max_vector_score = max(entry["scores"].values())
            final_score = max_vector_score + entry["rrf"] + boost
            candidates.append(RLOCandidateMatch(
                rlo_id=assembly_rlo.id,
                rlo_version=assembly_rlo.version,
                title=assembly_rlo.title,
                topic=assembly_rlo.topic,
                domain=assembly_rlo.domain,
                level=assembly_rlo.level,
                estimated_duration_minutes=assembly_rlo.estimated_duration_minutes,
                governance_status=hit.governance_status,
                vector_scores=dict(entry["scores"]),
                reciprocal_rank_fusion_score=entry["rrf"],
                facet_boost_score=boost,
                final_score=final_score,
                # Context boosts may reorder semantically relevant content but
                # must never promote an unrelated RLO into an eligible band.
                relevance_band=_band(max_vector_score),
                match_reasons=tuple(reasons),
                source_query_ids=tuple(sorted(entry["scores"])),
                storage_uri=hit.storage_uri,
                index_revision=response.index_revision,
            ))

        # Semantic search finds relevant content, but prerequisites are
        # authoritative catalog relationships rather than search terms. Expand
        # the complete prerequisite graph so curation and confirmation see the
        # same dependency set that curriculum assembly will validate later.
        candidate_by_key = {
            (candidate.rlo_id, candidate.rlo_version): candidate
            for candidate in candidates
        }
        dependency_parents: dict[tuple[str, str], set[str]] = {}
        dependency_gaps: list[ContentGap] = []
        reported_dependency_failures: set[tuple[str, str]] = set()

        def add_dependency_gap(prerequisite_id: str, dependent_id: str, reason: str) -> None:
            failure_key = (prerequisite_id, dependent_id)
            if failure_key in reported_dependency_failures:
                return
            reported_dependency_failures.add(failure_key)
            dependency_gaps.append(ContentGap(
                subject=f"prerequisite {prerequisite_id}",
                severity=GapSeverity.BLOCKING,
                explanation=(
                    f"RLO '{dependent_id}' requires '{prerequisite_id}', but the prerequisite "
                    f"cannot be included in candidate review: {reason}."
                ),
                nearest_candidate_ids=(dependent_id,),
                filters_responsible=("prerequisite_dependency",),
                recommendation=(
                    "Restore an active, approved, assembly-compatible prerequisite or exclude "
                    f"the dependent RLO '{dependent_id}'."
                ),
            ))

        pending = [
            key for key, candidate in candidate_by_key.items()
            if candidate.relevance_band != RelevanceBand.FORBIDDEN
        ]
        expanded: set[tuple[str, str]] = set()
        while pending:
            parent_key = pending.pop(0)
            if parent_key in expanded:
                continue
            expanded.add(parent_key)
            parent = hydrated_rlos[parent_key]
            for prerequisite_id in parent.prerequisites:
                if prerequisite_id in request.excluded_rlo_ids:
                    add_dependency_gap(
                        prerequisite_id,
                        parent.id,
                        "it was explicitly excluded by the requester",
                    )
                    continue
                try:
                    versions = await self.catalog.get_versions(prerequisite_id)
                    current = next(
                        (item for item in versions if item.get("is_current")),
                        None,
                    )
                    if current is None or not current.get("rlo_version"):
                        raise ValueError("the catalog has no current version")
                    prerequisite_version = str(current["rlo_version"])
                    prerequisite_key = (prerequisite_id, prerequisite_version)
                    dependency_parents.setdefault(prerequisite_key, set()).add(parent.id)

                    if prerequisite_key not in candidate_by_key:
                        raw = await self.catalog.get_exact(*prerequisite_key)
                        shared = RLO.model_validate(raw)
                        if (shared.id, shared.version) != prerequisite_key:
                            raise RLOCompatibilityError(
                                shared.id,
                                "hydrated document identity differs from current version metadata",
                            )
                        if shared.governance.status.value not in {"approved", "signed"}:
                            raise RLOCompatibilityError(
                                shared.id,
                                f"governance status is {shared.governance.status.value!r}",
                            )
                        assembly_rlo = adapt_stored_rlo(shared)
                        storage_uri = str(
                            current.get("storage_uri")
                            or f"catalog://rlos/{prerequisite_id}/{prerequisite_version}"
                        )
                        candidate_by_key[prerequisite_key] = RLOCandidateMatch(
                            rlo_id=assembly_rlo.id,
                            rlo_version=assembly_rlo.version,
                            title=assembly_rlo.title,
                            topic=assembly_rlo.topic,
                            domain=assembly_rlo.domain,
                            level=assembly_rlo.level,
                            estimated_duration_minutes=assembly_rlo.estimated_duration_minutes,
                            governance_status=shared.governance.status.value,
                            vector_scores={},
                            reciprocal_rank_fusion_score=0.0,
                            facet_boost_score=0.0,
                            final_score=0.0,
                            relevance_band=RelevanceBand.ACCEPTABLE,
                            match_reasons=(
                                f"Required prerequisite for {parent.id}",
                            ),
                            source_query_ids=("dependency-closure",),
                            required_as_prerequisite_for=(parent.id,),
                            storage_uri=storage_uri,
                            index_revision=response.index_revision,
                        )
                        hydrated_rlos[prerequisite_key] = shared
                    pending.append(prerequisite_key)
                except (CatalogUnavailableError, RLOCompatibilityError, ValueError) as exc:
                    compatibility_errors.append(
                        f"{prerequisite_id} (prerequisite of {parent.id}): {exc}"
                    )
                    add_dependency_gap(prerequisite_id, parent.id, str(exc))

        for key, parents in dependency_parents.items():
            candidate = candidate_by_key.get(key)
            if candidate is None:
                continue
            parent_ids = tuple(sorted(parents))
            dependency_reason = "Required prerequisite for: " + ", ".join(parent_ids)
            reasons = tuple(dict.fromkeys((*candidate.match_reasons, dependency_reason)))
            updates: dict[str, Any] = {
                "required_as_prerequisite_for": parent_ids,
                "match_reasons": reasons,
            }
            if candidate.relevance_band in (RelevanceBand.WEAK, RelevanceBand.FORBIDDEN):
                updates["relevance_band"] = RelevanceBand.ACCEPTABLE
            candidate_by_key[key] = candidate.model_copy(update=updates)

        candidates = list(candidate_by_key.values())

        candidates.sort(key=lambda candidate: (-candidate.final_score, candidate.rlo_id))
        gaps: list[ContentGap] = list(dependency_gaps)
        covered_facets: list[str] = []
        covered_goals: list[str] = []
        acceptable = {RelevanceBand.STRONG, RelevanceBand.ACCEPTABLE}
        for index, (query_id, facet) in enumerate(
            zip(query_ids, intent.subject_facets, strict=True)
        ):
            covering = [
                candidate for candidate in candidates
                if query_id in candidate.source_query_ids and candidate.relevance_band in acceptable
            ]
            outcome = intent.desired_outcomes[index] if index < len(intent.desired_outcomes) else None
            if covering:
                covered_facets.append(facet)
                if outcome:
                    covered_goals.append(outcome)
                continue
            nearest = tuple(
                candidate.rlo_id for candidate in candidates if query_id in candidate.source_query_ids
            )[:3]
            gaps.append(ContentGap(
                subject=facet,
                desired_outcome=outcome,
                severity=GapSeverity.BLOCKING,
                explanation="No compatible, approved RLO is an acceptable match for this required subject facet.",
                nearest_candidate_ids=nearest,
                filters_responsible=("assembly_compatibility",) if compatibility_errors else (),
                recommendation="Add or approve an RLO for this subject before creating a blueprint.",
            ))

        candidate_ids = {candidate.rlo_id for candidate in candidates}
        for required_id in request.required_rlo_ids:
            if required_id not in candidate_ids:
                gaps.append(ContentGap(
                    subject=f"required RLO {required_id}",
                    severity=GapSeverity.BLOCKING,
                    explanation="The explicitly required RLO was not returned as an active, approved, compatible match.",
                    nearest_candidate_ids=(),
                    filters_responsible=("required_rlo",),
                    recommendation="Approve or repair the required RLO, or remove the requirement.",
                ))

        sufficient = not any(gap.severity == GapSeverity.BLOCKING for gap in gaps)
        report = ContentGapReport(
            sufficient=sufficient,
            covered_subject_facets=tuple(covered_facets),
            covered_goals=tuple(covered_goals),
            gaps=tuple(gaps),
            retrieval_policy_version=RETRIEVAL_POLICY_VERSION,
            explanation=(
                "Approved, compatible RLO content covers every required subject facet."
                if sufficient else INSUFFICIENT_MESSAGE
            ),
        )
        return RetrievalOutcome(
            candidates=tuple(candidates),
            gap_report=report,
            index_revision=response.index_revision,
            embedding_model=response.embedding_model,
            compatibility_errors=tuple(compatibility_errors),
        )
