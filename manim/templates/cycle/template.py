"""cycle — 3–5 steps arranged in a circle with directional arrows.

Ideal for: PDCA, Agile sprints, feedback loops, lifecycle stages, iterative processes.
"""
from __future__ import annotations

import math
import textwrap

from .._shared import (
    _ACCENT, _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _TITLE_MAX_W, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .layout import (
    CY_ARROW_BUFF, CY_ARROW_SW, CY_LABEL_FIT, CY_LABEL_SZ,
    CY_NODE_R, CY_RING_R, CY_TITLE_SZ, CY_TITLE_Y,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "title": "Cycle title, max 50 chars",
  "steps": [
    {
      "label": "Step label shown near node, max 16 chars",
      "narration": "1-2 sentences spoken as this step appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the cycle template schema.
        The template shows 3–5 steps arranged in a circle with directional arrows,
        each step revealed with narration. Map one element → one step.
        If there are more than 5 elements, merge minor ones.

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
        step["label"]     = _check_text(f"steps[{i}].label", step.get("label", ""), 16)
        step["narration"] = str(step.get("narration", ""))
        _check_narration(f"steps[{i}].narration", step["narration"], _ITEM_WORDS)
    while len(steps) < 3:
        steps.append({"label": f"Step {len(steps) + 1}", "narration": ""})
    data["title"]             = _check_text("title", data.get("title", "Cycle"), 50)
    data["scene_narration"]   = str(data.get("scene_narration", ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["steps"] = steps
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    steps = data["steps"]
    n = len(steps)

    # Pre-compute all node positions and outward unit vectors at render time.
    # Step 0 starts at 12 o'clock (90°), going clockwise.
    positions: list[tuple[float, float]] = []
    cos_sins:  list[tuple[float, float]] = []
    for i in range(n):
        angle_deg = 90 - i * (360 / n)
        rad = math.radians(angle_deg)
        cx    = round(CY_RING_R * math.cos(rad), 3)
        cy    = round(CY_RING_R * math.sin(rad), 3)
        cos_i = round(math.cos(rad), 3)
        sin_i = round(math.sin(rad), 3)
        positions.append((cx, cy))
        cos_sins.append((cos_i, sin_i))

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
        f'        title = _fit(Text("{_esc(data["title"])}", font_size={CY_TITLE_SZ}, color=DEEP_GREEN,',
        f"                    weight=BOLD, font=FONT), {_TITLE_MAX_W})",
        f"        title.move_to(np.array([0, {CY_TITLE_Y}, 0]))",
        "",
    ]

    # Node mobjects — circle + label positioned outward from center
    for i, (step, (cx, cy), (cos_i, sin_i)) in enumerate(
        zip(steps, positions, cos_sins)
    ):
        accent = _ACCENT[i % len(_ACCENT)]
        lines += [
            f"        # Node {i}",
            f"        node_{i} = Circle(radius={CY_NODE_R}, fill_color={accent},"
            " fill_opacity=1, stroke_width=0)",
            f"        node_{i}.move_to(np.array([{cx}, {cy}, 0]))",
            f'        lbl_{i} = _fit(Text("{_esc(step["label"])}", font_size={CY_LABEL_SZ},'
            f" color=DELOITTE_DARK_GRAY, font=FONT, weight=BOLD), {CY_LABEL_FIT})",
            f"        lbl_{i}.next_to(node_{i}, np.array([{cos_i}, {sin_i}, 0]), buff=0.12)",
            f"        ng_{i} = VGroup(node_{i}, lbl_{i})",
            "",
        ]

    # Arrows between consecutive nodes (0→1, 1→2, …, n-1→0)
    for i in range(n):
        next_i = (i + 1) % n
        cx_i,    cy_i    = positions[i]
        cx_next, cy_next = positions[next_i]
        lines += [
            f"        # Arrow {i} → {next_i}",
            f"        arr_{i} = Arrow(",
            f"            np.array([{cx_i}, {cy_i}, 0]),",
            f"            np.array([{cx_next}, {cy_next}, 0]),",
            f"            buff={CY_ARROW_BUFF},",
            "            color=COOL_GRAY_9,",
            f"            stroke_width={CY_ARROW_SW})",
            "",
        ]

    # Animation sequence
    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.5)",
        "            self.play(Write(title), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
        f'        with self.voiceover(text="{_esc(steps[0]["narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.4, 0.8, 3.0)",
        "            self.play(FadeIn(ng_0), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]

    for i in range(1, n):
        lines += [
            f'        with self.voiceover(text="{_esc(steps[i]["narration"])}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.25, 0.4, 1.2)",
            "            r2 = _rt(d, 0.3, 0.5, 1.8)",
            f"            self.play(Create(arr_{i - 1}), run_time=r1)",
            f"            self.play(FadeIn(ng_{i}), run_time=r2)",
            "            self.wait(max(0.0, d - r1 - r2))",
            "",
        ]

    lines += [
        "        # Close the cycle with the final arrow",
        f"        self.play(Create(arr_{n - 1}), run_time=0.8)",
        "",
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]

    return "\n".join(lines)


TEMPLATE = Template(
    name="cycle",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
