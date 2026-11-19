"""scenario — fixed 4-beat structure: setup → question → wrong answer → correct answer."""
from __future__ import annotations

import textwrap

from .._shared import (
    _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _TITLE_MAX_W, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .layout import (
    SC_CHOICE_H, SC_CHOICE_SZ, SC_CHOICE_W,
    SC_CORRECT_Y, SC_LABEL_SZ, SC_Q_SZ, SC_Q_Y,
    SC_SETUP_H, SC_SETUP_SZ, SC_SETUP_W, SC_SETUP_Y,
    SC_WRONG_Y,
)

_SCHEMA = """\
{
  "scene_narration":    "1-2 sentence opener, max ~25 words",
  "setup":              "Scenario description, max 55 chars",
  "setup_narration":    "1-2 sentences spoken as scenario appears, max ~45 words",
  "question":           "The question, max 48 chars",
  "question_narration": "1-2 sentences spoken as question appears, max ~45 words",
  "wrong_answer":       "✗ Wrong choice, max 44 chars",
  "wrong_narration":    "1-2 sentences explaining why it is wrong, max ~45 words",
  "correct_answer":     "✓ Correct choice, max 44 chars",
  "correct_narration":  "1-2 sentences explaining why it is correct, max ~45 words",
  "closing_narration":  "1-2 sentence closer, max ~30 words"
}"""


def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this scene to the scenario template schema.
        The scene has exactly 4 elements: setup, question, wrong answer, correct answer.
        Wrong answer label MUST start with ✗; correct answer MUST start with ✓.

        Scene title: {scene["title"]}
        Opener: {scene["scene_narration"]}
        Elements:
        {_elements_block(scene)}
        Closing: {scene["closing_narration"]}

        Return this exact JSON schema:
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    for key, maxlen in [
        ("setup",         55), ("question",      48),
        ("wrong_answer",  44), ("correct_answer", 44),
    ]:
        data[key] = _check_text(key, data.get(key, ""), maxlen)
    for key in ("scene_narration", "setup_narration", "question_narration",
                "wrong_narration", "correct_narration", "closing_narration"):
        data[key] = str(data.get(key, ""))
    _check_narration("scene_narration",    data["scene_narration"],    _OPENER_WORDS)
    _check_narration("closing_narration",  data["closing_narration"],  _CLOSING_WORDS)
    for key in ("setup_narration", "question_narration",
                "wrong_narration", "correct_narration"):
        _check_narration(key, data[key], _ITEM_WORDS)
    if not data["wrong_answer"].startswith("✗"):
        data["wrong_answer"] = "✗ " + data["wrong_answer"]
    if not data["correct_answer"].startswith("✓"):
        data["correct_answer"] = "✓ " + data["correct_answer"]
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    setup_fit  = round(SC_SETUP_W - 0.6, 3)
    choice_fit = round(SC_CHOICE_W - 0.8, 3)
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
        f"        setup_box = RoundedRectangle(width={SC_SETUP_W}, height={SC_SETUP_H}, corner_radius=0.3,",
        "                      fill_color=CARD_BG, fill_opacity=1,",
        "                      stroke_color=COOL_GRAY_9, stroke_width=1.5)",
        f"        setup_box.move_to(np.array([0, {SC_SETUP_Y}, 0]))",
        f'        setup_lbl = Text("Scenario", font_size={SC_LABEL_SZ}, font=FONT, color=COOL_GRAY_9, weight=BOLD)',
        "        setup_lbl.next_to(setup_box.get_top(), DOWN, buff=0.2)",
        f'        setup_txt = _fit(Text("{_esc(data["setup"])}", font_size={SC_SETUP_SZ}, font=FONT,',
        f"                          color=DELOITTE_DARK_GRAY), {setup_fit})",
        "        setup_txt.move_to(setup_box.get_center())", "",
        f'        q_txt = _fit(Text("{_esc(data["question"])}", font_size={SC_Q_SZ}, font=FONT,',
        f"                      color=DEEP_GREEN, weight=BOLD), {_TITLE_MAX_W})",
        f"        q_txt.move_to(np.array([0, {SC_Q_Y}, 0]))", "",
        f"        wrong_box = RoundedRectangle(width={SC_CHOICE_W}, height={SC_CHOICE_H}, corner_radius=0.2,",
        "                      fill_color=CARD_BG, fill_opacity=1, stroke_color=FUNCTIONAL_RED, stroke_width=2)",
        f"        wrong_box.move_to(np.array([0, {SC_WRONG_Y}, 0]))",
        f'        wrong_txt = _fit(Text("{_esc(data["wrong_answer"])}", font_size={SC_CHOICE_SZ}, font=FONT,',
        f"                          color=DELOITTE_DARK_GRAY), {choice_fit})",
        "        wrong_txt.move_to(wrong_box.get_center())", "",
        f"        correct_box = RoundedRectangle(width={SC_CHOICE_W}, height={SC_CHOICE_H}, corner_radius=0.2,",
        "                        fill_color=CARD_BG, fill_opacity=1,",
        "                        stroke_color=MID_GREEN, stroke_width=2)",
        f"        correct_box.move_to(np.array([0, {SC_CORRECT_Y}, 0]))",
        f'        correct_txt = _fit(Text("{_esc(data["correct_answer"])}", font_size={SC_CHOICE_SZ}, font=FONT,',
        f"                            color=MID_GREEN), {choice_fit})",
        "        correct_txt.move_to(correct_box.get_center())", "",
        "        # Opener reveals the scenario frame — never narrate over a blank canvas.",
        f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.4, 0.8, 2.0)",
        "            self.play(FadeIn(setup_box), Write(setup_lbl), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))", "",
        f'        with self.voiceover(text="{_esc(data["setup_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.35, 0.6, 1.8)",
        "            self.play(FadeIn(setup_txt), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))", "",
        f'        with self.voiceover(text="{_esc(data["question_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.4, 0.8, 2.5)",
        "            self.play(Write(q_txt), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "        self.play(Indicate(q_txt, color=MID_GREEN, scale_factor=1.05))", "",
        f'        with self.voiceover(text="{_esc(data["wrong_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.4, 0.8, 2.5)",
        "            self.play(FadeIn(VGroup(wrong_box, wrong_txt)), run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "        self.play(wrong_box.animate.set_opacity(0.3), wrong_txt.animate.set_opacity(0.3))", "",
        f'        with self.voiceover(text="{_esc(data["correct_narration"])}") as tracker:',
        "            rt = _rt(tracker.duration, 0.4, 0.8, 2.5)",
        "            self.play(FadeIn(VGroup(correct_box, correct_txt), scale=0.95),",
        "                      run_time=rt)",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "        self.play(Indicate(correct_box, color=MID_GREEN, scale_factor=1.02))", "",
        f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
        "            self.wait(tracker.duration)",
    ]
    return "\n".join(L)


TEMPLATE = Template(
    name="scenario",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
