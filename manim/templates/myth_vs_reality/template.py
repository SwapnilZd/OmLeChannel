"""myth_vs_reality — paired myth/correction rows, revealed one pair at a time.

Ideal for: correcting misconceptions (max 3 pairs).
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
    MVR_BODY_SZ, MVR_BOX_H, MVR_BOX_RADIUS, MVR_BOX_W,
    MVR_CORR_Y, MVR_ICON_BUFF, MVR_ICON_SZ, MVR_MYTH_Y,
    MVR_TEXT_BUFF, MVR_TITLE_SZ, MVR_TITLE_Y,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener, max ~25 words",
  "title": "Scene title, max 50 chars",
  "pairs": [
    {
      "misconception":        "The myth, max 55 chars",
      "myth_narration":       "1-2 sentences spoken as the myth appears, max ~45 words",
      "correction":           "The reality, max 55 chars",
      "correction_narration": "1-2 sentences spoken as the correction appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene to the myth_vs_reality template schema.
        Elements come in pairs: odd-indexed = misconception, even-indexed = correction.
        Each pair becomes one entry in "pairs". Maximum 3 pairs.

        Scene title: {scene["title"]}
        Opener: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing: {scene["closing_narration"]}

        Return this exact JSON schema:
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    pairs = data.get("pairs", [])[:3]
    for i, p in enumerate(pairs):
        p["misconception"]        = _check_text(f"pairs[{i}].misconception", p.get("misconception", ""), 55)
        p["myth_narration"]       = str(p.get("myth_narration", ""))
        p["correction"]           = _check_text(f"pairs[{i}].correction",    p.get("correction", ""),    55)
        p["correction_narration"] = str(p.get("correction_narration", ""))
        _check_narration(f"pairs[{i}].myth_narration",       p["myth_narration"],       _ITEM_WORDS)
        _check_narration(f"pairs[{i}].correction_narration", p["correction_narration"], _ITEM_WORDS)
    data["title"]             = _check_text("title", data.get("title", "Common Misconceptions"), 50)
    data["scene_narration"]   = str(data.get("scene_narration", ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["pairs"] = pairs
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    pairs = data["pairs"]
    row_fit = round(MVR_BOX_W - 1.2, 3)   # icon + insets eat ~1.2 of the row box
    L = [
        "from manim import *",
        "from manim_voiceover import VoiceoverScene",
        "import numpy as np",
        tts_import, "",
        _PALETTE_BLOCK, "",
        _RT_BLOCK, "",
        _FIT_BLOCK, "",
        f"class Scene_{scene_id}(VoiceoverScene):",
        "    def construct(self):",
        f"        self.set_speech_service({service_call})", "",
        f'        mvr_title = _fit(Text("{_esc(data["title"])}", font_size={MVR_TITLE_SZ},',
        f"                         color=DEEP_GREEN, weight=BOLD, font=FONT), {_TITLE_MAX_W})",
        f"        mvr_title.move_to(np.array([0, {MVR_TITLE_Y}, 0]))", "",
    ]

    for i, (pair, my, cy) in enumerate(zip(pairs, MVR_MYTH_Y, MVR_CORR_Y)):
        myth = _esc(pair["misconception"])
        corr = _esc(pair["correction"])
        L += [
            f"        mb_{i} = RoundedRectangle(width={MVR_BOX_W}, height={MVR_BOX_H}, corner_radius={MVR_BOX_RADIUS},",
            "                    fill_color=CARD_BG, fill_opacity=1, stroke_color=FUNCTIONAL_RED, stroke_width=2)",
            f"        mb_{i}.move_to(np.array([0, {my}, 0]))",
            f'        mi_{i} = Text("✗", font_size={MVR_ICON_SZ}, color=FUNCTIONAL_RED, font=FONT)',
            f"        mi_{i}.next_to(mb_{i}.get_left(), RIGHT, buff={MVR_ICON_BUFF})",
            f'        mt_{i} = _fit(Text("{myth}", font_size={MVR_BODY_SZ}, color=DELOITTE_DARK_GRAY, font=FONT), {row_fit})',
            f"        mt_{i}.next_to(mi_{i}, RIGHT, buff={MVR_TEXT_BUFF})",
            f"        myth_row_{i} = VGroup(mb_{i}, mi_{i}, mt_{i})", "",
            f"        cb_{i} = RoundedRectangle(width={MVR_BOX_W}, height={MVR_BOX_H}, corner_radius={MVR_BOX_RADIUS},",
            "                    fill_color=CARD_BG, fill_opacity=1, stroke_color=MID_GREEN, stroke_width=2)",
            f"        cb_{i}.move_to(np.array([0, {cy}, 0]))",
            f'        ci_{i} = Text("✓", font_size={MVR_ICON_SZ}, color=MID_GREEN, font=FONT)',
            f"        ci_{i}.next_to(cb_{i}.get_left(), RIGHT, buff={MVR_ICON_BUFF})",
            f'        ct_{i} = _fit(Text("{corr}", font_size={MVR_BODY_SZ}, color=DELOITTE_DARK_GRAY, font=FONT), {row_fit})',
            f"        ct_{i}.next_to(ci_{i}, RIGHT, buff={MVR_TEXT_BUFF})",
            f"        corr_row_{i} = VGroup(cb_{i}, ci_{i}, ct_{i})", "",
        ]

    L += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Write(mvr_title), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))", "",
    ]

    for i, pair in enumerate(pairs):
        L += [
            f'        with self.voiceover(text="{_esc(pair["myth_narration"])}") as tracker:',
            "            rt = _rt(tracker.duration, 0.4, 0.8, 3.0)",
            f"            self.play(FadeIn(myth_row_{i}, shift=LEFT*0.2), run_time=rt)",
            "            self.wait(max(0.0, tracker.duration - rt))", "",
            f'        with self.voiceover(text="{_esc(pair["correction_narration"])}") as tracker:',
            "            rt = _rt(tracker.duration, 0.4, 0.8, 3.0)",
            f"            self.play(FadeIn(corr_row_{i}, shift=LEFT*0.2), run_time=rt)",
            "            self.wait(max(0.0, tracker.duration - rt))", "",
        ]

    L += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(L)


TEMPLATE = Template(
    name="myth_vs_reality",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
