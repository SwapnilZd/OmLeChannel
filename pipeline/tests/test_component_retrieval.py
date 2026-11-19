import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from component_registry import (  # noqa: E402
    ComponentRegistry,
    _load_all,
    _load_catalog,
    _variant_records,
)
from schema import SlideNeed  # noqa: E402


def _local_registry() -> ComponentRegistry:
    registry = object.__new__(ComponentRegistry)
    registry._descriptors = _load_all()
    registry._catalog = _load_catalog()
    registry._records = _variant_records({**registry._descriptors, **registry._catalog})
    registry._available = False
    return registry


def test_three_text_heavy_concepts_returns_bounded_content_candidates():
    registry = _local_registry()
    need = SlideNeed(
        category="content",
        purpose="introduce_concepts",
        content_shape="peer_items",
        relationship="parallel",
        item_count=3,
        density="text_heavy",
        interaction_preferences=["reveal", "tabs"],
    )
    candidates = registry.search_candidates(need, limit=8)
    assert 5 <= len(candidates) <= 8
    assert any(candidate.template_id == "concept_flip_card" for candidate in candidates)
    assert all(candidate.descriptor["selection"]["category"] == "content" for candidate in candidates)
    assert all(candidate.template_id != "video_player" for candidate in candidates)


def test_required_video_returns_only_grounded_media_template():
    registry = _local_registry()
    need = SlideNeed(
        category="media",
        purpose="play_video",
        content_shape="single_video_asset",
        relationship="single_focus",
        item_count=1,
        density="sparse",
        interaction_preferences=["video_controls"],
        media_requirement="required",
    )
    candidates = registry.search_candidates(need, limit=8)
    assert [(candidate.template_id, candidate.variant_id) for candidate in candidates] == [
        ("video_player", "default")
    ]


def test_assessment_query_cannot_return_content_template():
    registry = _local_registry()
    need = SlideNeed(
        category="assessment",
        purpose="assess_understanding",
        content_shape="multiple_choice_question",
        relationship="question_and_options",
        item_count=4,
        density="text_heavy",
        interaction_preferences=["single_select", "submit_feedback"],
    )
    candidates = registry.search_candidates(need, limit=8)
    assert [candidate.template_id for candidate in candidates] == ["knowledge_check"]


def test_descriptor_change_changes_variant_hash():
    descriptors = _load_all()
    before = _variant_records(descriptors)["rule_card:text_focus"].payload["descriptor_hash"]
    descriptors["rule_card"]["selection"]["retrieval_text"] += " Updated."
    after = _variant_records(descriptors)["rule_card:text_focus"].payload["descriptor_hash"]
    assert before != after


def test_catalog_covers_major_corporate_learning_categories():
    catalog = _load_catalog()
    categories = {concept["selection"]["category"] for concept in catalog.values()}
    assert {"intro", "content", "practice", "assessment", "media", "navigation", "completion"} <= categories
    assert {"matrix_2x2", "software_simulation", "open_response_assessment", "audio_player"} <= set(catalog)
    assert all(concept["implementation_status"] == "planned" for concept in catalog.values())


def test_production_retrieval_never_returns_planned_catalog_concepts():
    registry = _local_registry()
    need = SlideNeed(
        category="media",
        purpose="play_audio",
        content_shape="single_audio_asset",
        item_count=1,
        density="sparse",
        interaction_preferences=["audio_controls"],
        media_requirement="required",
    )
    assert all(
        candidate.descriptor.get("implementation_status", "ready") == "ready"
        for candidate in registry.search_candidates(need, limit=8)
    )


def test_catalog_search_can_discover_planned_assessment_designs():
    registry = _local_registry()
    need = SlideNeed(
        category="assessment",
        purpose="assess_constructed_response",
        content_shape="open_response_prompt",
        item_count=1,
        density="balanced",
        interaction_preferences=["text_input", "submit_feedback"],
    )
    candidates = registry.search_catalog(need, limit=8)
    assert any(candidate.template_id == "open_response_assessment" for candidate in candidates)
    assert 1 <= len(candidates) <= 8


def test_structural_metadata_promotes_implemented_design_variant():
    registry = _local_registry()
    need = SlideNeed(
        category="content",
        purpose="classify_items",
        content_shape="two_axis_matrix",
        relationship="two_dimensional",
        item_count=4,
        density="balanced",
    )
    candidates = registry.search_candidates(need, limit=8)
    assert (candidates[0].template_id, candidates[0].variant_id) == (
        "relationship_diagram",
        "matrix_2x2",
    )
