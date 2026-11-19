#!/usr/bin/env python3
"""Focused regressions for the pre-render geometry measurement stub.

Run inside the renderer image with `make manim-geometry-regressions` so the
checks use the same Manim/Pango implementation and fonts as production.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from templates._geometry import check_source  # noqa: E402


_GROUPED_FADE_OUT = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_grouped_fade(VoiceoverScene):
    def construct(self):
        old = Text("Old label", font="Open Sans")
        self.play(Write(old))
        self.play(FadeOut(VGroup(old)))
        new = Text("New label", font="Open Sans")
        self.play(Write(new))
'''


_ANIMATED_MOVE = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_animated_move(VoiceoverScene):
    def construct(self):
        moved = Text("Moved label", font="Open Sans")
        self.play(Write(moved))
        self.play(moved.animate.shift(RIGHT * 5))
        replacement = Text("Replacement label", font="Open Sans")
        self.play(Write(replacement))
'''


_GROUP_CHILD_REMOVAL = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_group_child_removal(VoiceoverScene):
    def construct(self):
        removed = Text("Removed child", font="Open Sans")
        retained = Text("Keep", font="Open Sans").shift(RIGHT * 5)
        group = VGroup(removed, retained)
        self.play(FadeIn(group))
        self.play(FadeOut(removed))
        replacement = Text("Replacement", font="Open Sans")
        self.play(Write(replacement))
'''


_NORMAL_TRANSFORM = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_normal_transform(VoiceoverScene):
    def construct(self):
        moved = Text("Moved", font="Open Sans")
        target = moved.copy().shift(RIGHT * 5)
        self.play(Write(moved))
        self.play(Transform(moved, target))
        replacement = Text("Replacement", font="Open Sans")
        self.play(Write(replacement))
'''


_FADE_TRANSFORM = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_fade_transform(VoiceoverScene):
    def construct(self):
        old = Text("Old", font="Open Sans")
        new = Text("New", font="Open Sans").shift(RIGHT * 5)
        self.play(Write(old))
        self.play(FadeTransform(old, new))
        replacement = Text("Replacement", font="Open Sans")
        self.play(Write(replacement))
'''


_THERE_AND_BACK_EMPHASIS = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_there_and_back(VoiceoverScene):
    def construct(self):
        label = Text("X", font_size=20, font="Open Sans").shift(RIGHT * 6.8)
        self.play(Write(label))
        self.play(Indicate(label, scale_factor=4))
'''


_NESTED_RECTS = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_nested_rects(VoiceoverScene):
    def construct(self):
        background = RoundedRectangle(width=12, height=5)
        card = RoundedRectangle(width=4, height=1)
        label = Text("Fits its card", font_size=20, font="Open Sans")
        self.play(Create(background), Create(card), Write(label))
'''


_VERTICAL_OVERFLOW = r'''
from manim import *
from manim_voiceover import VoiceoverScene

class Scene_vertical_overflow(VoiceoverScene):
    def construct(self):
        card = RoundedRectangle(width=10, height=0.05, corner_radius=0.005)
        label = Text("Too tall", font_size=30, font="Open Sans")
        self.play(Create(card), Write(label))
'''


def _assert_clear(name: str, source: str) -> None:
    findings = check_source(source, box_tol=0.1, overlap_min=0.05, frame_tol=0.05)
    if findings:
        raise AssertionError(f"{name} unexpectedly failed: {findings}")


def main() -> int:
    _assert_clear("grouped fade-out", _GROUPED_FADE_OUT)
    _assert_clear("animated move", _ANIMATED_MOVE)
    _assert_clear("child removed from visible group", _GROUP_CHILD_REMOVAL)
    _assert_clear("normal transform", _NORMAL_TRANSFORM)
    _assert_clear("fade transform", _FADE_TRANSFORM)
    _assert_clear("there-and-back emphasis", _THERE_AND_BACK_EMPHASIS)
    _assert_clear("nested rectangles", _NESTED_RECTS)

    findings = check_source(
        _VERTICAL_OVERFLOW,
        box_tol=0.1,
        overlap_min=0.05,
        frame_tol=0.05,
    )
    overflow = next((item for item in findings if item["kind"] == "BOX-OVERFLOW"), None)
    if overflow is None:
        raise AssertionError("vertical overflow was not detected")
    if "top=" not in overflow["detail"] and "bottom=" not in overflow["detail"]:
        raise AssertionError(f"overflow axis missing from diagnostic: {overflow}")
    if overflow.get("beat") != 1:
        raise AssertionError(f"overflow beat missing from diagnostic: {overflow}")

    print("8 geometry regression cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
