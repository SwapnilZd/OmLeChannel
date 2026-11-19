"""definition — single concept breakdown with term, definition, and key attributes.

Ideal for: vocabulary, technical terms, key principles (2–4 attributes).
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
    DFN_ATTR_SZ, DFN_ATTR_STEP, DFN_ATTR_Y0,
    DFN_DEF_SZ, DFN_DEF_Y,
    DFN_DIV_X0, DFN_DIV_X1, DFN_DIV_Y,
    DFN_KEY_X, DFN_SEP_X, DFN_VAL_X,
    DFN_TERM_SZ, DFN_TERM_Y,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "term": "The term or concept being defined, max 35 chars",
  "definition": "Formal one-sentence definition, max 100 chars",
  "definition_narration": "1-2 sentences spoken as definition appears, max ~45 words",
  "attributes": [
    {
      "key": "Attribute name, max 18 chars",
      "value": "Attribute value or example, max 55 chars",
      "narration": "1-2 sentences spoken as this attribute appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the definition template schema.
        The template presents a large term, a formal one-sentence definition, and
        2–4 key attributes revealed one by one below a divider line.
        Identify the concept being defined from the scene title or elements and
        map the scene elements to attributes (short key + concise value pairs).

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema (2 to 4 attributes):
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    attributes = data.get("attributes", [])[:4]
    for i, attr in enumerate(attributes):
        attr["key"]       = _check_text(f"attributes[{i}].key",   attr.get("key",   ""), 18)
        attr["value"]     = _check_text(f"attributes[{i}].value", attr.get("value", ""), 55)
        attr["narration"] = str(attr.get("narration", ""))
        _check_narration(f"attributes[{i}].narration", attr["narration"], _ITEM_WORDS)
    data["term"]                 = _check_text("term",       data.get("term", "Term"), 35)
    data["definition"]           = _check_text("definition", data.get("definition", ""), 100)
    data["scene_narration"]      = str(data.get("scene_narration",      ""))
    data["definition_narration"] = str(data.get("definition_narration", ""))
    data["closing_narration"]    = str(data.get("closing_narration",    ""))
    _check_narration("scene_narration",      data["scene_narration"],      _OPENER_WORDS)
    _check_narration("definition_narration", data["definition_narration"], _ITEM_WORDS)
    _check_narration("closing_narration",    data["closing_narration"],    _CLOSING_WORDS)
    data["attributes"] = attributes
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    attributes = data["attributes"]
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
        f'        term = _fit(Text("{_esc(data["term"])}", font_size={DFN_TERM_SZ},'
        f" color=DEEP_GREEN, weight=BOLD, font=FONT), {_TITLE_MAX_W})",
        f"        term.move_to(np.array([0, {DFN_TERM_Y}, 0]))",
        # Downscale-only clamp: Text(width=...) scale-to-fit would blow short
        # definitions up to banner size.
        f'        definition_text = _fit(Text("{_esc(data["definition"])}", font_size={DFN_DEF_SZ},'
        " color=DELOITTE_DARK_GRAY, font=FONT), 11)",
        f"        definition_text.move_to(np.array([0, {DFN_DEF_Y}, 0]))",
        f"        divider = Line(np.array([{DFN_DIV_X0}, {DFN_DIV_Y}, 0]),"
        f" np.array([{DFN_DIV_X1}, {DFN_DIV_Y}, 0]), color=MID_GREEN)",
        "",
    ]

    key_fit = round(DFN_SEP_X - DFN_KEY_X - 0.2, 3)
    val_fit = 8.0   # value is left-aligned at DFN_VAL_X; keep clear of the frame edge
    for i, attr in enumerate(attributes):
        accent = _ACCENT[i % len(_ACCENT)]
        y = round(DFN_ATTR_Y0 + i * DFN_ATTR_STEP, 3)
        lines += [
            f'        key_{i} = _fit(Text("{_esc(attr["key"])}", font_size={DFN_ATTR_SZ},'
            f" color={accent}, weight=BOLD, font=FONT), {key_fit})",
            f'        sep_{i} = Text(":", font_size={DFN_ATTR_SZ}, color={accent}, font=FONT)',
            f'        val_{i} = _fit(Text("{_esc(attr["value"])}", font_size={DFN_ATTR_SZ},'
            f" color=DELOITTE_DARK_GRAY, font=FONT), {val_fit})",
            f"        key_{i}.move_to(np.array([{DFN_KEY_X}, {y}, 0]), aligned_edge=LEFT)",
            f"        sep_{i}.move_to(np.array([{DFN_SEP_X}, {y}, 0]))",
            f"        val_{i}.move_to(np.array([{DFN_VAL_X}, {y}, 0]), aligned_edge=LEFT)",
            f"        attr_{i} = VGroup(key_{i}, sep_{i}, val_{i})",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Write(term), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
        f'        with self.voiceover(text="{_esc(data["definition_narration"])}") as tracker:',
        "            d = tracker.duration",
        "            r1 = _rt(d, 0.35, 0.6, 1.8)",
        "            r2 = _rt(d, 0.2, 0.4, 0.9)",
        "            self.play(FadeIn(definition_text), run_time=r1)",
        "            self.play(Create(divider), run_time=r2)",
        "            self.wait(max(0.0, d - r1 - r2))",
        "",
    ]

    for i, attr in enumerate(attributes):
        lines += [
            f'        with self.voiceover(text="{_esc(attr["narration"])}") as tracker:',
            "            rt = _rt(tracker.duration, 0.4, 0.8, 3.0)",
            f"            self.play(FadeIn(attr_{i}), run_time=rt)",
            "            self.wait(max(0.0, tracker.duration - rt))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(lines)


TEMPLATE = Template(
    name="definition",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
