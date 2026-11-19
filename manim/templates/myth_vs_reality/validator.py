#!/usr/bin/env python3
"""Standalone validator for the myth_vs_reality template.

Usage (from any working directory):
    python templates/myth_vs_reality/validator.py
    python templates/myth_vs_reality/validator.py --quality m
    python templates/myth_vs_reality/validator.py --no-render

Output:
    previews/validator_myth_vs_reality.py
    previews/preview_myth_vs_reality.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE     = Path(__file__).parent.resolve()   # templates/myth_vs_reality/
MANIM    = HERE.parent.parent                 # manim/
OUT_DIR  = HERE.parent / "_previews"
HTML_OUT = HERE.parent / "_previews" / "preview_myth_vs_reality.html"

sys.path.insert(0, str(MANIM))

from templates._validator import build_single_html, render_template    # noqa: E402
from templates.myth_vs_reality.template import TEMPLATE                # noqa: E402

FIXTURE: dict = {
    "scene_narration": "Let's clear up the two most common pawn misconceptions.",
    "title": "Pawn Myths vs Reality",
    "pairs": [
        {
            "misconception": "Pawns can move backward",
            "myth_narration": "Many beginners assume pawns can retreat like other pieces.",
            "correction": "Pawns can only move forward — never backward",
            "correction_narration": "A pawn's direction is permanently fixed toward the opponent.",
        },
        {
            "misconception": "Pawns always capture straight ahead",
            "myth_narration": "It seems natural to capture in the direction you're moving.",
            "correction": "Pawns capture one square diagonally forward",
            "correction_narration": "Pawn captures are diagonal — this creates their unique attack pattern.",
        },
    ],
    "closing_narration": "These two corrections unlock the real strategic value of pawns.",
}


def render(quality: str = "l", dry_run: bool = False) -> tuple[str, Path | None]:
    return render_template(TEMPLATE, FIXTURE, "myth_vs_reality", quality, dry_run, OUT_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quality", default="l", choices=["l", "m", "h"],
                    help="Manim quality: l=480p (fast, default), m=720p, h=1080p")
    ap.add_argument("--no-render", action="store_true",
                    help="Write .py file only, skip Manim execution")
    args = ap.parse_args()

    print("\n  [myth_vs_reality]")
    code, video = render(args.quality, args.no_render)
    print(f"    → {(OUT_DIR / 'validator_myth_vs_reality.py').relative_to(MANIM.parent)}")
    if not args.no_render:
        print(f"    {'✓  ' + video.name if video else '✗  render failed'}")

    HTML_OUT.write_text(build_single_html("myth_vs_reality", code, video, HTML_OUT.parent),
                        encoding="utf-8")
    print(f"  Report → {HTML_OUT.relative_to(MANIM.parent)}\n")


if __name__ == "__main__":
    main()
