"""brand/deloitte.yaml ↔ manim/templates/_shared.py consistency.

The yaml is the declared source of truth for Deloitte brand tokens; the manim
palette block mirrors it by hand. This test makes the mirror real: editing
either side without the other fails here.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from learning_pipeline.tools.manim_video._manim_bridge import _MANIM_ROOT

_BRAND_YAML = _MANIM_ROOT.parent / "brand" / "deloitte.yaml"
_SHARED_PY = _MANIM_ROOT / "templates" / "_shared.py"

# palette-block constant name → brand yaml key (palette.* unless dotted)
_PALETTE_PAIRS = {
    "DELOITTE_GREEN": "deloitte_green",
    "MID_GREEN": "mid_green",
    "DEEP_GREEN": "deep_green",
    "DARK_GREEN": "dark_green",
    "DELOITTE_DARK_GRAY": "dark_gray",
    "DELOITTE_LIGHT_GRAY": "light_gray",
    "DELOITTE_WHITE": "white",
    "GREEN_2": "green_2",
    "GREEN_4": "green_4",
    "GREEN_5": "green_5",
    "TEAL_3": "teal_3",
    "TEAL_4": "teal_4",
    "TEAL_6": "teal_6",
    "BLUE_2": "blue_2",
    "BLUE_3": "blue_3",
    "BLUE_4": "blue_4",
    "COOL_GRAY_7": "cool_gray_7",
    "COOL_GRAY_9": "cool_gray_9",
    "CARD_BG": "card_bg",
}


def _load_brand() -> dict:
    return yaml.safe_load(_BRAND_YAML.read_text(encoding="utf-8"))


def _shared_constants() -> dict[str, str]:
    """Parse NAME = "#HEX" assignments out of the embedded palette block."""
    source = _SHARED_PY.read_text(encoding="utf-8")
    return dict(re.findall(r'([A-Z_0-9]+)\s*=\s*"(#[0-9A-Fa-f]{6})"', source))


def test_palette_values_match_brand_yaml() -> None:
    brand = _load_brand()["palette"]
    constants = _shared_constants()
    mismatches = {
        const: (constants.get(const), brand.get(key))
        for const, key in _PALETTE_PAIRS.items()
        if constants.get(const, "").upper() != str(brand.get(key, "")).upper()
    }
    assert not mismatches, f"palette drift between _shared.py and brand/deloitte.yaml: {mismatches}"


def test_functional_red_matches_brand_yaml() -> None:
    brand = _load_brand()["functional"]
    constants = _shared_constants()
    assert constants.get("FUNCTIONAL_RED", "").upper() == brand["red"].upper()


def test_accent_cycle_matches_brand_yaml() -> None:
    from learning_pipeline.tools.manim_video import _manim_bridge  # noqa: F401  (sys.path)
    from templates._shared import _ACCENT  # type: ignore[import-not-found]

    brand_cycle = [c.upper() for c in _load_brand()["accent_cycle"]]
    assert [a.upper() for a in _ACCENT] == brand_cycle


def test_accent_cycle_leads_with_green() -> None:
    """Green code: green must be prominent — the first accent is a green."""
    brand_cycle = _load_brand()["accent_cycle"]
    assert "green" in brand_cycle[0], (
        f"accent_cycle must lead with a green (green code); got {brand_cycle[0]!r}"
    )


def test_typography_is_open_sans() -> None:
    brand = _load_brand()["typography"]
    constants_src = _SHARED_PY.read_text(encoding="utf-8")
    assert brand["heading_font"] == "Open Sans"
    assert 'FONT = "Open Sans"' in constants_src


def test_no_off_palette_hex_in_templates() -> None:
    """Template renderers must use named palette constants, not raw hex codes.

    layout.py files may hold geometry only; pyramid's band colors are the one
    sanctioned literal list and must stay within the brand palette.
    """
    brand = _load_brand()
    allowed = {str(v).upper() for v in brand["palette"].values()}
    allowed |= {str(v).upper() for v in brand["functional"].values()}

    offenders: list[str] = []
    for template_file in sorted((_MANIM_ROOT / "templates").rglob("*.py")):
        if template_file.name == "_shared.py":
            continue
        if "_previews" in template_file.parts:  # generated artifacts, not source
            continue
        for hex_code in re.findall(r'"(#[0-9A-Fa-f]{6})"', template_file.read_text(encoding="utf-8")):
            if hex_code.upper() not in allowed:
                offenders.append(f"{template_file.relative_to(_MANIM_ROOT)}: {hex_code}")
    assert not offenders, f"off-palette hex literals in templates: {offenders}"
