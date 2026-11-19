#!/usr/bin/env python3
"""Standalone validator for the scenario template.

Usage (from any working directory):
    python templates/scenario/validator.py
    python templates/scenario/validator.py --quality m
    python templates/scenario/validator.py --no-render

Output:
    previews/validator_scenario.py
    previews/preview_scenario.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE     = Path(__file__).parent.resolve()   # templates/scenario/
MANIM    = HERE.parent.parent                 # manim/
OUT_DIR  = HERE.parent / "_previews"
HTML_OUT = HERE.parent / "_previews" / "preview_scenario.html"

sys.path.insert(0, str(MANIM))

from templates._validator import build_single_html, render_template   # noqa: E402
from templates.scenario.template import TEMPLATE                       # noqa: E402

FIXTURE: dict = {
    "scene_narration": "Test your knowledge with this pawn scenario.",
    "setup": "White pawn on e2. Black pawn on d3.",
    "setup_narration": "White has a pawn on its starting square. Black threatens from d3.",
    "question": "What can White's pawn do?",
    "question_narration": "Think about every legal option available to White.",
    "wrong_answer": "✗ Move two squares to e4 only",
    "wrong_narration": "Two squares forward is possible, but it ignores a key capture.",
    "correct_answer": "✓ Advance to e3, e4, or capture d3",
    "correct_narration": "White can move one or two squares, or capture the black pawn diagonally.",
    "closing_narration": "Always scan for captures before committing to a forward move.",
}


def render(quality: str = "l", dry_run: bool = False) -> tuple[str, Path | None]:
    return render_template(TEMPLATE, FIXTURE, "scenario", quality, dry_run, OUT_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quality", default="l", choices=["l", "m", "h"],
                    help="Manim quality: l=480p (fast, default), m=720p, h=1080p")
    ap.add_argument("--no-render", action="store_true",
                    help="Write .py file only, skip Manim execution")
    args = ap.parse_args()

    print("\n  [scenario]")
    code, video = render(args.quality, args.no_render)
    print(f"    → {(OUT_DIR / 'validator_scenario.py').relative_to(MANIM.parent)}")
    if not args.no_render:
        print(f"    {'✓  ' + video.name if video else '✗  render failed'}")

    HTML_OUT.write_text(build_single_html("scenario", code, video, HTML_OUT.parent),
                        encoding="utf-8")
    print(f"  Report → {HTML_OUT.relative_to(MANIM.parent)}\n")


if __name__ == "__main__":
    main()
