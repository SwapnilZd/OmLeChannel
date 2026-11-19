from pathlib import Path


_ROOT = Path(__file__).parents[2]
_TEMPLATE = _ROOT / "pipeline/components/templates/knowledge_check.html.j2"
_SCRIPT = _ROOT / "pipeline/components/base.js"
_STYLES = _ROOT / "pipeline/components/base.css"
_REGISTRY = _ROOT / "pipeline/components/registry/knowledge_check.yaml"


def test_option_labels_never_render_diagnostic_feedback_as_visible_copy() -> None:
    template = _TEMPLATE.read_text(encoding="utf-8")

    assert '<span class="option-text">{{ o.text }}</span>' in template
    assert 'data-feedback="{{ o.feedback }}"' in template
    assert '<span class="option-feedback" hidden>' not in template


def test_selected_option_feedback_is_revealed_in_the_result_panel() -> None:
    template = _TEMPLATE.read_text(encoding="utf-8")
    script = _SCRIPT.read_text(encoding="utf-8")
    styles = _STYLES.read_text(encoding="utf-8")

    assert '<div class="kc-feedback-detail"></div>' in template
    assert "i.dataset.feedback" in script
    assert "form.querySelector('.kc-feedback-detail')" in script
    assert ".kc-feedback.is-correct" in styles
    assert ".kc-feedback.is-incorrect" in styles


def test_component_contract_states_feedback_timing_and_placement() -> None:
    registry = _REGISTRY.read_text(encoding="utf-8")

    assert "shown only after submission" in registry
    assert "result panel" in registry
