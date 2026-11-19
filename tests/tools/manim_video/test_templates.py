"""Template timing, narration-budget, and layout-safety guarantees.

Every template must:
  1. Render syntactically valid Python from minimal valid bindings.
  2. Emit the bounded-timing helper (_rt) and use it — no animation may stretch
     to the full narration duration (the "45-second crawling title" defect).
  3. Reject narration fields that grossly exceed their beat's word budget, so
     the controller's bounded repair loop can fix the draft.
  4. Emit the width-clamp helper (_fit) and use it — visible text must never
     escape its card, box, hub, or the frame (measured geometry is verified
     separately by `make manim-layout-audit`).
  5. Never silently truncate visible text: mild cap overage passes through
     (the _fit clamp absorbs it); gross overage (>1.5x cap) raises for the
     repair loop — the same policy narration budgets follow.
"""
from __future__ import annotations

import ast

import pytest

from learning_pipeline.tools.manim_video._manim_bridge import REGISTRY

_SAMPLES: dict[str, dict] = {
    "vertical_stack": {
        "scene_narration": "Opening words here.",
        "title": "T",
        "items": [
            {"label": "A", "detail": "d", "narration": "n one"},
            {"label": "B", "detail": "d", "narration": "n two"},
            {"label": "C", "detail": "d", "narration": "n three"},
        ],
        "closing_narration": "Done.",
    },
    "central_callouts": {
        "scene_narration": "Open.",
        "center_label": "Core",
        "center_narration": "Hub.",
        "callouts": [
            {"label": "A", "narration": "n"},
            {"label": "B", "narration": "n"},
            {"label": "C", "narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "two_column": {
        "scene_narration": "Open.",
        "left_header": "L",
        "right_header": "R",
        "pairs": [
            {"left": "a", "right": "b", "narration": "n"},
            {"left": "c", "right": "d", "narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "chess_board": {
        "scene_narration": "Board appears.",
        "title": "T",
        "initial_pieces": [{"symbol": "♙", "file": "e", "rank": 2, "color": "white"}],
        "steps": [
            {"narration": "Move.", "actions": [
                {"type": "move", "file": "e", "rank": 2, "to_file": "e", "to_rank": 4}
            ]},
            {"narration": "Dots.", "actions": [{"type": "dot", "file": "d", "rank": 4}]},
        ],
        "closing_narration": "Close.",
    },
    "myth_vs_reality": {
        "scene_narration": "Open.",
        "title": "T",
        "pairs": [
            {"misconception": "m", "myth_narration": "n",
             "correction": "c", "correction_narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "scenario": {
        "scene_narration": "Open.",
        "setup": "s", "setup_narration": "n",
        "question": "q", "question_narration": "n",
        "wrong_answer": "✗ w", "wrong_narration": "n",
        "correct_answer": "✓ c", "correct_narration": "n",
        "closing_narration": "Close.",
    },
    "definition": {
        "scene_narration": "Open.",
        "term": "T", "definition": "D", "definition_narration": "n",
        "attributes": [
            {"key": "k", "value": "v", "narration": "n"},
            {"key": "k2", "value": "v2", "narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "pyramid": {
        "scene_narration": "Open.",
        "title": "T",
        "levels": [
            {"label": "a", "narration": "n"},
            {"label": "b", "narration": "n"},
            {"label": "c", "narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "timeline": {
        "scene_narration": "Open.",
        "title": "T",
        "events": [
            {"date": "d", "label": "a", "narration": "n"},
            {"date": "d", "label": "b", "narration": "n"},
            {"date": "d", "label": "c", "narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "process_flow": {
        "scene_narration": "Open.",
        "title": "T",
        "steps": [
            {"label": "a", "detail": "d", "narration": "n"},
            {"label": "b", "detail": "d", "narration": "n"},
            {"label": "c", "detail": "d", "narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "cycle": {
        "scene_narration": "Open.",
        "title": "T",
        "steps": [
            {"label": "a", "narration": "n"},
            {"label": "b", "narration": "n"},
            {"label": "c", "narration": "n"},
        ],
        "closing_narration": "Close.",
    },
    "quadrant": {
        "scene_narration": "Open.",
        "x_low": "xl", "x_high": "xh", "y_low": "yl", "y_high": "yh",
        "tl_label": "TL", "tl_items": ["i1"], "tl_narration": "n",
        "tr_label": "TR", "tr_items": ["i2"], "tr_narration": "n",
        "bl_label": "BL", "bl_items": ["i3"], "bl_narration": "n",
        "br_label": "BR", "br_items": [], "br_narration": "n",
        "closing_narration": "Close.",
    },
}


def test_every_registered_template_has_a_sample() -> None:
    assert set(_SAMPLES) == set(REGISTRY)


@pytest.mark.parametrize("name", sorted(_SAMPLES))
def test_every_template_is_expressible_in_component_bindings(name: str) -> None:
    """The LLM's structured-output schema (extra=forbid) must be able to carry
    every registered template's bindings — a template the schema cannot
    express is a template the agent can never draft, silently pushing it
    to free-form source."""
    from learning_pipeline.tools.manim_video._contracts import ManimComponentBindings

    bindings = ManimComponentBindings.model_validate(_SAMPLES[name])
    round_tripped = bindings.model_dump(exclude_none=True)
    validated = REGISTRY[name].validate(round_tripped)
    source = REGISTRY[name].render(validated, "test_scene", "", '""')
    ast.parse(source)


@pytest.mark.parametrize("name", sorted(_SAMPLES))
def test_template_renders_bounded_timing_python(name: str) -> None:
    template = REGISTRY[name]
    data = template.validate(dict(_SAMPLES[name]))
    source = template.render(data, "test_scene", "", '""')

    ast.parse(source)  # must be valid Python
    assert "def _rt(" in source, "bounded-timing helper missing from generated source"
    assert "_rt(" in source.split("def _rt(")[1], "no animation uses the timing helper"
    assert "max(0.8, tracker.duration)" not in source, (
        "an animation still stretches to the full narration duration"
    )
    assert "config.background_color = DELOITTE_WHITE" in source, (
        "scene must render on the white Deloitte canvas"
    )
    assert "def _fit(" in source, "width-clamp helper missing from generated source"
    assert "_fit(" in source.split("def _fit(")[1], "no text uses the width clamp"


@pytest.mark.parametrize("name", sorted(_SAMPLES))
def test_overlong_opener_narration_rejected(name: str) -> None:
    data = dict(_SAMPLES[name])
    data["scene_narration"] = " ".join(["word"] * 120)
    with pytest.raises(ValueError, match="budget"):
        REGISTRY[name].validate(data)


def test_narration_within_budget_passes() -> None:
    data = dict(_SAMPLES["vertical_stack"])
    data["scene_narration"] = " ".join(["word"] * 40)  # over budget (25) but under hard cap (50)
    validated = REGISTRY["vertical_stack"].validate(data)
    assert len(validated["scene_narration"].split()) == 40


def test_visible_text_mild_overage_passes_untruncated() -> None:
    """≤1.5x the cap passes through verbatim — the emitted _fit clamp absorbs
    the overflow by shrinking. No mid-word ellipsis ever reaches the screen."""
    data = dict(_SAMPLES["vertical_stack"])
    label = "x" * 34  # cap is 26, hard cap 39
    data["items"] = [{"label": label, "detail": "d", "narration": "n"}] * 3
    validated = REGISTRY["vertical_stack"].validate(data)
    assert validated["items"][0]["label"] == label
    assert "…" not in validated["items"][0]["label"]


def test_visible_text_gross_overage_rejected() -> None:
    """>1.5x the cap raises so the controller's repair loop can shorten it —
    the same policy narration budgets follow."""
    data = dict(_SAMPLES["vertical_stack"])
    data["items"] = [{"label": "x" * 60, "detail": "d", "narration": "n"}] * 3
    with pytest.raises(ValueError, match="chars"):
        REGISTRY["vertical_stack"].validate(data)


def test_definition_never_scales_text_up() -> None:
    """Text(width=...) is scale-to-fit and blew short definitions up to banner
    size; the definition body must use the downscale-only _fit clamp instead."""
    template = REGISTRY["definition"]
    data = template.validate(dict(_SAMPLES["definition"]))
    source = template.render(data, "test_scene", "", '""')
    assert "width=11" not in source
    assert "definition_text = _fit(" in source


def test_scenario_opener_is_not_a_blank_screen() -> None:
    """The opener narration must reveal the scenario frame — up to ~10 s of
    speech over an empty white canvas otherwise."""
    template = REGISTRY["scenario"]
    data = template.validate(dict(_SAMPLES["scenario"]))
    source = template.render(data, "test_scene", "", '""')
    opener = source.split("with self.voiceover", 2)[1]
    assert "FadeIn(setup_box)" in opener
