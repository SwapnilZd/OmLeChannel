#!/usr/bin/env python3
"""Layout audit — renders every template's generated scene code with worst-case
(cap-length) bindings and measures REAL Pango text geometry against the frame,
container shapes, and sibling text.

Needs a Manim environment, so it runs inside the renderer container:

    make manim-layout-audit

(or: docker run --rm --entrypoint python3 -w /tmp -v "$PWD":/repo:ro \
     manim-renderer:latest /repo/manim/templates/audit_layout.py)

No TTS, no rendering — VoiceoverScene is stubbed so construct() only builds
and positions mobjects. Checks:

  FRAME-OUT    any mobject outside the 14.22 x 8 frame
  FRAME-TIGHT  Text closer than 0.15 to a frame edge
  BOX-OVERFLOW Text whose center sits inside a Rectangle/Circle but whose
               bbox escapes it (text overflowing its card / box / hub)
  TXT-OVERLAP  two Text bboxes intersecting (label collisions)

Exits 1 if any finding survives, so it can gate CI or a pre-release check.
Deliberately NOT part of the default test suite (needs Docker + Manim).
"""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from templates._geometry import GeometryExecutionError, check_source  # noqa: E402

# Audit thresholds are tighter than the render gate's: templates are ours, so
# even small escapes are regressions worth failing on.
_EDGE_TIGHT = 0.15

_SEED = "Strategic Wording Might Overflow The Allocated Space Here "


def _t(n: int) -> str:
    """Cap-length filler text (mixed-case, realistic glyph widths)."""
    return (_SEED * 8)[:n].rstrip()


def audit(name: str, variant: str, source: str) -> list[dict]:
    try:
        findings = check_source(source, edge_tight=_EDGE_TIGHT)
    except GeometryExecutionError as exc:
        findings = [{"kind": "HARNESS-ERROR", "detail": str(exc)}]
    return [{"template": name, "variant": variant, **f} for f in findings]


def cases():
    """Worst-case bindings per template — strings at their schema caps."""
    yield "vertical_stack", "5-items-max", {
        "scene_narration": "Open.", "title": _t(50),
        "items": [{"label": _t(26), "detail": _t(80), "narration": "n"}] * 5,
        "closing_narration": "Close."}
    for n in (3, 8):
        yield "central_callouts", f"{n}-callouts-max", {
            "scene_narration": "Open.", "center_label": _t(18), "center_narration": "n",
            "callouts": [{"label": _t(20), "narration": "n"}] * n,
            "closing_narration": "Close."}
    for n in (2, 3, 4, 5, 6):
        yield "two_column", f"{n}-pairs-max", {
            "scene_narration": "Open.", "left_header": _t(22), "right_header": _t(22),
            "pairs": [{"left": _t(32), "right": _t(32), "narration": "n"}] * n,
            "closing_narration": "Close."}
    yield "myth_vs_reality", "3-pairs-max", {
        "scene_narration": "Open.", "title": _t(50),
        "pairs": [{"misconception": _t(55), "myth_narration": "n",
                   "correction": _t(55), "correction_narration": "n"}] * 3,
        "closing_narration": "Close."}
    yield "scenario", "max", {
        "scene_narration": "Open.", "setup": _t(55), "setup_narration": "n",
        "question": _t(48), "question_narration": "n",
        "wrong_answer": _t(44), "wrong_narration": "n",
        "correct_answer": _t(44), "correct_narration": "n",
        "closing_narration": "Close."}
    yield "definition", "max", {
        "scene_narration": "Open.", "term": _t(35), "definition": _t(100),
        "definition_narration": "n",
        "attributes": [{"key": _t(18), "value": _t(55), "narration": "n"}] * 4,
        "closing_narration": "Close."}
    yield "definition", "short-definition", {
        "scene_narration": "Open.", "term": "Tax", "definition": "A mandatory charge.",
        "definition_narration": "n",
        "attributes": [{"key": "Type", "value": "Direct", "narration": "n"}] * 2,
        "closing_narration": "Close."}
    for n in (3, 5):
        yield "pyramid", f"{n}-levels-max", {
            "scene_narration": "Open.", "title": _t(50),
            "levels": [{"label": _t(22), "narration": "n"}] * n,
            "closing_narration": "Close."}
    yield "timeline", "5-events-max", {
        "scene_narration": "Open.", "title": _t(50),
        "events": [{"date": _t(18), "label": _t(22), "narration": "n"}] * 5,
        "closing_narration": "Close."}
    yield "process_flow", "5-steps-max", {
        "scene_narration": "Open.", "title": _t(50),
        "steps": [{"label": _t(16), "detail": _t(22), "narration": "n"}] * 5,
        "closing_narration": "Close."}
    for n in (3, 4, 5):
        yield "cycle", f"{n}-steps-max", {
            "scene_narration": "Open.", "title": _t(50),
            "steps": [{"label": _t(16), "narration": "n"}] * n,
            "closing_narration": "Close."}
    yield "quadrant", "max", {
        "scene_narration": "Open.",
        "x_low": _t(15), "x_high": _t(15), "y_low": _t(15), "y_high": _t(15),
        "tl_label": _t(20), "tl_items": [_t(28)] * 3, "tl_narration": "n",
        "tr_label": _t(20), "tr_items": [_t(28)] * 3, "tr_narration": "n",
        "bl_label": _t(20), "bl_items": [_t(28)] * 3, "bl_narration": "n",
        "br_label": _t(20), "br_items": [_t(28)] * 3, "br_narration": "n",
        "closing_narration": "Close."}
    yield "chess_board", "typical", {
        "scene_narration": "Board.", "title": _t(50),
        "initial_pieces": [{"symbol": "♙", "file": f, "rank": 2, "color": "white"}
                           for f in "abcdefgh"]
        + [{"symbol": "♚", "file": "e", "rank": 8, "color": "black"}],
        "steps": [{"narration": "Step.", "actions": [
            {"type": "dot", "file": "d", "rank": 4},
            {"type": "ring", "file": "e", "rank": 5},
            {"type": "cross", "file": "f", "rank": 6},
            {"type": "arrow", "file": "e", "rank": 2, "to_file": "e", "to_rank": 4},
            {"type": "highlight", "file": "a", "rank": 1},
            {"type": "move", "file": "e", "rank": 2, "to_file": "e", "to_rank": 4},
        ]}],
        "closing_narration": "Close."}


def main() -> int:
    findings = []
    n_cases = 0
    for name, variant, data in cases():
        n_cases += 1
        tpl = importlib.import_module(f"templates.{name}.template").TEMPLATE
        validated = tpl.validate(copy.deepcopy(data))
        source = tpl.render(validated, "audit", "", "None")
        try:
            findings += audit(name, variant, source)
        except Exception as exc:  # noqa: BLE001 — report, don't abort the sweep
            findings.append({"template": name, "variant": variant,
                             "kind": "HARNESS-ERROR", "detail": repr(exc)})
    for f in findings:
        print(json.dumps(f))
    print(f"{n_cases} cases audited, {len(findings)} findings", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
