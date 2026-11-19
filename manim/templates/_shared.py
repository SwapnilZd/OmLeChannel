"""Shared palette, accent list, and string utilities used by all template modules."""
from __future__ import annotations

# Embedded verbatim into every generated Manim file.
# Values mirror brand/deloitte.yaml (enforced by test_brand_consistency.py).
# Light theme: white background (matching the Deloitte deck content-slide
# aesthetic and the light e-learning HTML theme the videos embed into), dark
# ink, DEEP_GREEN headings, and dark-end accents that hold ≥3:1 contrast on
# white. FUNCTIONAL_RED is a Deloitte limited-use functional color: it
# requires a functional association (marking a wrong answer or misconception)
# and is used sparingly — icons and strokes only, never body text or fills.
_PALETTE_BLOCK = """\
# Deloitte palette
DELOITTE_GREEN      = "#86BC25"
MID_GREEN           = "#26890D"
DEEP_GREEN          = "#046A38"
DARK_GREEN          = "#1C3D26"
DELOITTE_DARK_GRAY  = "#222222"
DELOITTE_LIGHT_GRAY = "#E6E6E6"
DELOITTE_WHITE      = "#FFFFFF"
GREEN_2  = "#C4D600";  GREEN_4 = "#43B02A";  GREEN_5 = "#009A44"
TEAL_3   = "#6FC2B4";  TEAL_4  = "#00ABAB";  TEAL_6  = "#007680"
BLUE_2   = "#62B5E5";  BLUE_3  = "#00A3E0";  BLUE_4  = "#0076A8"
COOL_GRAY_7 = "#97999B";  COOL_GRAY_9 = "#75787B"
CARD_BG     = "#F7F7F7"
FUNCTIONAL_RED = "#DA291C"
config.background_color = DELOITTE_WHITE
FONT = "Open Sans"\
"""

# Accent colors cycled across multi-item visuals. Leads with green to satisfy
# the brand's green code; restricted to the palette's dark end so strokes and
# accent text keep WCAG-viable contrast on the white background.
_ACCENT = ["MID_GREEN", "TEAL_6", "BLUE_4", "GREEN_5", "DEEP_GREEN", "DARK_GREEN"]

# Embedded verbatim into every generated Manim file, after the palette block.
# Animations take a bounded share of the narration time instead of stretching
# to fill it — long narration holds a finished visual, never a slow-motion play.
_RT_BLOCK = '''\
def _rt(d, frac, lo, hi):
    """Bounded share of narration duration d for one animation stage."""
    return max(lo, min(hi, d * frac))\
'''

# Embedded verbatim after _RT_BLOCK. Spatial counterpart of _rt: every text
# with a width slot is clamped so measured Pango width can never escape its
# card, box, hub, or the frame — char caps alone don't bound rendered pixels.
_FIT_BLOCK = '''\
def _fit(m, w):
    """Downscale m to fit width w — never upscales."""
    if m.width > w:
        m.scale_to_fit_width(w)
    return m\
'''

# Max width for scene titles (frame is 14.22 wide; keep breathing room).
_TITLE_MAX_W = 13.0

# Per-beat narration word budgets (~2.5 spoken words per second of TTS).
_OPENER_WORDS  = 25   # opener / title beat (~10 s)
_ITEM_WORDS    = 45   # per-item reveal (~18 s) — these carry the teaching load
_CLOSING_WORDS = 30   # closing beat (~12 s)


def _esc(s: str) -> str:
    """Escape for embedding inside a Python double-quoted string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _check_text(field: str, text: object, cap: int) -> str:
    """Reject visible text grossly over its slot's length cap — never truncate.

    Mild overage (≤1.5× cap) passes through unchanged: the generated scene's
    _fit clamp absorbs it by shrinking. Beyond that, shrinking would be
    illegible, so the raise feeds the controller's bounded LLM repair loop —
    the same policy _check_narration applies to spoken text.
    """
    text = str(text)
    if len(text) > int(cap * 1.5):
        raise ValueError(
            f"{field}: text is {len(text)} chars but this slot fits ~{cap} "
            f"(hard cap {int(cap * 1.5)}). Shorten it."
        )
    return text


def _wc(s: str) -> int:
    return len(str(s).split())


def _check_narration(field: str, text: str, budget: int) -> None:
    """Reject narration grossly over its beat budget — never truncate speech.

    The raise feeds the controller's bounded LLM repair loop; a mid-sentence
    TTS cut would be worse than one repair round.
    """
    words = _wc(text)
    if words > 2 * budget:
        raise ValueError(
            f"{field}: narration is {words} words but this beat's budget is "
            f"~{budget} (hard cap {2 * budget}). Shorten it or move content "
            f"into other beats."
        )


def _elements_block(scene: dict) -> str:
    lines = []
    for i, e in enumerate(scene.get("elements", []), 1):
        lines.append(f'  [{i}] label: "{e["label"]}"')
        lines.append(f'       narration: "{e["narration"]}"')
    return "\n".join(lines)
