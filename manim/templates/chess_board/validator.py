#!/usr/bin/env python3
"""Standalone validator for the chess_board template.

Usage (from any working directory):
    python templates/chess_board/validator.py
    python templates/chess_board/validator.py --quality m
    python templates/chess_board/validator.py --no-render

Output:
    previews/validator_chess_board.py
    previews/preview_chess_board.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE     = Path(__file__).parent.resolve()   # templates/chess_board/
MANIM    = HERE.parent.parent                 # manim/
OUT_DIR  = HERE.parent / "_previews"
HTML_OUT = HERE.parent / "_previews" / "preview_chess_board.html"

sys.path.insert(0, str(MANIM))

from templates._validator import build_single_html, render_template   # noqa: E402
from templates.chess_board.template import TEMPLATE                    # noqa: E402

FIXTURE: dict = {
    "scene_narration": "Here is a white pawn on its starting square, e2.",
    "title": "Pawn Starting Position",
    "initial_pieces": [
        {"symbol": "♙", "file": "e", "rank": 2, "color": "white"},
    ],
    "steps": [
        {
            "narration": "From e2 the pawn can advance one square to e3.",
            "actions": [{"type": "dot", "file": "e", "rank": 3, "color": "green"}],
        },
        {
            "narration": "Or two squares to e4 on its very first move.",
            "actions": [{"type": "dot", "file": "e", "rank": 4, "color": "green"}],
        },
        {
            "narration": "An arrow shows the full two-square option.",
            "actions": [
                {
                    "type": "arrow",
                    "file": "e", "rank": 2,
                    "to_file": "e", "to_rank": 4,
                    "color": "green",
                }
            ],
        },
    ],
    "closing_narration": "The pawn's starting options set the tone for the opening.",
}


def render(quality: str = "l", dry_run: bool = False) -> tuple[str, Path | None]:
    return render_template(TEMPLATE, FIXTURE, "chess_board", quality, dry_run, OUT_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quality", default="l", choices=["l", "m", "h"],
                    help="Manim quality: l=480p (fast, default), m=720p, h=1080p")
    ap.add_argument("--no-render", action="store_true",
                    help="Write .py file only, skip Manim execution")
    args = ap.parse_args()

    print("\n  [chess_board]")
    code, video = render(args.quality, args.no_render)
    print(f"    → {(OUT_DIR / 'validator_chess_board.py').relative_to(MANIM.parent)}")
    if not args.no_render:
        print(f"    {'✓  ' + video.name if video else '✗  render failed'}")

    HTML_OUT.write_text(build_single_html("chess_board", code, video, HTML_OUT.parent),
                        encoding="utf-8")
    print(f"  Report → {HTML_OUT.relative_to(MANIM.parent)}\n")


if __name__ == "__main__":
    main()
