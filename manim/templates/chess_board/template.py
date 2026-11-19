"""chess_board — fixed 8×8 board; LLM supplies piece positions and per-step indicator actions."""
from __future__ import annotations

import textwrap

from .._shared import (
    _CLOSING_WORDS, _FIT_BLOCK, _ITEM_WORDS, _OPENER_WORDS,
    _PALETTE_BLOCK, _RT_BLOCK, _TITLE_MAX_W, _check_narration, _check_text,
    _elements_block, _esc,
)
from .._types import Template
from .board import board_lines, ind_line, step_block
from .layout import CB_PIECE_F, CB_TITLE_SZ, CB_TITLE_X, CB_TITLE_Y

_SCHEMA = """\
{
  "scene_narration": "spoken as board and initial pieces appear, max ~45 words",
  "title": "optional scene title, max 50 chars, or empty string",
  "initial_pieces": [
    {"symbol": "♙", "file": "e", "rank": 2, "color": "white"}
  ],
  "steps": [
    {
      "narration": "1-2 sentences for this animation step, max ~45 words",
      "actions": [
        {
          "type": "dot|ring|cross|arrow|highlight|move",
          "file": "e", "rank": 4,
          "to_file": "e", "to_rank": 5,
          "color": "green"
        }
      ]
    }
  ],
  "closing_narration": "1-2 sentence closer, max ~30 words"
}
Action types: dot=legal-move dot, ring=capture ring, cross=blocked cross,
arrow=direction arrow (needs to_file/to_rank), highlight=square highlight,
move=physically move piece (needs to_file/to_rank). color: "green" or "red"."""

_VALID_FILES   = set("abcdefgh")
_VALID_SYMBOLS = set("♙♟♘♞♗♝♖♜♕♛♔♚")
_VALID_IND     = {"dot", "ring", "cross", "arrow", "highlight", "move"}


# ── Validators ─────────────────────────────────────────────────────────────────

def _to_rank(val: object) -> int | None:
    """Coerce to int rank 1–8, or None if invalid."""
    try:
        r = int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return r if 1 <= r <= 8 else None


def _clean_piece(p: dict) -> dict | None:
    f = str(p.get("file", "")).lower()
    r = _to_rank(p.get("rank"))
    if f not in _VALID_FILES or r is None:
        return None
    sym = str(p.get("symbol", "♙"))
    return {"symbol": sym if sym in _VALID_SYMBOLS else "♙",
            "file": f, "rank": r, "color": str(p.get("color", "white"))}


def _clean_action(a: dict) -> dict | None:
    f  = str(a.get("file", "")).lower()
    r  = _to_rank(a.get("rank"))
    if f not in _VALID_FILES or r is None:
        return None
    t  = str(a.get("type", "dot"))
    tf = str(a.get("to_file", "")).lower()
    tr = _to_rank(a.get("to_rank"))
    needs_dest = t in {"arrow", "move"}
    if needs_dest and (tf not in _VALID_FILES or tr is None):
        return None
    return {"type":    t if t in _VALID_IND else "dot",
            "file": f, "rank": r,
            "to_file": tf if tf in _VALID_FILES else f,
            "to_rank": tr if tr is not None else r,
            "color":   str(a.get("color", "green"))}


# ── Public interface ───────────────────────────────────────────────────────────

def fill_prompt(scene: dict) -> str:
    return textwrap.dedent(f"""\
        Map this chess scene to the chess_board template schema.

        initial_pieces: all pieces visible at the START (before any animations).
        steps: one per element — each describes what annotations/moves appear with that narration.

        Piece symbols — White: ♙pawn ♘knight ♗bishop ♖rook ♕queen ♔king
                        Black: ♟pawn ♞knight ♝bishop ♜rook ♛queen ♚king

        Scene title: {scene["title"]}
        Opener narration: {scene["scene_narration"]}
        Elements (each becomes one step):
        {_elements_block(scene)}
        Closing narration: {scene["closing_narration"]}

        Return this exact JSON schema:
        {_SCHEMA}
    """)


def validate(data: dict) -> dict:
    seen: set[str] = set()
    pieces = []
    for p in data.get("initial_pieces", []):
        c = _clean_piece(p)
        if c and (sq := f"{c['file']}{c['rank']}") not in seen:
            seen.add(sq)
            pieces.append(c)
    data["initial_pieces"] = pieces
    data["steps"] = [
        {"narration": str(s.get("narration", "")),
         "actions": [c for a in s.get("actions", []) if (c := _clean_action(a))]}
        for s in data.get("steps", [])
    ]
    for i, s in enumerate(data["steps"]):
        _check_narration(f"steps[{i}].narration", s["narration"], _ITEM_WORDS)
    data["title"]             = _check_text("title", data.get("title", ""), 50)
    data["scene_narration"]   = str(data.get("scene_narration", ""))
    data["closing_narration"] = str(data.get("closing_narration", ""))
    # Board setup narrates over an elastic multi-piece reveal — item budget, not opener.
    _check_narration("scene_narration",   data["scene_narration"],   _ITEM_WORDS)
    _check_narration("closing_narration", data["closing_narration"], _CLOSING_WORDS)
    return data


def render(data: dict, scene_id: str, tts_import: str, service_call: str) -> str:
    pieces_data = data["initial_pieces"]
    steps       = data["steps"]
    title_text  = data.get("title", "").strip()

    L: list[str] = [
        "from manim import *", "from manim_voiceover import VoiceoverScene",
        "import numpy as np", tts_import, "", _PALETTE_BLOCK, "", _RT_BLOCK, "",
        _FIT_BLOCK, "",
        f"class Scene_{scene_id}(VoiceoverScene):",
        "    def construct(self):",
        f"        self.set_speech_service({service_call})", "",
    ]
    L += board_lines()

    if title_text:
        L += [f'        board_title = _fit(Text("{_esc(title_text)}", font_size={CB_TITLE_SZ},',
              f"                           color=DEEP_GREEN, weight=BOLD, font=FONT), {_TITLE_MAX_W})",
              f"        board_title.move_to(np.array([{CB_TITLE_X}, {CB_TITLE_Y}, 0]))", ""]

    L.append("        pieces = {}")
    for i, p in enumerate(pieces_data):
        is_white = p["color"].lower() == "white"
        color = "DELOITTE_WHITE" if is_white else "DELOITTE_DARK_GRAY"
        L += [f'        p{i} = Text("{p["symbol"]}", font_size=int(SQ*{CB_PIECE_F}), font=FONT, color={color})']
        if is_white:
            # White glyphs need an outline to stay visible on the light squares.
            L.append(f"        p{i}.set_stroke(DELOITTE_DARK_GRAY, width=1.2)")
        L += [f"        p{i}.move_to(sq_center('{p['file']}', {p['rank']}))",
              f"        pieces['{p['file']}{p['rank']}'] = p{i}"]
    L.append("")

    for si, step in enumerate(steps):
        for ai, a in enumerate(step["actions"]):
            if a["type"] != "move":
                c = "MID_GREEN" if a["color"] != "red" else "FUNCTIONAL_RED"
                L.append(ind_line(f"ind_{si}_{ai}", a["type"], c,
                                  a["file"], a["rank"], a["to_file"], a["to_rank"]))
    L.append("")

    L += [f'        with self.voiceover(text="{_esc(data["scene_narration"])}") as tracker:',
          "            rt = _rt(tracker.duration, 0.7, 1.2, 6.0)",
          "            self.play(", "                Create(board_vg), FadeIn(file_labels), FadeIn(rank_labels),"]
    if title_text:
        L.append("                Write(board_title),")
    for i in range(len(pieces_data)):
        L.append(f"                FadeIn(p{i}, scale=0.6),")
    L += [
        "                run_time=rt",
        "            )",
        "            self.wait(max(0.0, tracker.duration - rt))",
        "",
    ]

    for si, step in enumerate(steps):
        L += step_block(si, step)

    L += [f'        with self.voiceover(text="{_esc(data["closing_narration"])}") as tracker:',
          "            self.wait(tracker.duration)"]
    return "\n".join(L)


TEMPLATE = Template(
    name="chess_board",
    fill_prompt=fill_prompt,
    validate=validate,
    render=render,
)
