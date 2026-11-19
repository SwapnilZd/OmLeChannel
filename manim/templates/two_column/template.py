"""two_column — left/right split with a divider, rows revealed one by one.

Ideal for: comparisons, contrasts, side-by-side groupings (2–6 row pairs).
Font size and card height auto-scale with item count.
"""
from __future__ import annotations

import textwrap

from .._shared import (
    _ACCENT, _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .layout import (
    TC_CARD_RADIUS, TC_CARD_W,
    TC_COL_X, TC_HEADER_SZ, TC_HEADER_Y,
    TC_TIERS,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "left_header": "Left column header, max 22 chars",
  "right_header": "Right column header, max 22 chars",
  "pairs": [
    {
      "left": "Left item text, max 32 chars",
      "right": "Right item text, max 32 chars",
      "narration": "1-2 sentences spoken as this row appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the two_column template schema.
        The template splits the screen with a left column and right column and a divider.
        Paired rows appear one at a time with narration. Use when comparing or grouping
        two categories side by side.

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema (2 to 6 pairs):
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    pairs = data.get("pairs", [])[:6]
    for i, p in enumerate(pairs):
        p["left"]      = _check_text(f"pairs[{i}].left",  p.get("left",  ""), 32)
        p["right"]     = _check_text(f"pairs[{i}].right", p.get("right", ""), 32)
        p["narration"] = str(p.get("narration", ""))
        _check_narration(f"pairs[{i}].narration", p["narration"], _ITEM_WORDS)
    data["left_header"]       = _check_text("left_header",  data.get("left_header",  "Left"),  22)
    data["right_header"]      = _check_text("right_header", data.get("right_header", "Right"), 22)
    data["scene_narration"]   = str(data.get("scene_narration",   ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["pairs"] = pairs
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    pairs = data["pairs"]
    tier_n = min(max(len(pairs), 3), 6)
    body_sz, card_h, row_step, row_y0 = TC_TIERS[tier_n]
    body_fit = round(TC_CARD_W - 0.3, 3)
    hdr_fit  = round(2 * (TC_COL_X - 0.2), 3)   # header must not cross the divider

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
        "        # Column headers and divider",
        f'        left_hdr  = _fit(Text("{_esc(data["left_header"])}", font_size={TC_HEADER_SZ},'
        f" color=DEEP_GREEN, weight=BOLD, font=FONT), {hdr_fit})",
        f'        right_hdr = _fit(Text("{_esc(data["right_header"])}", font_size={TC_HEADER_SZ},'
        f" color=DEEP_GREEN, weight=BOLD, font=FONT), {hdr_fit})",
        f"        left_hdr.move_to(np.array([-{TC_COL_X}, {TC_HEADER_Y}, 0]))",
        f"        right_hdr.move_to(np.array([{TC_COL_X}, {TC_HEADER_Y}, 0]))",
        "        divider = DashedLine(np.array([0, 3.5, 0]), np.array([0, -3.5, 0]),",
        "                             color=COOL_GRAY_9, stroke_width=1.5)",
        "",
    ]

    for i, pair in enumerate(pairs):
        y = round(row_y0 + i * row_step, 3)
        accent = _ACCENT[i % len(_ACCENT)]
        lines += [
            f"        # Row {i}",
            f"        lb_{i} = RoundedRectangle(width={TC_CARD_W}, height={card_h}, corner_radius={TC_CARD_RADIUS},",
            f"                    fill_color=CARD_BG, fill_opacity=1,"
            f" stroke_color={accent}, stroke_width=1.5)",
            f"        rb_{i} = RoundedRectangle(width={TC_CARD_W}, height={card_h}, corner_radius={TC_CARD_RADIUS},",
            f"                    fill_color=CARD_BG, fill_opacity=1,"
            f" stroke_color={accent}, stroke_width=1.5)",
            f"        lb_{i}.move_to(np.array([-{TC_COL_X}, {y}, 0]))",
            f"        rb_{i}.move_to(np.array([{TC_COL_X}, {y}, 0]))",
            f'        lt_{i} = _fit(Text("{_esc(pair["left"])}",  font_size={body_sz},'
            f" color=DELOITTE_DARK_GRAY, font=FONT), {body_fit})",
            f'        rt_{i} = _fit(Text("{_esc(pair["right"])}", font_size={body_sz},'
            f" color=DELOITTE_DARK_GRAY, font=FONT), {body_fit})",
            f"        lt_{i}.move_to(lb_{i}.get_center())",
            f"        rt_{i}.move_to(rb_{i}.get_center())",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Write(left_hdr), Write(right_hdr), Create(divider),",
        "                      run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]

    for i, pair in enumerate(pairs):
        lines += [
            f'        with self.voiceover(text="{_esc(pair["narration"])}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.35, 0.6, 1.5)",
            "            r2 = _rt(d, 0.3, 0.5, 1.5)",
            f"            self.play(FadeIn(lb_{i}), FadeIn(lt_{i}), run_time=r1)",
            f"            self.play(FadeIn(rb_{i}), FadeIn(rt_{i}), run_time=r2)",
            "            self.wait(max(0.0, d - r1 - r2))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(lines)


TEMPLATE = Template(
    name="two_column",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
