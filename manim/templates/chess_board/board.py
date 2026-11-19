"""Chess board geometry helpers — board construction lines and indicator/move code generation."""
from __future__ import annotations

from .._shared import _esc
from .layout import CB_COORD_SZ, CB_OFF_X, CB_OFF_Y, CB_SQ


def board_lines() -> list[str]:
    """Return the board-setup code block with current layout constants interpolated."""
    return [
        f"        SQ = {CB_SQ}",
        f"        board_origin = np.array([{CB_OFF_X} * SQ, {CB_OFF_Y} * SQ, 0])", "",
        "        def sq_center(file_char, rank_int):",
        "            f = ord(file_char.lower()) - ord('a')",
        "            r = rank_int - 1",
        "            return board_origin + np.array([(f + 0.5) * SQ, (r + 0.5) * SQ, 0])", "",
        "        board_vg = VGroup()",
        "        for r in range(8):",
        "            for f in range(8):",
        "                sq = Square(side_length=SQ, fill_opacity=1,",
        "                            stroke_width=0.5, stroke_color=DELOITTE_DARK_GRAY)",
        "                sq.set_fill(DELOITTE_LIGHT_GRAY if (f + r) % 2 == 1 else DEEP_GREEN)",
        "                sq.move_to(board_origin + np.array([(f+0.5)*SQ, (r+0.5)*SQ, 0]))",
        "                board_vg.add(sq)",
        f'        file_labels = VGroup(*[Text(ch, font_size={CB_COORD_SZ}, font=FONT, color=COOL_GRAY_9)',
        '            .move_to(board_origin + np.array([(f+0.5)*SQ, -0.25, 0]))',
        '            for f, ch in enumerate("abcdefgh")])',
        f'        rank_labels = VGroup(*[Text(str(r+1), font_size={CB_COORD_SZ}, font=FONT, color=COOL_GRAY_9)',
        '            .move_to(board_origin + np.array([-0.25, (r+0.5)*SQ, 0]))',
        "            for r in range(8)])", "",
    ]


def ind_line(vn: str, t: str, c: str, f: str, r: int, tf: str, tr: int) -> str:
    """Return one indicator variable assignment line."""
    if t == "dot":
        return f"        {vn} = Dot(radius=SQ*0.15, color={c}, fill_opacity=0.8).move_to(sq_center('{f}', {r}))"
    if t == "ring":
        return f"        {vn} = Circle(radius=SQ*0.42, color={c}, stroke_width=4).move_to(sq_center('{f}', {r}))"
    if t == "cross":
        return f"        {vn} = Cross(scale_factor=SQ*0.28, color={c}, stroke_width=3).move_to(sq_center('{f}', {r}))"
    if t == "arrow":
        return f"        {vn} = Arrow(sq_center('{f}', {r}), sq_center('{tf}', {tr}), color={c}, stroke_width=5, buff=SQ*0.3)"
    # highlight
    return f"        {vn} = Square(side_length=SQ, fill_color={c}, fill_opacity=0.3, stroke_width=0).move_to(sq_center('{f}', {r}))"


def mixed_lines(si: int, non_moves: list, moves: list) -> list[str]:
    """Return the animation lines for a step that has both indicators and piece moves.

    Piece moves absorb narration time well (elastic beat) — indicators alone
    are quick reveals. Either way the animation takes a bounded share of the
    narration and the finished position holds for the remainder.
    """
    ind_args = [f"FadeIn(ind_{si}_{ai})" for ai, _ in non_moves]
    L = [f"            _a{si} = [{', '.join(ind_args)}]"]
    for mi, (_, a) in enumerate(moves):
        mv = f"_mv{si}_{mi}"
        L += [
            f"            {mv} = pieces.pop('{a['file']}{a['rank']}', None)",
            f"            if {mv}: _a{si}.append({mv}.animate.move_to(sq_center('{a['to_file']}', {a['to_rank']})))",
        ]
    L += [
        "            rt = _rt(tracker.duration, 0.6, 0.8, 4.0)",
        f"            if _a{si}:",
        f"                self.play(*_a{si}, run_time=rt)",
        "                self.wait(max(0.0, tracker.duration - rt))",
        "            else: self.wait(tracker.duration)",
    ]
    for mi, (_, a) in enumerate(moves):
        L.append(f"            if _mv{si}_{mi}: pieces['{a['to_file']}{a['to_rank']}'] = _mv{si}_{mi}")
    return L


def step_block(si: int, step: dict) -> list[str]:
    """Return the full voiceover + animation block for one narration step."""
    non_moves = [(ai, a) for ai, a in enumerate(step["actions"]) if a["type"] != "move"]
    moves     = [(ai, a) for ai, a in enumerate(step["actions"]) if a["type"] == "move"]
    L = [f'        with self.voiceover(text="{_esc(step["narration"])}") as tracker:']
    if non_moves and not moves:
        args = ", ".join(f"FadeIn(ind_{si}_{ai})" for ai, _ in non_moves)
        L += [
            "            rt = _rt(tracker.duration, 0.4, 0.8, 2.5)",
            f"            self.play({args}, run_time=rt)",
            "            self.wait(max(0.0, tracker.duration - rt))",
        ]
    elif moves or non_moves:
        L += mixed_lines(si, non_moves, moves)
    else:
        L.append("            self.wait(tracker.duration)")
    L.append("")
    return L
