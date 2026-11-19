#!/usr/bin/env python3
"""Standalone validator for the vertical_stack template.

Usage (from any working directory):
    python templates/vertical_stack/validator.py
    python templates/vertical_stack/validator.py --quality m
    python templates/vertical_stack/validator.py --no-render

Output:
    previews/validator_vertical_stack.py
    previews/preview_vertical_stack.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE     = Path(__file__).parent.resolve()   # templates/vertical_stack/
MANIM    = HERE.parent.parent                 # manim/
OUT_DIR  = HERE.parent / "_previews"
HTML_OUT = HERE.parent / "_previews" / "preview_vertical_stack.html"

sys.path.insert(0, str(MANIM))

from templates._validator import build_single_html, render_template   # noqa: E402
from templates.vertical_stack.template import TEMPLATE                # noqa: E402

FIXTURE: dict = {
    "scene_narration": "Let's explore the four core rules that define pawn movement.",
    "title": "Pawn Movement Rules",
    "items": [
        {
            "label": "Always moves forward",
            "detail": "Pawns can never retreat — forward only.",
            "narration": "A pawn can only ever advance toward the opponent's side.",
        },
        {
            "label": "One square per turn",
            "detail": "After the first move, one square at a time.",
            "narration": "Once a pawn has moved, it is limited to a single square each turn.",
        },
        {
            "label": "Two squares on first move",
            "detail": "From its starting rank, may advance two squares.",
            "narration": "On its very first move a pawn may leap two squares forward.",
        },
        {
            "label": "Captures diagonally",
            "detail": "Takes enemy pieces one square diagonally forward.",
            "narration": "To capture, a pawn moves one square diagonally — never straight ahead.",
        },
    ],
    "closing_narration": "These four rules define everything a pawn can do.",
}


def render(quality: str = "l", dry_run: bool = False) -> tuple[str, Path | None]:
    return render_template(TEMPLATE, FIXTURE, "vertical_stack", quality, dry_run, OUT_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quality", default="l", choices=["l", "m", "h"],
                    help="Manim quality: l=480p (fast, default), m=720p, h=1080p")
    ap.add_argument("--no-render", action="store_true",
                    help="Write .py file only, skip Manim execution")
    args = ap.parse_args()

    print("\n  [vertical_stack]")
    code, video = render(args.quality, args.no_render)
    print(f"    → {(OUT_DIR / 'validator_vertical_stack.py').relative_to(MANIM.parent)}")
    if not args.no_render:
        print(f"    {'✓  ' + video.name if video else '✗  render failed'}")

    HTML_OUT.write_text(build_single_html("vertical_stack", code, video, HTML_OUT.parent),
                        encoding="utf-8")
    print(f"  Report → {HTML_OUT.relative_to(MANIM.parent)}\n")


if __name__ == "__main__":
    main()
