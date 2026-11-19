"""Versioned, format-neutral contracts for source extraction artifacts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_MIGRATION_POLICY = {
    "extracted-document-v1": "read-write",
    "source-artifacts-v1": "read-write",
    "source-quality-v1": "read-write",
    "source-segment-v1": "read-write",
    "source-retrieval-hit-v1": "read-write",
    "source-section-map-v1": "read-write",
    "source-document-map-v1": "read-write",
    "source-collection-map-v1": "read-write",
}
"""Known versions are explicit; unknown versions fail rather than auto-coerce."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceFormat(StrEnum):
    PDF = "pdf"
    PPTX = "pptx"
    EPUB = "epub"


class ExtractionMethod(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    DERIVED = "derived"
    UNKNOWN = "unknown"


class RelationshipType(StrEnum):
    CAPTION_OF = "caption_of"
    FOOTNOTE_OF = "footnote_of"
    CITES = "cites"
    SPEAKER_NOTE_OF = "speaker_note_of"
    CROSS_REFERENCE = "cross_reference"
    TABLE_CELL_OF = "table_cell_of"
    VISUAL_EXPLANATION_OF = "visual_explanation_of"


class SourceLocator(StrictModel):
    page: int | None = Field(default=None, ge=1)
    slide: int | None = Field(default=None, ge=1)
    chapter: int | None = Field(default=None, ge=1)
    href: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def exactly_one_extent(self) -> "SourceLocator":
        if sum(value is not None for value in (self.page, self.slide, self.chapter)) != 1:
            raise ValueError("locator must identify exactly one page, slide, or chapter")
        if self.bbox is not None:
            left, top, right, bottom = self.bbox
            if min(self.bbox) < 0 or right <= left or bottom <= top:
                raise ValueError("bbox must be non-negative with positive area")
        return self


class DocumentNode(StrictModel):
    node_id: str = Field(min_length=1)
    parent_id: str | None = None
    ordinal: int = Field(ge=0)
    ordinal_path: tuple[int, ...] = Field(min_length=1)
    kind: str = Field(min_length=1)
    role: str = Field(min_length=1)
    native_ref: str | None = None
    text: str | None = None
    asset_id: str | None = None
    locators: list[SourceLocator] = Field(min_length=1)
    method: ExtractionMethod
    confidence: float | None = Field(default=None, ge=0, le=1)
    child_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_or_asset(self) -> "DocumentNode":
        if self.text is None and self.asset_id is None and not self.child_ids:
            raise ValueError("node must contain text, an asset, or children")
        return self


class NodeRelationship(StrictModel):
    relationship_id: str = Field(min_length=1)
    type: RelationshipType
    source_node_id: str
    target_node_id: str
    ordinal: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def distinct_nodes(self) -> "NodeRelationship":
        if self.source_node_id == self.target_node_id:
            raise ValueError("relationship endpoints must be distinct")
        return self


class ExtractionWarning(StrictModel):
    code: str
    message: str
    node_id: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"


class ExtractionQualityReport(StrictModel):
    schema_version: Literal["source-quality-v1"] = "source-quality-v1"
    text_coverage: float = Field(ge=0, le=1)
    reading_order: float = Field(ge=0, le=1)
    hierarchy_accuracy: float = Field(ge=0, le=1)
    table_fidelity: float = Field(ge=0, le=1)
    notes_coverage: float = Field(ge=0, le=1)
    visual_coverage: float = Field(ge=0, le=1)
    locator_accuracy: float = Field(ge=0, le=1)
    ocr_coverage: float = Field(ge=0, le=1)
    warnings: list[ExtractionWarning] = Field(default_factory=list)


class OcrPageDecision(StrictModel):
    page: int = Field(ge=1)
    native_character_count: int = Field(ge=0)
    should_ocr: bool
    selection_rule: Literal[
        "healthy_native", "image_only", "sparse_native", "corrupt_native", "repeated_header_only"
    ]
    authoritative_method: ExtractionMethod
    engine: str | None = None
    engine_version: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class VisualAxis(StrictModel):
    label: str | None = None
    unit: str | None = None
    scale: str | None = None


class VisualSeries(StrictModel):
    name: str
    visible_values: list[str] = Field(default_factory=list)


class VisualExplanation(StrictModel):
    schema_version: Literal["source-visual-explanation-v1"] = "source-visual-explanation-v1"
    asset_id: str
    node_id: str
    chart_type: str | None = None
    title: str | None = None
    axes: list[VisualAxis] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)
    legend_or_series: list[VisualSeries] = Field(default_factory=list)
    visible_relationships: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    extracted_visible_text: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    unsupported_observations: list[str] = Field(default_factory=list)
    uncertain_observations: list[str] = Field(default_factory=list)


class ArtifactEntry(StrictModel):
    artifact_id: str
    kind: str
    object_key: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str
    size_bytes: int = Field(ge=0)


class ArtifactManifest(StrictModel):
    schema_version: Literal["source-artifacts-v1"] = "source-artifacts-v1"
    source_version_id: str
    extraction_run_id: str
    artifacts: list[ArtifactEntry]


class SourceDocument(StrictModel):
    schema_version: Literal["source-document-v1"] = "source-document-v1"
    source_id: str
    title: str
    current_version_id: str | None = None


class SourceVersion(StrictModel):
    schema_version: Literal["source-version-v1"] = "source-version-v1"
    source_version_id: str
    source_id: str
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str
    format: SourceFormat
    original_object_key: str
    created_at: datetime


class ExtractionRun(StrictModel):
    schema_version: Literal["source-extraction-run-v1"] = "source-extraction-run-v1"
    extraction_run_id: str
    source_version_id: str
    extractor: str
    extractor_version: str
    attempt: int = Field(ge=1)
    status: Literal["queued", "running", "succeeded", "failed"]
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExtractedDocument(StrictModel):
    schema_version: Literal["extracted-document-v1"] = "extracted-document-v1"
    source_version_id: str
    extraction_run_id: str
    format: SourceFormat
    page_count: int | None = Field(default=None, ge=1)
    slide_count: int | None = Field(default=None, ge=1)
    chapter_count: int | None = Field(default=None, ge=1)
    nodes: list[DocumentNode] = Field(min_length=1)
    relationships: list[NodeRelationship] = Field(default_factory=list)
    ocr_decisions: list[OcrPageDecision] = Field(default_factory=list)
    artifact_manifest: ArtifactManifest | None = None

    @model_validator(mode="after")
    def format_extent(self) -> "ExtractedDocument":
        if self.format == SourceFormat.PDF:
            if (
                self.page_count is None
                or self.slide_count is not None
                or self.chapter_count is not None
            ):
                raise ValueError("PDF documents require page_count only")
        elif self.format == SourceFormat.PPTX:
            if (
                self.slide_count is None
                or self.page_count is not None
                or self.chapter_count is not None
            ):
                raise ValueError("PPTX documents require slide_count only")
        elif (
            self.chapter_count is None
            or self.page_count is not None
            or self.slide_count is not None
        ):
            raise ValueError("EPUB documents require chapter_count only")
        return self


class SourceSegment(StrictModel):
    schema_version: Literal["source-segment-v1"] = "source-segment-v1"
    segment_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    extraction_run_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    node_ids: list[str] = Field(min_length=1)
    hierarchy_path: list[str] = Field(min_length=1)
    locator_start: SourceLocator
    locator_end: SourceLocator
    token_count: int = Field(ge=1)
    text: str = Field(min_length=1)
    split_from_node: bool = False

    @model_validator(mode="after")
    def valid_lineage(self) -> "SourceSegment":
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError("segment node IDs must be unique")
        start_extent = (
            "page"
            if self.locator_start.page is not None
            else "slide"
            if self.locator_start.slide is not None
            else "chapter"
        )
        end_extent = (
            "page"
            if self.locator_end.page is not None
            else "slide"
            if self.locator_end.slide is not None
            else "chapter"
        )
        if start_extent != end_extent:
            raise ValueError("segment locator range must use one extent type")
        return self


class RetrievalHit(StrictModel):
    schema_version: Literal["source-retrieval-hit-v1"] = "source-retrieval-hit-v1"
    segment_id: str
    source_version_id: str
    collection_id: str | None = None
    source_ordinal: int | None = Field(default=None, ge=0)
    authority_note: str | None = None
    ordinal: int = Field(ge=0)
    node_ids: list[str] = Field(min_length=1)
    hierarchy_path: list[str] = Field(min_length=1)
    locator_start: SourceLocator
    locator_end: SourceLocator
    text: str
    score: float = Field(ge=0)
    match_type: Literal["semantic", "lexical", "hybrid", "node"]


class CoverageStatus(StrEnum):
    REPRESENTED = "represented"
    EXCLUDED = "excluded"
    REDUNDANT = "redundant"
    UNRESOLVED = "unresolved"


class EvidenceCitation(StrictModel):
    source_version_id: str = Field(min_length=1)
    node_ids: list[str] = Field(min_length=1)

    @field_validator("node_ids")
    @classmethod
    def unique_nodes(cls, node_ids: list[str]) -> list[str]:
        return list(dict.fromkeys(node_ids))


class MapClaim(StrictModel):
    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    citations: list[EvidenceCitation] = Field(min_length=1)


class MapRelationship(StrictModel):
    relationship_id: str = Field(min_length=1)
    source_claim_id: str = Field(min_length=1)
    target_claim_id: str = Field(min_length=1)
    relationship: str = Field(min_length=1)

    @model_validator(mode="after")
    def distinct_claims(self) -> "MapRelationship":
        if self.source_claim_id == self.target_claim_id:
            raise ValueError("relationship claims must be distinct")
        return self


class MapUncertainty(StrictModel):
    uncertainty_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    citations: list[EvidenceCitation] = Field(default_factory=list)


class CoverageEntry(StrictModel):
    source_version_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    status: CoverageStatus
    claim_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class CoverageLedger(StrictModel):
    entries: list[CoverageEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_nodes(self) -> "CoverageLedger":
        identities = [(entry.source_version_id, entry.node_id) for entry in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("coverage ledger nodes must be unique")
        return self


class SectionMap(StrictModel):
    schema_version: Literal["source-section-map-v1"] = "source-section-map-v1"
    map_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    hierarchy_path: list[str] = Field(min_length=1)
    segment_ids: list[str] = Field(min_length=1)
    claims: list[MapClaim] = Field(default_factory=list)
    relationships: list[MapRelationship] = Field(default_factory=list)
    uncertainties: list[MapUncertainty] = Field(default_factory=list)
    coverage: CoverageLedger
    map_revision: str = Field(min_length=1)


class DocumentMap(StrictModel):
    schema_version: Literal["source-document-map-v1"] = "source-document-map-v1"
    map_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    section_map_ids: list[str] = Field(min_length=1)
    claims: list[MapClaim] = Field(default_factory=list)
    relationships: list[MapRelationship] = Field(default_factory=list)
    uncertainties: list[MapUncertainty] = Field(default_factory=list)
    coverage: CoverageLedger
    map_revision: str = Field(min_length=1)


class CollectionSource(StrictModel):
    source_version_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    authority_note: str | None = None


class MapConflict(StrictModel):
    conflict_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    citations: list[EvidenceCitation] = Field(min_length=2)


class CollectionMap(StrictModel):
    schema_version: Literal["source-collection-map-v1"] = "source-collection-map-v1"
    map_id: str = Field(min_length=1)
    collection_id: str = Field(min_length=1)
    sources: list[CollectionSource] = Field(min_length=1)
    document_map_ids: list[str] = Field(min_length=1)
    claims: list[MapClaim] = Field(default_factory=list)
    relationships: list[MapRelationship] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    overlaps: list[str] = Field(default_factory=list)
    conflicts: list[MapConflict] = Field(default_factory=list)
    version_differences: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    uncertainties: list[MapUncertainty] = Field(default_factory=list)
    coverage: CoverageLedger
    map_revision: str = Field(min_length=1)
