#!/usr/bin/env python3
"""Standalone validator for the central_callouts template.

Usage (from any working directory):
    python templates/central_callouts/validator.py
    python templates/central_callouts/validator.py --quality m
    python templates/central_callouts/validator.py --no-render

Output:
    previews/validator_central_callouts.py
    previews/preview_central_callouts.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE     = Path(__file__).parent.resolve()   # templates/central_callouts/
MANIM    = HERE.parent.parent                 # manim/
OUT_DIR  = HERE.parent / "_previews"
HTML_OUT = HERE.parent / "_previews" / "preview_central_callouts.html"

sys.path.insert(0, str(MANIM))

from templates._validator import build_single_html, render_template    # noqa: E402
from templates.central_callouts.template import TEMPLATE               # noqa: E402

FIXTURE: dict = {
    "scene_narration": "Every pawn rule radiates from a single core idea.",
    "center_label": "Pawn Rules",
    "center_narration": "All pawn behaviour stems from its permanently forward-facing nature.",
    "callouts": [
        {
            "label": "Always forward",
            "narration": "Pawns never retreat — advancing is the only direction.",
        },
        {
            "label": "One-square limit",
            "narration": "Standard moves advance exactly one square at a time.",
        },
        {
            "label": "Opening two-step",
            "narration": "The initial two-square option gives early flexibility.",
        },
        {
            "label": "Diagonal capture",
            "narration": "Captures happen diagonally, creating attack angles.",
        },
        {
            "label": "Diagonal capture",
            "narration": "Captures happen diagonally, creating attack angles.",
        },
        {
            "label": "Diagonal capture",
            "narration": "Captures happen diagonally, creating attack angles.",
        },
        {
            "label": "Diagonal capture",
            "narration": "Captures happen diagonally, creating attack angles.",
        },
        {
            "label": "Diagonal capture",
            "narration": "Captures happen diagonally, creating attack angles.",
        },
    ],
    "closing_narration": "These four properties make the pawn deceptively powerful.",
}


def render(quality: str = "l", dry_run: bool = False) -> tuple[str, Path | None]:
    return render_template(TEMPLATE, FIXTURE, "central_callouts", quality, dry_run, OUT_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quality", default="l", choices=["l", "m", "h"],
                    help="Manim quality: l=480p (fast, default), m=720p, h=1080p")
    ap.add_argument("--no-render", action="store_true",
                    help="Write .py file only, skip Manim execution")
    args = ap.parse_args()

    print("\n  [central_callouts]")
    code, video = render(args.quality, args.no_render)
    print(f"    → {(OUT_DIR / 'validator_central_callouts.py').relative_to(MANIM.parent)}")
    if not args.no_render:
        print(f"    {'✓  ' + video.name if video else '✗  render failed'}")

    HTML_OUT.write_text(build_single_html("central_callouts", code, video, HTML_OUT.parent),
                        encoding="utf-8")
    print(f"  Report → {HTML_OUT.relative_to(MANIM.parent)}\n")


if __name__ == "__main__":
    main()
