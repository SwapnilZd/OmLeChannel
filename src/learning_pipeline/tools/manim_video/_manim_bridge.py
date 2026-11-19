"""Bridge module: imports the Manim template REGISTRY from manim/.

The manim/ directory is not an installed Python package.
This module adds manim/ to sys.path exactly once so that templates
can be imported without polluting the packaging contract.

Only import this module from components that need template rendering.
Do not import it at module definition time in contracts or validators.
"""
from __future__ import annotations

import sys
from pathlib import Path

_MANIM_ROOT = (
    Path(__file__).resolve()
    .parent   # manim_video/
    .parent   # tools/
    .parent   # learning_pipeline/
    .parent   # src/
    .parent   # repo root
    / "manim"
)

if not _MANIM_ROOT.is_dir():
    raise ImportError(
        f"manim/ not found at {_MANIM_ROOT}. "
        "Ensure the repository layout has manim/ at the repo root."
    )

_path_str = str(_MANIM_ROOT)
if _path_str not in sys.path:
    sys.path.insert(0, _path_str)

# These imports must come after the sys.path mutation above.
from templates import REGISTRY  # noqa: E402

__all__ = ["REGISTRY"]
