import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from component_registry import _load_all, _load_catalog  # noqa: E402
from design_gallery import design_gallery_course  # noqa: E402
from renderer import render_course_html  # noqa: E402


def test_every_ready_catalog_mapping_targets_a_real_variant():
    registry = _load_all()
    mapped = 0
    for concept in _load_catalog().values():
        implementation = concept.get("implementation", {})
        if implementation.get("status") != "ready":
            continue
        mapped += 1
        family = registry[implementation["family"]]
        assert implementation["variant"] in family.get("layout_variants", {"default": {}})
    assert mapped >= 18


def test_design_gallery_has_sample_data_for_every_new_variant():
    course = design_gallery_course()
    actual = {(screen.type, screen.layout_variant) for screen in course.screens}
    expected = {
        ("paired_comparison", variant)
        for variant in ("before_after", "pros_cons", "do_dont", "current_future")
    } | {
        ("disclosure_list", variant)
        for variant in ("accordion", "faq", "click_reveal")
    } | {
        ("relationship_diagram", variant)
        for variant in ("cycle", "hierarchy", "continuum", "matrix_2x2", "linear_flow")
    }
    assert actual == expected


def test_design_gallery_renders_without_a_model_call():
    course = design_gallery_course()
    html = render_course_html(course)
    assert len(course.screens) == 12
    assert "slide-paired-comparison" in html
    assert "slide-disclosure" in html
    assert "relationship-matrix" in html
