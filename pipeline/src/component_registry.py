"""Searchable registry of slide template families and layout variants."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from llm_gateway import ModelAlias, build_langfuse_headers, build_litellm_metadata
from model_gateway import make_openai_client
from schema import SlideNeed, TemplateCandidate

_REGISTRY_DIR = Path(__file__).parent.parent / "components" / "registry"
_CATALOG_DIR = Path(__file__).parent.parent / "components" / "catalog"
_COLLECTION = "slide_templates_v3"
_INDEX_VERSION = 3
_EMBED_MODEL = ModelAlias.COMPONENT_CATALOG_EMBEDDING
_EMBED_DIM = int(os.environ.get("COMPONENT_EMBED_DIM", "1536"))
_DEFAULT_LIMIT = 8
_MAX_VARIANTS_PER_FAMILY = 2


def _stable_uuid(record_id: str) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(record_id.encode()).digest()))


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _load_all() -> dict[str, dict]:
    descriptors: dict[str, dict] = {}
    for path in sorted(_REGISTRY_DIR.glob("*.yaml")):
        descriptor = yaml.safe_load(path.read_text(encoding="utf-8"))
        descriptors[descriptor["id"]] = descriptor
    return descriptors


def _load_catalog() -> dict[str, dict]:
    concepts: dict[str, dict] = {}
    for path in sorted(_CATALOG_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for concept in document.get("concepts", []):
            if concept["id"] in concepts:
                raise ValueError(f"Duplicate catalog concept ID {concept['id']!r}.")
            concepts[concept["id"]] = concept
    return concepts


def _infer_item_capacity(descriptor: dict) -> tuple[int | None, int | None]:
    explicit = descriptor.get("selection", {}).get("capacity", {})
    if "min_items" in explicit or "max_items" in explicit:
        return explicit.get("min_items"), explicit.get("max_items")
    arrays = [
        slot
        for slot in descriptor.get("slots", {}).values()
        if isinstance(slot, dict) and slot.get("type") == "array"
    ]
    if not arrays:
        return None, None
    return arrays[0].get("min_items"), arrays[0].get("max_items")


@dataclass(frozen=True)
class _VariantRecord:
    record_id: str
    template_id: str
    variant_id: str
    retrieval_text: str
    payload: dict[str, Any]
    descriptor: dict[str, Any]


def _variant_records(descriptors: dict[str, dict]) -> dict[str, _VariantRecord]:
    records: dict[str, _VariantRecord] = {}
    for template_id, descriptor in descriptors.items():
        selection = descriptor.get("selection", {})
        variants = descriptor.get("layout_variants") or {"default": {}}
        min_items, max_items = _infer_item_capacity(descriptor)
        base_text = selection.get("retrieval_text") or (
            f"{descriptor.get('description', '')}\n"
            f"Best use: {descriptor.get('when_to_use', '')}"
        )
        for variant_id, variant in variants.items():
            variant = variant if isinstance(variant, dict) else {"description": str(variant)}
            variant_selection = {**selection, **variant.get("selection", {})}
            variant_text = " ".join(
                str(value)
                for value in (variant.get("when"), variant.get("behavior"), variant.get("description"))
                if value
            )
            retrieval_text = (
                f"{base_text}\nVariant {variant_id}: {variant_text}" if variant_id != "default" else base_text
            ).strip()
            record_id = f"{template_id}:{variant_id}"
            variant_capacity = variant.get("capacity", {})
            payload = {
                "record_id": record_id,
                "template_id": template_id,
                "variant_id": variant_id,
                "index_version": _INDEX_VERSION,
                "implementation_status": descriptor.get("implementation_status", "ready"),
                "suggested_family": descriptor.get("suggested_family", template_id),
                "category": variant_selection.get("category", "content"),
                "purposes": variant_selection.get("purposes", []),
                "content_shapes": variant_selection.get("content_shapes", []),
                "relationships": variant_selection.get("relationships", []),
                "interactions": variant_selection.get("interactions", []),
                "densities": variant.get("densities", variant_selection.get("densities", ["balanced"])),
                "sequence_positions": variant_selection.get(
                    "sequence_positions", [descriptor.get("sequence_position", "any")]
                ),
                "media_supported": bool(variant_selection.get("media_supported", False)),
                "media_required": bool(variant_selection.get("media_required", False)),
                "min_items": variant_capacity.get("min_items", min_items),
                "max_items": variant_capacity.get("max_items", max_items),
                "retrieval_summary": retrieval_text,
            }
            payload["descriptor_hash"] = _content_hash(
                {
                    "index_version": _INDEX_VERSION,
                    "embedding_model": _EMBED_MODEL,
                    "payload": payload,
                    "descriptor": descriptor,
                }
            )
            records[record_id] = _VariantRecord(
                record_id=record_id,
                template_id=template_id,
                variant_id=variant_id,
                retrieval_text=retrieval_text,
                payload=payload,
                descriptor=descriptor,
            )
    return records


class ComponentRegistry:
    """Retrieve a small, eligible, diverse shortlist of template variants."""

    def __init__(self, qdrant_url: str, litellm_base_url: str, litellm_api_key: str) -> None:
        self._descriptors = _load_all()
        self._catalog = _load_catalog()
        self._records = _variant_records({**self._descriptors, **self._catalog})
        self._base_url = litellm_base_url
        self._api_key = litellm_api_key
        self._client: Any = None
        self._available = False
        self._connect(qdrant_url)

    def _connect(self, qdrant_url: str) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            client = QdrantClient(url=qdrant_url, timeout=10)
            existing = {collection.name for collection in client.get_collections().collections}
            if _COLLECTION not in existing:
                client.create_collection(
                    _COLLECTION,
                    vectors_config=VectorParams(size=_EMBED_DIM, distance=Distance.COSINE),
                )
            self._client = client
            self._ensure_payload_indexes()
            self._sync()
            self._available = True
        except Exception as exc:
            print(f"[registry] Qdrant unavailable ({exc}); using deterministic local fallback")

    def _ensure_payload_indexes(self) -> None:
        from qdrant_client.models import PayloadSchemaType

        schema = self._client.get_collection(_COLLECTION).payload_schema
        fields = {
            "implementation_status": PayloadSchemaType.KEYWORD,
            "category": PayloadSchemaType.KEYWORD,
            "densities": PayloadSchemaType.KEYWORD,
            "interactions": PayloadSchemaType.KEYWORD,
            "sequence_positions": PayloadSchemaType.KEYWORD,
            "media_supported": PayloadSchemaType.BOOL,
            "min_items": PayloadSchemaType.INTEGER,
            "max_items": PayloadSchemaType.INTEGER,
        }
        for field, field_type in fields.items():
            if field not in schema:
                self._client.create_payload_index(
                    collection_name=_COLLECTION,
                    field_name=field,
                    field_schema=field_type,
                    wait=True,
                )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        client = make_openai_client(base_url=self._base_url, api_key=self._api_key)
        response = client.embeddings.create(
            model=_EMBED_MODEL,
            input=texts,
            extra_body={
                "metadata": build_litellm_metadata(_EMBED_MODEL, operation="index")
            },
            extra_headers=build_langfuse_headers(_EMBED_MODEL, operation="index"),
        )
        return [item.embedding for item in response.data]

    def _sync(self) -> None:
        from qdrant_client.models import PointStruct

        existing_points, _ = self._client.scroll(
            _COLLECTION,
            limit=10_000,
            with_payload=["record_id", "descriptor_hash"],
            with_vectors=False,
        )
        existing = {
            point.payload.get("record_id"): point.payload.get("descriptor_hash")
            for point in existing_points
        }
        changed = [
            record
            for record in self._records.values()
            if existing.get(record.record_id) != record.payload["descriptor_hash"]
        ]
        removed = sorted(set(existing) - set(self._records))

        if changed:
            vectors = self._embed([record.retrieval_text for record in changed])
            self._client.upsert(
                collection_name=_COLLECTION,
                points=[
                    PointStruct(
                        id=_stable_uuid(record.record_id),
                        vector=vector,
                        payload=record.payload,
                    )
                    for record, vector in zip(changed, vectors)
                ],
                wait=True,
            )
        if removed:
            self._client.delete(
                collection_name=_COLLECTION,
                points_selector=[_stable_uuid(record_id) for record_id in removed],
                wait=True,
            )
        print(
            f"[registry] {_COLLECTION}: {len(self._records)} variants "
            f"({len(changed)} refreshed, {len(removed)} removed)"
        )

    @staticmethod
    def _eligible(record: _VariantRecord, need: SlideNeed, *, ready_only: bool = True) -> bool:
        payload = record.payload
        if ready_only and payload["implementation_status"] != "ready":
            return False
        if payload["category"] != need.category:
            return False
        if need.item_count is not None:
            if payload["min_items"] is not None and payload["min_items"] > need.item_count:
                return False
            if payload["max_items"] is not None and payload["max_items"] < need.item_count:
                return False
        if need.media_requirement == "required" and not payload["media_supported"]:
            return False
        return True

    @staticmethod
    def _metadata_boost(record: _VariantRecord, need: SlideNeed) -> float:
        payload = record.payload
        purpose = need.purpose.lower().replace(" ", "_").replace("-", "_")
        boost = 0.0
        boost += 0.4 if need.content_shape in payload["content_shapes"] else 0.0
        boost += 0.25 if need.relationship in payload["relationships"] else 0.0
        boost += 0.2 if purpose in payload["purposes"] else 0.0
        boost += 0.1 if need.density in payload["densities"] else 0.0
        boost += 0.1 * len(set(need.interaction_preferences) & set(payload["interactions"]))
        return boost

    @classmethod
    def _local_score(cls, record: _VariantRecord, need: SlideNeed) -> float:
        score = 1.0 + cls._metadata_boost(record, need)
        need_words = set(need.retrieval_text().lower().split())
        record_words = set(record.retrieval_text.lower().split())
        score += len(need_words & record_words) / max(len(need_words), 1)
        return score

    def _query_filter(self, need: SlideNeed, *, ready_only: bool = True) -> Any:
        from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

        must: list[Any] = [FieldCondition(key="category", match=MatchValue(value=need.category))]
        if ready_only:
            must.append(
                FieldCondition(key="implementation_status", match=MatchValue(value="ready"))
            )
        if need.item_count is not None:
            must.extend(
                [
                    FieldCondition(key="min_items", range=Range(lte=need.item_count)),
                    FieldCondition(key="max_items", range=Range(gte=need.item_count)),
                ]
            )
        if need.media_requirement == "required":
            must.append(FieldCondition(key="media_supported", match=MatchValue(value=True)))
        return Filter(must=must)

    def _hydrate(
        self,
        ranked: Iterable[tuple[_VariantRecord, float | None]],
        *,
        limit: int,
    ) -> list[TemplateCandidate]:
        candidates: list[TemplateCandidate] = []
        family_counts: dict[str, int] = {}
        for record, score in ranked:
            family = record.payload.get("suggested_family", record.template_id)
            if family_counts.get(family, 0) >= _MAX_VARIANTS_PER_FAMILY:
                continue
            descriptor = copy.deepcopy(record.descriptor)
            descriptor["selected_variant"] = record.variant_id
            candidates.append(
                TemplateCandidate(
                    template_id=record.template_id,
                    variant_id=record.variant_id,
                    score=score,
                    retrieval_summary=record.payload["retrieval_summary"],
                    descriptor=descriptor,
                )
            )
            family_counts[family] = family_counts.get(family, 0) + 1
            if len(candidates) >= limit:
                break
        return candidates

    def _local_candidates(
        self, need: SlideNeed, limit: int, *, ready_only: bool = True
    ) -> list[TemplateCandidate]:
        ranked = sorted(
            (
                (record, self._local_score(record, need))
                for record in self._records.values()
                if self._eligible(record, need, ready_only=ready_only)
            ),
            key=lambda item: (-item[1], item[0].record_id),
        )
        return self._hydrate(ranked, limit=limit)

    def search_candidates(self, need: SlideNeed, limit: int = _DEFAULT_LIMIT) -> list[TemplateCandidate]:
        return self.search_candidates_batch([need], limit=limit)[0]

    def search_candidates_batch(
        self,
        needs: list[SlideNeed],
        limit: int = _DEFAULT_LIMIT,
    ) -> list[list[TemplateCandidate]]:
        return self._search_needs_batch(needs, limit=limit, ready_only=True)

    def search_catalog(self, need: SlideNeed, limit: int = _DEFAULT_LIMIT) -> list[TemplateCandidate]:
        """Search ready and planned designs for design discovery and roadmap work."""
        return self._search_needs_batch([need], limit=limit, ready_only=False)[0]

    def _search_needs_batch(
        self,
        needs: list[SlideNeed],
        *,
        limit: int,
        ready_only: bool,
    ) -> list[list[TemplateCandidate]]:
        if not 5 <= limit <= 10:
            raise ValueError("Candidate shortlist limit must be between 5 and 10.")
        if not self._available:
            return [
                self._local_candidates(need, limit, ready_only=ready_only) for need in needs
            ]

        vectors = self._embed([need.retrieval_text() for need in needs])
        output: list[list[TemplateCandidate]] = []
        raw_limit = max(20, limit * 3)
        for need, vector in zip(needs, vectors):
            points = self._client.query_points(
                collection_name=_COLLECTION,
                query=vector,
                query_filter=self._query_filter(need, ready_only=ready_only),
                limit=raw_limit,
                with_payload=True,
            ).points
            ranked = [
                (
                    self._records[point.payload["record_id"]],
                    float(point.score)
                    + self._metadata_boost(self._records[point.payload["record_id"]], need),
                )
                for point in points
                if point.payload.get("record_id") in self._records
            ]
            ranked.sort(key=lambda item: (-item[1], item[0].record_id))
            candidates = self._hydrate(ranked, limit=limit)
            if len(candidates) < min(5, limit):
                seen = {(candidate.template_id, candidate.variant_id) for candidate in candidates}
                fallback = [
                    candidate
                    for candidate in self._local_candidates(
                        need, limit, ready_only=ready_only
                    )
                    if (candidate.template_id, candidate.variant_id) not in seen
                ]
                candidates.extend(fallback[: limit - len(candidates)])
            output.append(candidates)
        return output

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Legacy unfiltered semantic lookup, retained for diagnostics."""
        if not self._available:
            return self.all()[:top_k]
        vector = self._embed([query])[0]
        points = self._client.query_points(
            collection_name=_COLLECTION,
            query=vector,
            limit=top_k,
            with_payload=True,
        ).points
        return [
            copy.deepcopy(self._records[point.payload["record_id"]].descriptor)
            for point in points
            if point.payload.get("record_id") in self._records
        ]

    def get(self, component_id: str) -> dict | None:
        return self._descriptors.get(component_id)

    def all(self) -> list[dict]:
        return [self._descriptors[key] for key in sorted(self._descriptors)]

    def all_summary_text(self) -> str:
        return "\n".join(
            f"  {descriptor['id']}: {descriptor.get('when_to_use', '').replace(chr(10), ' ')[:140]}"
            for descriptor in self.all()
        )

    def slot_constraint_text(self, component_id: str) -> str:
        descriptor = self._descriptors.get(component_id, {})
        slots = descriptor.get("slots", {})
        if not slots:
            return ""
        lines = [f"Slot constraints for '{component_id}':"]

        def add(current: dict, prefix: str = "") -> None:
            for name, spec in current.items():
                if not isinstance(spec, dict):
                    continue
                path = f"{prefix}.{name}" if prefix else name
                bounds = [
                    f"{key}={spec[key]}"
                    for key in ("min_chars", "target_chars", "max_chars", "min_items", "max_items")
                    if key in spec
                ]
                if bounds:
                    lines.append(f"  {path}: {', '.join(bounds)}")
                if isinstance(spec.get("slots"), dict):
                    add(spec["slots"], path)
                if isinstance(spec.get("item_slots"), dict):
                    add(spec["item_slots"], f"{path}[]")

        add(slots)
        return "\n".join(lines)
