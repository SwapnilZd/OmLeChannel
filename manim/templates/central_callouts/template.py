"""central_callouts — hub circle with labelled spokes radiating outward.

Ideal for: a core concept + 3–8 surrounding attributes or properties.
Font size and spoke radius auto-scale with callout count.
"""
from __future__ import annotations

import math
import textwrap

from .._shared import (
    _ACCENT, _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .layout import (
    CC_ARROW_B, CC_CENTER_SZ,
    CC_DOT_R, CC_HUB_FIT, CC_HUB_R, CC_LBL_BUFF, CC_LBL_FIT, CC_TIERS,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "center_label": "Core concept label, max 18 chars",
  "center_narration": "1-2 sentences as the hub appears, max ~45 words",
  "callouts": [
    {
      "label": "Callout label, max 20 chars",
      "narration": "1-2 sentences as this callout appears, max ~45 words"
    }
  ],
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""

# 8-way compass directions ordered by angle (0°=RIGHT, counterclockwise).
_DIRS8 = ["RIGHT", "UP+RIGHT", "UP", "UP+LEFT", "LEFT", "DOWN+LEFT", "DOWN", "DOWN+RIGHT"]


def _label_dir(angle_deg: float) -> str:
    """Map a spoke angle to the nearest 8-way Manim direction string."""
    sector = round((angle_deg % 360) / 45) % 8
    return _DIRS8[sector]


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the central_callouts template schema.
        The template shows a central hub circle with 3–8 labelled callouts radiating
        outward, each revealed with narration. The scene title becomes the center_label;
        elements become callouts.

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema (3 to 8 callouts):
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    callouts = data.get("callouts", [])[:8]
    for i, c in enumerate(callouts):
        c["label"]     = _check_text(f"callouts[{i}].label", c.get("label", ""), 20)
        c["narration"] = str(c.get("narration", ""))
        _check_narration(f"callouts[{i}].narration", c["narration"], _ITEM_WORDS)
    data["center_label"]      = _check_text("center_label", data.get("center_label", "Core Concept"), 18)
    data["center_narration"]  = str(data.get("center_narration", ""))
    data["scene_narration"]   = str(data.get("scene_narration", ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("center_narration",  data["center_narration"],  _ITEM_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    data["callouts"] = callouts
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    callouts = data["callouts"]
    n        = len(callouts)
    tier_n   = min(max(n, 3), 8)
    callout_sz, spoke_r = CC_TIERS[tier_n]

    # Pre-compute spoke positions starting from top, distributed evenly
    positions: list[tuple[float, float]] = []
    hub_edges:  list[tuple[float, float]] = []
    lbl_dirs:   list[str] = []
    for i in range(n):
        angle_deg = 90 - i * (360 / n)
        rad = math.radians(angle_deg)
        cx = round(spoke_r * math.cos(rad), 3)
        cy = round(spoke_r * math.sin(rad), 3)
        positions.append((cx, cy))
        hx = round(CC_HUB_R * math.cos(rad), 3)
        hy = round(CC_HUB_R * math.sin(rad), 3)
        hub_edges.append((hx, hy))
        lbl_dirs.append(_label_dir(angle_deg))

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
        "        # Central hub",
        f"        hub_circle = Circle(radius={CC_HUB_R}, fill_color=DEEP_GREEN, fill_opacity=1,",
        "                            stroke_color=DELOITTE_GREEN, stroke_width=2.5)",
        "        hub_circle.move_to(ORIGIN)",
        f'        hub_label = _fit(Text("{_esc(data["center_label"])}", font_size={CC_CENTER_SZ},'
        f" color=DELOITTE_WHITE, font=FONT, weight=BOLD), {CC_HUB_FIT})",
        "        hub_label.move_to(hub_circle.get_center())",
        "        hub = VGroup(hub_circle, hub_label)",
        "",
    ]

    for i, (callout, (cx, cy), (hx, hy), ldir) in enumerate(
        zip(callouts, positions, hub_edges, lbl_dirs)
    ):
        accent = _ACCENT[i % len(_ACCENT)]
        lines += [
            f"        # Callout {i}",
            f"        c_pos_{i} = np.array([{cx}, {cy}, 0])",
            f"        c_dot_{i} = Circle(radius={CC_DOT_R}, fill_color={accent},"
            " fill_opacity=1, stroke_width=0)",
            f"        c_dot_{i}.move_to(c_pos_{i})",
            f'        c_lbl_{i} = _fit(Text("{_esc(callout["label"])}", font_size={callout_sz},'
            f" color=DELOITTE_DARK_GRAY, font=FONT), {CC_LBL_FIT})",
            f"        c_lbl_{i}.next_to(c_dot_{i}, {ldir}, buff={CC_LBL_BUFF})",
            f"        c_arrow_{i} = Arrow(np.array([{hx}, {hy}, 0]), c_pos_{i},",
            f"                            color=COOL_GRAY_9, stroke_width=2.0, buff={CC_ARROW_B})",
            f"        cg_{i} = VGroup(c_dot_{i}, c_lbl_{i})",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.5, 0.8, 2.0)",
        "            self.play(FadeIn(hub, scale=0.85), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
        f'        with self.voiceover(text="{_esc(data["center_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
        "",
    ]

    for i, callout in enumerate(callouts):
        lines += [
            f'        with self.voiceover(text="{_esc(callout["narration"])}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.25, 0.4, 1.0)",
            "            r2 = _rt(d, 0.3, 0.5, 1.5)",
            f"            self.play(Create(c_arrow_{i}), run_time=r1)",
            f"            self.play(FadeIn(cg_{i}), run_time=r2)",
            "            self.wait(max(0.0, d - r1 - r2))",
            "",
        ]

    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(lines)


TEMPLATE = Template(
    name="central_callouts",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
