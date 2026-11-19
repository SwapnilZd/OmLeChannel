#!/usr/bin/env python3
"""
Central validator — renders all templates with fixture data (no LLM, no TTS).

Delegates to per-template validators; each template owns its own fixture.

Usage:
    python templates/validate_all.py                        # render all templates
    python templates/validate_all.py --template chess_board # one template only
    python templates/validate_all.py --list                 # list available templates
    python templates/validate_all.py --no-render            # write .py files only, skip manim
    python templates/validate_all.py --quality m            # m=720p, h=1080p (default: l=480p)

After rendering, open  manim/previews/preview.html  in a browser.

Tuning loop for a single template:
    cd manim/templates/<name>
    python validator.py          # edit layout.py → re-run → refresh previews/preview_<name>.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE  = Path(__file__).parent.resolve()   # manim/templates/
MANIM = HERE.parent                        # manim/

sys.path.insert(0, str(MANIM))

from templates import REGISTRY                                          # noqa: E402
from templates._validator import build_html, render_template            # noqa: E402
from templates.vertical_stack.validator   import FIXTURE as _vs_fix    # noqa: E402
from templates.central_callouts.validator import FIXTURE as _cc_fix    # noqa: E402
from templates.two_column.validator       import FIXTURE as _tc_fix    # noqa: E402
from templates.chess_board.validator      import FIXTURE as _cb_fix    # noqa: E402
from templates.myth_vs_reality.validator  import FIXTURE as _mvr_fix   # noqa: E402
from templates.scenario.validator         import FIXTURE as _sc_fix    # noqa: E402

FIXTURES: dict[str, dict] = {
    "vertical_stack":   _vs_fix,
    "central_callouts": _cc_fix,
    "two_column":       _tc_fix,
    "chess_board":      _cb_fix,
    "myth_vs_reality":  _mvr_fix,
    "scenario":         _sc_fix,
}

PREVIEW_DIR = HERE / "_previews"
HTML_OUT    = HERE / "_previews" / "preview.html"


def render_one(name: str, quality: str = "l", dry_run: bool = False) -> tuple[str, Path | None]:
    return render_template(REGISTRY[name], FIXTURES[name], name, quality, dry_run, PREVIEW_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", choices=list(REGISTRY),
                    help="Render a single template (default: all)")
    ap.add_argument("--quality", default="l", choices=["l", "m", "h"],
                    help="Manim quality: l=480p (fast, default), m=720p, h=1080p")
    ap.add_argument("--no-render", action="store_true",
                    help="Write .py files to preview/ but skip Manim execution")
    ap.add_argument("--list", action="store_true", dest="list_only",
                    help="Print available template names and exit")
    args = ap.parse_args()

    if args.list_only:
        for n in REGISTRY:
            print(f"  ✓  {n}")
        return

    names = [args.template] if args.template else list(REGISTRY)

    results: list[tuple[str, str, Path | None]] = []
    for name in names:
        print(f"\n  [{name}]")
        code, video = render_one(name, quality=args.quality, dry_run=args.no_render)
        py = PREVIEW_DIR / f"validator_{name}.py"
        print(f"    → {py.relative_to(MANIM.parent)}")
        if not args.no_render:
            print(f"    {'✓  ' + video.name if video else '✗  render failed'}")
        results.append((name, code, video))

    HTML_OUT.write_text(build_html(results, HTML_OUT.parent), encoding="utf-8")
    print(f"\n  Report → {HTML_OUT.relative_to(MANIM.parent)}")
    print("  Open that file in a browser to view the previews.\n")


if __name__ == "__main__":
    main()
