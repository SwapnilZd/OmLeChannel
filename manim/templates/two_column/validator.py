#!/usr/bin/env python3
"""Standalone validator for the two_column template.

Usage (from any working directory):
    python templates/two_column/validator.py
    python templates/two_column/validator.py --quality m
    python templates/two_column/validator.py --no-render

Output:
    previews/validator_two_column.py
    previews/preview_two_column.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE     = Path(__file__).parent.resolve()   # templates/two_column/
MANIM    = HERE.parent.parent                 # manim/
OUT_DIR  = HERE.parent / "_previews"
HTML_OUT = HERE.parent / "_previews" / "preview_two_column.html"

sys.path.insert(0, str(MANIM))

from templates._validator import build_single_html, render_template   # noqa: E402
from templates.two_column.template import TEMPLATE                     # noqa: E402

FIXTURE: dict = {
    "scene_narration": "Let's contrast legal pawn moves with common illegal ones.",
    "left_header": "Legal Moves",
    "right_header": "Illegal Moves",
    "pairs": [
        {
            "left": "Move forward one square",
            "right": "Move backward",
            "narration": "Pawns advance — retreating is never allowed.",
        },
        {
            "left": "Capture diagonally forward",
            "right": "Capture straight ahead",
            "narration": "Diagonal capture is correct; forward capture is not.",
        },
        {
            "left": "Two squares on first move",
            "right": "Two squares after first move",
            "narration": "The two-square advance is a one-time opening privilege.",
        },
        {
            "left": "Two squares on first move",
            "right": "Two squares after first move",
            "narration": "The two-square advance is a one-time opening privilege.",
        },
        {
            "left": "Two squares on first move",
            "right": "Two squares after first move",
            "narration": "The two-square advance is a one-time opening privilege.",
        },
    ],
    "closing_narration": "Knowing illegal moves is as important as knowing legal ones.",
}


def render(quality: str = "l", dry_run: bool = False) -> tuple[str, Path | None]:
    return render_template(TEMPLATE, FIXTURE, "two_column", quality, dry_run, OUT_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quality", default="l", choices=["l", "m", "h"],
                    help="Manim quality: l=480p (fast, default), m=720p, h=1080p")
    ap.add_argument("--no-render", action="store_true",
                    help="Write .py file only, skip Manim execution")
    args = ap.parse_args()

    print("\n  [two_column]")
    code, video = render(args.quality, args.no_render)
    print(f"    → {(OUT_DIR / 'validator_two_column.py').relative_to(MANIM.parent)}")
    if not args.no_render:
        print(f"    {'✓  ' + video.name if video else '✗  render failed'}")

    HTML_OUT.write_text(build_single_html("two_column", code, video, HTML_OUT.parent),
                        encoding="utf-8")
    print(f"  Report → {HTML_OUT.relative_to(MANIM.parent)}\n")


if __name__ == "__main__":
    main()
