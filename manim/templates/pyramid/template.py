"""pyramid — hierarchical layers revealed bottom-up.

Ideal for: Maslow's hierarchy, Bloom's taxonomy, organizational structures,
and "foundation → advanced" progressions (3–5 levels).
"""
from __future__ import annotations

import textwrap

from .._shared import (
    _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _TITLE_MAX_W, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .layout import (
    PY_BAND_GAP, PY_BAND_H, PY_BAND_RADIUS,
    PY_LABEL_SZ, PY_MAX_W, PY_MIN_W,
    PY_STACK_TOP_Y, PY_TITLE_SZ, PY_TITLE_Y,
)

# Band colors top-to-bottom: MID_GREEN, TEAL_6, BLUE_4, DEEP_GREEN, DARK_GREEN
_BAND_COLORS = ["#26890D", "#007680", "#0076A8", "#046A38", "#1C3D26"]

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "title": "Pyramid title, max 50 chars",
  "levels": [
    {
      "label": "Level label, top to bottom order, max 22 chars",
      "narration": "1-2 sentences spoken as this level appears (reveal bottom-up), max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the pyramid template schema.
        The template displays a hierarchical pyramid with 3–5 bands, revealed bottom-up.
        The first level in the list is the narrowest top band; the last is the widest base.
        Map each scene element to a level label, ordered from top (most specific) to
        bottom (foundational or broadest). Bands are revealed from the base upward.

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema (3 to 5 levels, top to bottom order):
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    levels = data.get("levels", [])[:5]
    for i, level in enumerate(levels):
        level["label"]     = _check_text(f"levels[{i}].label", level.get("label", ""), 22)
        level["narration"] = str(level.get("narration", ""))
        _check_narration(f"levels[{i}].narration", level["narration"], _ITEM_WORDS)
    data["title"]             = _check_text("title", data.get("title", "Hierarchy"), 50)
    data["scene_narration"]   = str(data.get("scene_narration",   ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["levels"] = levels
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    levels = data["levels"]
    n = len(levels)

    # Geometry computed once — embedded as literals in the generated scene.
    stack_top_y = PY_STACK_TOP_Y - PY_BAND_H / 2

    lines = [
        "from manim import *",
        "from manim_voiceover import VoiceoverScene",
        "import numpy as np",
        tts_import,
        "",
        _PALETTE_BLOCK,
        "",
        _RT_BLOCK,
        "",
        _FIT_BLOCK,
        "",
        f"class Scene_{scene_id}(VoiceoverScene):",
        "    def construct(self):",
        f"        self.set_speech_service({service_call})",
        "",
        f'        title = _fit(Text("{_esc(data["title"])}", font_size={PY_TITLE_SZ},'
        f" color=DEEP_GREEN, weight=BOLD, font=FONT), {_TITLE_MAX_W})",
        f"        title.move_to(np.array([0, {PY_TITLE_Y}, 0]))",
        "",
    ]

    # Generate all band and label mobjects in top-to-bottom order (0 = top).
    for i, level in enumerate(levels):
        w = round(PY_MIN_W + i * (PY_MAX_W - PY_MIN_W) / max(n - 1, 1), 3)
        y = round(stack_top_y - i * (PY_BAND_H + PY_BAND_GAP), 3)
        color = _BAND_COLORS[i % len(_BAND_COLORS)]
        lbl_fit = round(w - 0.24, 3)   # label must stay inside its own band
        lines += [
            f'        band_{i} = RoundedRectangle(width={w}, height={PY_BAND_H},'
            f' corner_radius={PY_BAND_RADIUS}, fill_color="{color}",'
            f" fill_opacity=1, stroke_width=0)",
            f"        band_{i}.move_to(np.array([0, {y}, 0]))",
            f'        lbl_{i} = _fit(Text("{_esc(level["label"])}", font_size={PY_LABEL_SZ},'
            f" color=DELOITTE_WHITE, weight=BOLD, font=FONT), {lbl_fit})",
            f"        lbl_{i}.move_to(band_{i}.get_center())",
            "",
        ]

    # Animate: title first, then reveal bands bottom-up (n-1 down to 0).
    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Write(title), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]

    for i in range(n - 1, -1, -1):
        level = levels[i]
        lines += [
            f'        with self.voiceover(text="{_esc(level["narration"])}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.3, 0.6, 1.5)",
            "            r2 = _rt(d, 0.25, 0.5, 1.2)",
            f"            self.play(FadeIn(band_{i}, shift=UP*0.1), run_time=r1)",
            f"            self.play(Write(lbl_{i}), run_time=r2)",
            "            self.wait(max(0.0, d - r1 - r2))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(lines)


TEMPLATE = Template(
    name="pyramid",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
