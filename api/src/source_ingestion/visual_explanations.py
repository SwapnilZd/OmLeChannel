"""Bounded, grounded visual explanations through the shared LiteLLM gateway."""

from __future__ import annotations

import base64
import json
import re

from llm_gateway import ModelAlias, build_langfuse_headers, build_litellm_metadata, load_lite_llm_settings
from openai import OpenAI

from .contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    NodeRelationship,
    RelationshipType,
    VisualExplanation,
)
from .hierarchy import stable_node_id, validate_document
from .rendering import RenderedArtifact


MODEL = ModelAlias.SOURCE_VISUAL_EXPLANATION
MAX_ADJACENT_CONTEXT_CHARACTERS = 2_000
SYSTEM_PROMPT = """Describe only what is visibly supported by this chart or diagram and its adjacent source context. Return the strict schema. Put anything unreadable or unsupported in uncertain_observations or unsupported_observations; never infer missing values."""


def adjacent_context(document: ExtractedDocument, visual_node: DocumentNode) -> str:
    extent = visual_node.locators[0].page or visual_node.locators[0].slide
    values = []
    for node in document.nodes:
        if node.node_id == visual_node.node_id or not node.text:
            continue
        if any((locator.page or locator.slide) == extent for locator in node.locators):
            values.append(node.text)
    return "\n".join(values)[:MAX_ADJACENT_CONTEXT_CHARACTERS]


def _numeric_tokens(values: list[str]) -> set[str]:
    return {token for value in values for token in re.findall(r"(?<!\w)-?\d+(?:\.\d+)?%?", value)}


def ground_numeric_claims(explanation: VisualExplanation, visible_text: str) -> VisualExplanation:
    supported = _numeric_tokens([visible_text])
    uncertain = list(explanation.uncertain_observations)

    def retain(values: list[str]) -> list[str]:
        grounded = []
        for value in values:
            unsupported = _numeric_tokens([value]) - supported
            if unsupported:
                uncertain.append(f"Unverified numeric observation removed: {value}")
            else:
                grounded.append(value)
        return grounded

    return explanation.model_copy(
        update={
            "measures": retain(explanation.measures),
            "visible_relationships": retain(explanation.visible_relationships),
            "uncertain_observations": uncertain,
            "confidence": min(explanation.confidence, 0.75) if uncertain else explanation.confidence,
        }
    )


class VisualExplanationService:
    def __init__(self, client=None) -> None:
        settings = load_lite_llm_settings(required=False)
        self.client = client or OpenAI(base_url=settings.base_url, api_key=settings.api_key)

    def explain(
        self,
        *,
        document: ExtractedDocument,
        visual_node: DocumentNode,
        crop: RenderedArtifact,
        visible_text: str,
    ) -> VisualExplanation:
        context = adjacent_context(document, visual_node)
        data_url = f"data:{crop.content_type};base64,{base64.b64encode(crop.body).decode()}"
        response = self.client.responses.parse(
            model=MODEL,
            metadata=build_litellm_metadata(MODEL, operation="explain", job_id=document.extraction_run_id),
            extra_headers=build_langfuse_headers(MODEL, operation="explain", job_id=document.extraction_run_id),
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": json.dumps({"asset_id": visual_node.asset_id, "node_id": visual_node.node_id, "adjacent_context": context, "locators": [locator.model_dump() for locator in visual_node.locators], "locally_extracted_visible_text": visible_text})},
                        {"type": "input_image", "image_url": data_url},
                    ],
                },
            ],
            text_format=VisualExplanation,
        )
        explanation = response.output_parsed
        if explanation is None:
            raise ValueError("model returned no visual explanation")
        if explanation.node_id != visual_node.node_id or explanation.asset_id != visual_node.asset_id:
            raise ValueError("visual explanation lineage does not match its requested asset")
        return ground_numeric_claims(explanation, visible_text)


def attach_visual_explanation(document: ExtractedDocument, explanation: VisualExplanation) -> ExtractedDocument:
    visual = next((node for node in document.nodes if node.node_id == explanation.node_id), None)
    if visual is None:
        raise ValueError("visual explanation references an unknown node")
    root = document.nodes[0]
    ordinal = len(root.child_ids)
    node_id = stable_node_id(document.source_version_id, kind="visual_explanation", ordinal_path=(0, ordinal))
    node = DocumentNode(
        node_id=node_id,
        parent_id=root.node_id,
        ordinal=ordinal,
        ordinal_path=(0, ordinal),
        kind="visual_explanation",
        role="visual_explanation",
        text=explanation.model_dump_json(),
        locators=visual.locators,
        method=ExtractionMethod.DERIVED,
    )
    relationship = NodeRelationship(
        relationship_id=f"visual-explanation-{visual.node_id}",
        type=RelationshipType.VISUAL_EXPLANATION_OF,
        source_node_id=node_id,
        target_node_id=visual.node_id,
    )
    nodes = [root.model_copy(update={"child_ids": [*root.child_ids, node_id]}), *document.nodes[1:], node]
    return validate_document(document.model_copy(update={"nodes": nodes, "relationships": [*document.relationships, relationship]}))
