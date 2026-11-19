"""process_flow — numbered steps in a horizontal row connected by arrows.

Ideal for: procedures, workflows, sequential processes, cause-and-effect chains (3–5 steps).
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
    PF_ARROW_GAP, PF_BOX_H, PF_BOX_RADIUS, PF_BOX_W,
    PF_DETAIL_SZ, PF_DETAIL_Y_OFF,
    PF_LABEL_SZ, PF_LABEL_Y_OFF,
    PF_NUM_SZ, PF_NUM_Y_OFF,
    PF_ROW_Y, PF_TITLE_SZ, PF_TITLE_Y,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "title": "Process title, max 50 chars",
  "steps": [
    {
      "label": "Step label, max 16 chars",
      "detail": "Supporting detail, max 22 chars",
      "narration": "1-2 sentences spoken as this step appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the process_flow template schema.
        The template shows 3–5 numbered steps in a horizontal row connected by arrows, revealed left-to-right.
        Map one element → one step. If there are more than 5 elements, merge minor ones.

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema (3 to 5 steps):
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    steps = data.get("steps", [])[:5]
    for i, step in enumerate(steps):
        # Caps sized so text at the cap fits the 2.0-wide step box at these fonts.
        step["label"]     = _check_text(f"steps[{i}].label",  step.get("label",  ""), 16)
        step["detail"]    = _check_text(f"steps[{i}].detail", step.get("detail", ""), 22)
        step["narration"] = str(step.get("narration", ""))
        _check_narration(f"steps[{i}].narration", step["narration"], _ITEM_WORDS)
    data["title"]             = _check_text("title", data.get("title", "Process"), 50)
    data["scene_narration"]   = str(data.get("scene_narration",   ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["steps"] = steps
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    steps = data["steps"]
    n = len(steps)

    # Compute center x positions for each step box
    pitch      = PF_BOX_W + PF_ARROW_GAP                    # 2.5
    total_span = PF_BOX_W * n + PF_ARROW_GAP * (n - 1)
    left_cx    = -total_span / 2 + PF_BOX_W / 2
    cxs        = [round(left_cx + i * pitch, 3) for i in range(n)]

    # Precompute Y positions from layout constants (embedded as literals below)
    num_y = round(PF_ROW_Y + PF_NUM_Y_OFF,    3)   # -0.3 + 0.28  = -0.02
    lbl_y = round(PF_ROW_Y + PF_LABEL_Y_OFF,  3)   # -0.3 + -0.05 = -0.35
    det_y = round(PF_ROW_Y + PF_DETAIL_Y_OFF, 3)   # -0.3 + -0.38 = -0.68

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
        f'        title = _fit(Text("{_esc(data["title"])}", font_size={PF_TITLE_SZ}, color=DEEP_GREEN,'
        f" weight=BOLD, font=FONT), {_TITLE_MAX_W})",
        f"        title.move_to(np.array([0, {PF_TITLE_Y}, 0]))",
        "",
    ]

    box_fit = round(PF_BOX_W - 0.15, 3)
    for i, step in enumerate(steps):
        cx     = cxs[i]
        accent = _ACCENT[i % len(_ACCENT)]

        lines += [
            f"        bg_{i} = RoundedRectangle(width={PF_BOX_W}, height={PF_BOX_H},"
            f" corner_radius={PF_BOX_RADIUS},",
            "                   fill_color=CARD_BG, fill_opacity=1,",
            f"                   stroke_color={accent}, stroke_width=2)",
            f"        bg_{i}.move_to(np.array([{cx}, {PF_ROW_Y}, 0]))",
            f'        num_{i} = Text("{i + 1}", font_size={PF_NUM_SZ}, color={accent},'
            " font=FONT, weight=BOLD)",
            f"        num_{i}.move_to(np.array([{cx}, {num_y}, 0]))",
            f'        lbl_{i} = _fit(Text("{_esc(step["label"])}", font_size={PF_LABEL_SZ},'
            f" color=DELOITTE_DARK_GRAY, font=FONT, weight=BOLD), {box_fit})",
            f"        lbl_{i}.move_to(np.array([{cx}, {lbl_y}, 0]))",
            f'        det_{i} = _fit(Text("{_esc(step["detail"])}", font_size={PF_DETAIL_SZ},'
            f" color=DELOITTE_DARK_GRAY, font=FONT), {box_fit})",
            f"        det_{i}.move_to(np.array([{cx}, {det_y}, 0]))",
            f"        step_{i} = VGroup(bg_{i}, num_{i}, lbl_{i}, det_{i})",
            "",
        ]

    # Arrows between consecutive steps
    for i in range(n - 1):
        arr_start_x = round(cxs[i]     + PF_BOX_W / 2, 3)
        arr_end_x   = round(cxs[i + 1] - PF_BOX_W / 2, 3)
        lines += [
            f"        arr_{i} = Arrow(",
            f"            np.array([{arr_start_x}, {PF_ROW_Y}, 0]),",
            f"            np.array([{arr_end_x}, {PF_ROW_Y}, 0]),",
            "            color=COOL_GRAY_9, stroke_width=2, buff=0)",
            "",
        ]

    # Animation
    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Write(title), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
        f'        with self.voiceover(text="{_esc(steps[0]["narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.4, 0.8, 3.0)",
        "            self.play(FadeIn(step_0), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]

    for i in range(1, n):
        lines += [
            f'        with self.voiceover(text="{_esc(steps[i]["narration"])}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.2, 0.4, 0.9)",
            "            r2 = _rt(d, 0.35, 0.6, 2.0)",
            f"            self.play(Create(arr_{i - 1}), run_time=r1)",
            f"            self.play(FadeIn(step_{i}), run_time=r2)",
            "            self.wait(max(0.0, d - r1 - r2))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(lines)


TEMPLATE = Template(
    name="process_flow",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
