"""vertical_stack — stacked cards revealed one by one.

Ideal for: enumerated items, steps, rules (3–5 cards).
"""
from __future__ import annotations

import textwrap

from .._shared import (
    _ACCENT, _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _TITLE_MAX_W, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .layout import (
    VS_CARD_BUFF, VS_CARD_H, VS_CARD_RADIUS, VS_CARD_W,
    VS_DETAIL_BUFF, VS_DETAIL_SZ,
    VS_LABEL_BUFF, VS_LABEL_SZ, VS_LABEL_TOP,
    VS_TITLE_BUFF, VS_TITLE_SZ, VS_TITLE_Y,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "title": "Scene title, max 50 chars",
  "items": [
    {
      "label": "Short label, max 26 chars",
      "detail": "One supporting sentence, max 80 chars",
      "narration": "1-2 sentences spoken as this card appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the vertical_stack template schema.
        The template shows 3–5 cards stacked vertically, each revealed with narration.
        Map one element → one item. If there are more than 5 elements, merge minor ones.

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema (3 to 5 items):
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    items = data.get("items", [])[:5]
    for i, item in enumerate(items):
        item["label"]     = _check_text(f"items[{i}].label",  item.get("label", ""),  26)
        item["detail"]    = _check_text(f"items[{i}].detail", item.get("detail", ""), 80)
        item["narration"] = str(item.get("narration", ""))
        _check_narration(f"items[{i}].narration", item["narration"], _ITEM_WORDS)
    data["title"]             = _check_text("title", data.get("title", "Scene"), 50)
    data["scene_narration"]   = str(data.get("scene_narration", ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["items"] = items
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    items = data["items"]
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
        f'        title = Text("{_esc(data["title"])}", font_size={VS_TITLE_SZ}, color=DEEP_GREEN,'
        " weight=BOLD, font=FONT)",
        f"        _fit(title, {_TITLE_MAX_W})",
        f"        title.move_to(np.array([0, {VS_TITLE_Y}, 0]))",
        "",
    ]

    text_fit = round(VS_CARD_W - 2 * VS_LABEL_BUFF, 3)
    for i, item in enumerate(items):
        accent = _ACCENT[i % len(_ACCENT)]
        lines += [
            f"        bg_{i} = RoundedRectangle(width={VS_CARD_W}, height={VS_CARD_H}, corner_radius={VS_CARD_RADIUS},",
            "                    fill_color=CARD_BG, fill_opacity=1,",
            f"                    stroke_color={accent}, stroke_width=2)",
            f'        lbl_{i} = _fit(Text("{_esc(item["label"])}", font_size={VS_LABEL_SZ},'
            f" color=DELOITTE_DARK_GRAY, font=FONT, weight=BOLD), {text_fit})",
            f'        det_{i} = _fit(Text("{_esc(item["detail"])}", font_size={VS_DETAIL_SZ},'
            f" color=DELOITTE_DARK_GRAY, font=FONT), {text_fit})",
            "",
        ]

    # Arrange bg boxes first — identical size so centering is exact.
    # Labels and details attach after, relative to the settled bg positions.
    bg_names = ", ".join(f"bg_{i}" for i in range(len(items)))
    lines += [
        f"        stack = VGroup({bg_names})",
        f"        stack.arrange(DOWN, buff={VS_CARD_BUFF})",
        f"        stack.next_to(title, DOWN, buff={VS_TITLE_BUFF})",
        "",
    ]

    for i in range(len(items)):
        lines += [
            f"        lbl_{i}.align_to(bg_{i}, UL)",
            f"        lbl_{i}.shift(RIGHT * {VS_LABEL_BUFF} + DOWN * {VS_LABEL_TOP})",
            f"        det_{i}.next_to(lbl_{i}, DOWN, buff={VS_DETAIL_BUFF}, aligned_edge=LEFT)",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Write(title), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]

    for i, item in enumerate(items):
        lines += [
            f'        with self.voiceover(text="{_esc(item["narration"])}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.35, 0.6, 1.6)",
            "            r2 = _rt(d, 0.25, 0.5, 1.2)",
            f"            self.play(FadeIn(bg_{i}, shift=RIGHT*0.15), Write(lbl_{i}), run_time=r1)",
            f"            self.play(FadeIn(det_{i}, shift=UP*0.08), run_time=r2)",
            "            self.wait(max(0.0, d - r1 - r2))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(lines)


TEMPLATE = Template(
    name="vertical_stack",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
