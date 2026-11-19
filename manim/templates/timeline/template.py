"""timeline — horizontal timeline with events revealed left-to-right.

Ideal for: historical progressions, project phases, chronological sequences (3–5 events).
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
    TL_ABOVE_Y, TL_AXIS_X0, TL_AXIS_X1, TL_AXIS_Y,
    TL_BELOW_Y, TL_DATE_ABOVE, TL_DATE_BELOW, TL_DATE_FIT, TL_DATE_SZ,
    TL_DOT_R, TL_LABEL_FIT, TL_LABEL_SZ, TL_TICK_H, TL_TITLE_SZ, TL_TITLE_Y,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "title": "Timeline title, max 50 chars",
  "events": [
    {
      "date": "Date or period label, max 18 chars",
      "label": "Event label, max 22 chars",
      "narration": "1-2 sentences spoken as this event appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the timeline template schema.
        The template shows 3–5 events on a horizontal timeline, each revealed left-to-right with narration.
        Map one element → one event. If there are more than 5 elements, merge minor ones.

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema (3 to 5 events):
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    events = data.get("events", [])[:5]
    for i, event in enumerate(events):
        event["date"]      = _check_text(f"events[{i}].date",  event.get("date",  ""), 18)
        event["label"]     = _check_text(f"events[{i}].label", event.get("label", ""), 22)
        event["narration"] = str(event.get("narration", ""))
        _check_narration(f"events[{i}].narration", event["narration"], _ITEM_WORDS)
    data["title"]             = _check_text("title", data.get("title", "Timeline"), 50)
    data["scene_narration"]   = str(data.get("scene_narration",   ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["events"] = events
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    events = data["events"]
    n = len(events)

    # Compute x positions for each event along the axis
    xs = []
    for i in range(n):
        if n == 1:
            x = 0.0
        else:
            x = TL_AXIS_X0 + i * (TL_AXIS_X1 - TL_AXIS_X0) / (n - 1)
        xs.append(round(x, 3))

    # Precompute Y positions from layout constants (embedded as literals below)
    label_y_above = round(TL_AXIS_Y + TL_ABOVE_Y,    3)   # -0.4 + 1.0  =  0.6
    label_y_below = round(TL_AXIS_Y + TL_BELOW_Y,    3)   # -0.4 + -1.0 = -1.4
    date_y_above  = round(TL_AXIS_Y + TL_DATE_ABOVE,  3)  # -0.4 + 0.45 =  0.05
    date_y_below  = round(TL_AXIS_Y + TL_DATE_BELOW,  3)  # -0.4 + -0.45 = -0.85
    tick_above    = round(TL_AXIS_Y + TL_TICK_H,      3)  # -0.4 + 0.25 = -0.15
    tick_below    = round(TL_AXIS_Y - TL_TICK_H,      3)  # -0.4 - 0.25 = -0.65

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
        f'        title = _fit(Text("{_esc(data["title"])}", font_size={TL_TITLE_SZ}, color=DEEP_GREEN,'
        f" weight=BOLD, font=FONT), {_TITLE_MAX_W})",
        f"        title.move_to(np.array([0, {TL_TITLE_Y}, 0]))",
        "",
        f"        axis = Arrow(np.array([{TL_AXIS_X0}, {TL_AXIS_Y}, 0]),"
        f" np.array([{TL_AXIS_X1}, {TL_AXIS_Y}, 0]),",
        "                     color=DELOITTE_DARK_GRAY, stroke_width=2, buff=0)",
        "",
    ]

    for i, event in enumerate(events):
        x = xs[i]
        accent = _ACCENT[i % len(_ACCENT)]
        above = (i % 2 == 0)
        label_y  = label_y_above if above else label_y_below
        date_y   = date_y_above  if above else date_y_below
        tick_end = tick_above    if above else tick_below

        lines += [
            f"        dot_{i} = Dot(np.array([{x}, {TL_AXIS_Y}, 0]),"
            f" radius={TL_DOT_R}, color={accent})",
            f"        tick_{i} = Line(np.array([{x}, {TL_AXIS_Y}, 0]),"
            f" np.array([{x}, {tick_end}, 0]),",
            f"                       color={accent}, stroke_width=2)",
            f'        date_{i} = _fit(Text("{_esc(event["date"])}", font_size={TL_DATE_SZ},'
            f" color=COOL_GRAY_9, font=FONT), {TL_DATE_FIT})",
            f"        date_{i}.move_to(np.array([{x}, {date_y}, 0]))",
            f'        lbl_{i} = _fit(Text("{_esc(event["label"])}", font_size={TL_LABEL_SZ},'
            f" color=DELOITTE_DARK_GRAY, font=FONT, weight=BOLD), {TL_LABEL_FIT})",
            f"        lbl_{i}.move_to(np.array([{x}, {label_y}, 0]))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Create(axis), Write(title), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]

    for i, event in enumerate(events):
        lines += [
            f'        with self.voiceover(text="{_esc(event["narration"])}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.3, 0.5, 1.2)",
            "            r2 = _rt(d, 0.3, 0.5, 1.4)",
            f"            self.play(FadeIn(dot_{i}, scale=0.5), Create(tick_{i}), run_time=r1)",
            f"            self.play(FadeIn(date_{i}), Write(lbl_{i}), run_time=r2)",
            "            self.wait(max(0.0, d - r1 - r2))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(lines)


TEMPLATE = Template(
    name="timeline",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
