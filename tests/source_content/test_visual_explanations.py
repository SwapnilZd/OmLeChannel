from types import SimpleNamespace
from unittest.mock import MagicMock

from src.source_ingestion.contracts import RelationshipType, VisualExplanation, VisualSeries
from src.source_ingestion.extractors.docling import extract_document
from src.source_ingestion.visual_explanations import (
    MAX_ADJACENT_CONTEXT_CHARACTERS,
    VisualExplanationService,
    attach_visual_explanation,
)
from src.source_ingestion.worker import _add_visual_explanations


def _fixture():
    from pathlib import Path

    extraction = extract_document(
        Path("tests/source_content/fixtures/generated/structured-presentation.pptx"),
        source_version_id="visual-version",
        extraction_run_id="visual-run",
    )
    visual = next(node for node in extraction.document.nodes if node.asset_id)
    crop = next(
        artifact
        for artifact in extraction.artifacts
        if artifact.kind == "picture_crop" and visual.node_id in artifact.artifact_id
    )
    return extraction, visual, crop


def test_visual_request_is_crop_only_with_bounded_same_slide_context():
    extraction, visual, crop = _fixture()
    explanation = VisualExplanation(
        asset_id=visual.asset_id,
        node_id=visual.node_id,
        chart_type="column chart",
        title="Quarterly review completion",
        axes=[],
        measures=["Completion is 40 in Q1"],
        legend_or_series=[VisualSeries(name="Completed", visible_values=["40", "65", "85"])],
        visible_relationships=["Completion rises from 40 to 85"],
        extracted_visible_text=["40", "65", "85"],
        confidence=0.95,
    )
    client = MagicMock()
    client.responses.parse.return_value = SimpleNamespace(output_parsed=explanation)

    result = VisualExplanationService(client=client).explain(
        document=extraction.document,
        visual_node=visual,
        crop=crop,
        visible_text="Quarterly review completion Q1 40 Q2 65 Q3 85",
    )

    request = client.responses.parse.call_args.kwargs
    user_text = request["input"][1]["content"][0]["text"]
    assert len(user_text) < MAX_ADJACENT_CONTEXT_CHARACTERS + 1_000
    assert "Process and evidence" not in user_text
    assert request["input"][1]["content"][1]["image_url"].startswith("data:image/webp;base64,")
    assert result.measures == ["Completion is 40 in Q1"]


def test_unsupported_numbers_become_uncertain_and_explanation_retains_lineage():
    extraction, visual, crop = _fixture()
    explanation = VisualExplanation(
        asset_id=visual.asset_id,
        node_id=visual.node_id,
        measures=["Completion reaches 99"],
        visible_relationships=["Values double from 40 to 99"],
        confidence=0.96,
    )
    client = MagicMock()
    client.responses.parse.return_value = SimpleNamespace(output_parsed=explanation)

    grounded = VisualExplanationService(client=client).explain(
        document=extraction.document,
        visual_node=visual,
        crop=crop,
        visible_text="40 65 85",
    )
    attached = attach_visual_explanation(extraction.document, grounded)

    assert grounded.measures == []
    assert len(grounded.uncertain_observations) == 2
    assert grounded.confidence == 0.75
    derived = next(node for node in attached.nodes if node.kind == "visual_explanation")
    assert derived.method.value == "derived"
    assert any(
        relationship.type == RelationshipType.VISUAL_EXPLANATION_OF
        and relationship.source_node_id == derived.node_id
        and relationship.target_node_id == visual.node_id
        for relationship in attached.relationships
    )


def test_worker_adds_explanation_artifact_and_derived_node():
    extraction, visual, _crop = _fixture()
    explanation = VisualExplanation(
        asset_id=visual.asset_id,
        node_id=visual.node_id,
        visible_relationships=["Completion increases across the displayed quarters."],
        confidence=0.9,
    )
    service = MagicMock()
    service.explain.return_value = explanation

    result = _add_visual_explanations(extraction, service=service)

    assert any(node.kind == "visual_explanation" for node in result.document.nodes)
    assert any(artifact.kind == "visual_explanation" for artifact in result.artifacts)
