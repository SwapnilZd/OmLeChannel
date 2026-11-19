"""
API data-transfer objects for the ingestion endpoints.

The RLO content schema itself lives in `schemas/` (version-dispatched). These
models describe only the API's request/response envelopes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RloListItem(BaseModel):
    id: str
    title: str
    topic: str
    domain: str
    level: str
    status: str
    schema_version: str
    rlo_version: str
    storage_uri: str


class IngestResponse(BaseModel):
    rlo_id: str
    schema_version: str
    rlo_version: str
    title: str
    topic: str
    domain: str
    level: str
    concepts: int
    components: int
    assessment_items: int
    storage_uri: str
    indexed: bool
    message: str


class RloVersionItem(BaseModel):
    rlo_id: str
    rlo_version: str
    is_current: bool
    storage_uri: str


class RloSearchFilters(BaseModel):
    languages: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=lambda: ["approved"])
    levels: list[str] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    service_line_tags: list[str] = Field(default_factory=list)
    competency_tags: list[str] = Field(default_factory=list)
    regulatory_tags: list[str] = Field(default_factory=list)
    excluded_rlo_ids: list[str] = Field(default_factory=list)
    active_only: bool = True


class RloSearchQuery(BaseModel):
    query_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=10, ge=1, le=50)
    filters: RloSearchFilters = Field(default_factory=RloSearchFilters)


class RloBatchSearchRequest(BaseModel):
    queries: list[RloSearchQuery] = Field(min_length=1, max_length=4)


class RloSearchHit(BaseModel):
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


class RloSearchResult(BaseModel):
    query_id: str
    hits: list[RloSearchHit]


class RloBatchSearchResponse(BaseModel):
    index_revision: str
    embedding_model: str
    results: list[RloSearchResult]
