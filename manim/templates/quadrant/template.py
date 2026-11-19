"""quadrant — 2×2 matrix revealed quadrant by quadrant.

Ideal for: prioritization frameworks (urgent/important), risk matrices,
effort/impact analysis.
"""
from __future__ import annotations

import textwrap

from .._shared import (
    _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .layout import (
    QD_AXLBL_FIT_X, QD_AXLBL_FIT_Y, QD_AXLBL_SZ, QD_AXIS_X, QD_AXIS_Y,
    QD_H_X0, QD_H_X1, QD_ITEM_MAX_W, QD_ITEM_STEP, QD_ITEM_SZ,
    QD_ITEMS_Y0_B, QD_ITEMS_Y0_T, QD_QH_BY, QD_QH_INSET,
    QD_QH_SZ, QD_QH_Y, QD_V_Y0, QD_V_Y1,
)

_SCHEMA = """\
{
  "scene_narration": "1-2 sentence opener spoken aloud, max ~25 words",
  "x_low":  "Low-end X axis label, max 15 chars",
  "x_high": "High-end X axis label, max 15 chars",
  "y_low":  "Low-end Y axis label, max 15 chars",
  "y_high": "High-end Y axis label, max 15 chars",
  "tl_label": "Top-left quadrant name, max 20 chars",
  "tl_items": ["item text, max 28 chars"],
  "tl_narration": "1-2 sentences as top-left reveals, max ~45 words",
  "tr_label": "Top-right quadrant name, max 20 chars",
  "tr_items": ["item text, max 28 chars"],
  "tr_narration": "1-2 sentences as top-right reveals, max ~45 words",
  "bl_label": "Bottom-left quadrant name, max 20 chars",
  "bl_items": ["item text, max 28 chars"],
  "bl_narration": "1-2 sentences as bottom-left reveals, max ~45 words",
  "br_label": "Bottom-right quadrant name, max 20 chars",
  "br_items": ["item text, max 28 chars"],
  "br_narration": "1-2 sentences as bottom-right reveals, max ~45 words",
  "closing_narration": "1-2 sentence closer spoken aloud, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene plan to the quadrant template schema.
        The template shows a 2×2 matrix with labelled axes and items in each quadrant,
        revealed quadrant by quadrant with narration. Decide appropriate axis labels
        based on the scene content, then distribute elements across the four quadrants.
        Use 1–3 items per quadrant.

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema:
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    for key in ("x_low", "x_high", "y_low", "y_high"):
        data[key] = _check_text(key, data.get(key, ""), 15)
    for prefix in ("tl", "tr", "bl", "br"):
        lbl_key  = f"{prefix}_label"
        item_key = f"{prefix}_items"
        narr_key = f"{prefix}_narration"
        data[lbl_key]  = _check_text(lbl_key, data.get(lbl_key, ""), 20)
        items = [_check_text(f"{item_key}[{j}]", it, 28)
                 for j, it in enumerate(data.get(item_key, [])[:3])]
        data[item_key] = items
        data[narr_key] = str(data.get(narr_key, ""))
        _check_narration(narr_key, data[narr_key], _ITEM_WORDS)
    data["scene_narration"]   = str(data.get("scene_narration", ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    _check_narration("scene_narration",   data["scene_narration"],   _OPENER_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    # Pre-compute item Y positions for top and bottom quadrants at render time.
    def _item_ys(y0: float, count: int) -> list[float]:
        return [round(y0 + j * QD_ITEM_STEP, 3) for j in range(count)]

    # Build lines for one quadrant (header + items + VGroup).
    def _quad_lines(
        prefix: str,
        label: str,
        items: list[str],
        hdr_x: float,
        hdr_y: float,
        item_x: float,
        y0: float,
    ) -> list[str]:
        result = [f"        # {prefix.upper()} quadrant"]
        result.append(
            f'        {prefix}_hdr = _fit(Text("{_esc(label)}", font_size={QD_QH_SZ},'
        )
        result.append(
            f"                    color=DEEP_GREEN, font=FONT, weight=BOLD), {QD_ITEM_MAX_W})"
        )
        result.append(
            f"        {prefix}_hdr.move_to(np.array([{hdr_x}, {hdr_y}, 0]))"
        )
        ys = _item_ys(y0, len(items))
        for j, (item_text, iy) in enumerate(zip(items, ys)):
            result.append(
                f'        {prefix}_item_{j} = _fit(Text("{_esc(item_text)}", font_size={QD_ITEM_SZ},'
            )
            result.append(
                f"                    color=DELOITTE_DARK_GRAY, font=FONT), {QD_ITEM_MAX_W})"
            )
            result.append(
                f"        {prefix}_item_{j}.move_to(np.array([{item_x}, {iy}, 0]))"
            )
        result.append("")
        return result

    tl_items = data["tl_items"]
    tr_items = data["tr_items"]
    bl_items = data["bl_items"]
    br_items = data["br_items"]

    # Embed axis positions as literals (computed from layout constants at render time)
    h_x0   = QD_H_X0
    h_x1   = QD_H_X1
    ax_y   = QD_AXIS_Y
    ax_x   = QD_AXIS_X
    v_y0   = QD_V_Y0
    v_y1   = QD_V_Y1
    inset  = QD_QH_INSET
    xl_x   = round(QD_H_X0 + 0.8, 3)
    xh_x   = round(QD_H_X1 - 0.8, 3)
    yl_y   = round(QD_V_Y0 + 0.5, 3)
    yh_y   = round(QD_V_Y1 - 0.5, 3)
    lbl_dy = round(QD_AXIS_Y - 0.3, 3)
    lbl_dx = round(QD_AXIS_X - 0.4, 3)

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
        "        # Axes",
        f"        h_axis = Arrow(np.array([{h_x0}, {ax_y}, 0]), np.array([{h_x1}, {ax_y}, 0]),",
        "                       color=COOL_GRAY_9, stroke_width=1.5, buff=0)",
        f"        v_axis = Arrow(np.array([{ax_x}, {v_y0}, 0]), np.array([{ax_x}, {v_y1}, 0]),",
        "                       color=COOL_GRAY_9, stroke_width=1.5, buff=0)",
        f'        x_low_lbl = _fit(Text("{_esc(data["x_low"])}", font_size={QD_AXLBL_SZ},'
        f" color=COOL_GRAY_9, font=FONT), {QD_AXLBL_FIT_X})",
        f"        x_low_lbl.move_to(np.array([{xl_x}, {lbl_dy}, 0]))",
        f'        x_high_lbl = _fit(Text("{_esc(data["x_high"])}", font_size={QD_AXLBL_SZ},'
        f" color=COOL_GRAY_9, font=FONT), {QD_AXLBL_FIT_X})",
        f"        x_high_lbl.move_to(np.array([{xh_x}, {lbl_dy}, 0]))",
        # y labels rotate 90° — clamp width BEFORE rotation so the clamp bounds
        # their on-screen height along the axis.
        f'        y_low_lbl = _fit(Text("{_esc(data["y_low"])}", font_size={QD_AXLBL_SZ},'
        f" color=COOL_GRAY_9, font=FONT), {QD_AXLBL_FIT_Y}).rotate(PI / 2)",
        f"        y_low_lbl.move_to(np.array([{lbl_dx}, {yl_y}, 0]))",
        f'        y_high_lbl = _fit(Text("{_esc(data["y_high"])}", font_size={QD_AXLBL_SZ},'
        f" color=COOL_GRAY_9, font=FONT), {QD_AXLBL_FIT_Y}).rotate(PI / 2)",
        f"        y_high_lbl.move_to(np.array([{lbl_dx}, {yh_y}, 0]))",
        "        axes_grp = VGroup(h_axis, v_axis, x_low_lbl, x_high_lbl,"
        " y_low_lbl, y_high_lbl)",
        "",
    ]

    # Quadrant groups
    lines += _quad_lines("tl", data["tl_label"], tl_items, -inset, QD_QH_Y,  -inset, QD_ITEMS_Y0_T)
    lines += _quad_lines("tr", data["tr_label"], tr_items,  inset, QD_QH_Y,   inset, QD_ITEMS_Y0_T)
    lines += _quad_lines("bl", data["bl_label"], bl_items, -inset, QD_QH_BY, -inset, QD_ITEMS_Y0_B)
    lines += _quad_lines("br", data["br_label"], br_items,  inset, QD_QH_BY,  inset, QD_ITEMS_Y0_B)

    # Animation sequence — axes draw is elastic (6 mobjects create sequentially);
    # each quadrant stages header then items.
    lines = lines + [
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.6, 1.0, 4.0)",
        "            self.play(Create(axes_grp), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]
    for prefix in ("tl", "tr", "bl", "br"):
        narration = data[prefix + "_narration"]
        item_names = ", ".join(
            f"FadeIn({prefix}_item_{j})" for j in range(len(data[prefix + "_items"]))
        )
        lines += [
            f'        with self.voiceover(text="{_esc(narration)}") as tracker:',
            "            d = tracker.duration",
            "            r1 = _rt(d, 0.3, 0.5, 1.2)",
            "            r2 = _rt(d, 0.3, 0.5, 1.5)",
            f"            self.play(Write({prefix}_hdr), run_time=r1)",
        ]
        if item_names:
            lines += [
                f"            self.play({item_names}, run_time=r2)",
                "            self.wait(max(0.0, d - r1 - r2))",
            ]
        else:
            lines += ["            self.wait(max(0.0, d - r1))"]
        lines += [""]
    lines += [
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]

    return "\n".join(lines)


TEMPLATE = Template(
    name="quadrant",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
