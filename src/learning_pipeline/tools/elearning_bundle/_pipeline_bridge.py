"""Bridge module: imports pipeline/src/renderer and pipeline/src/schema.

The pipeline project (pipeline/src/) is not an installed Python package.
This module adds pipeline/src to sys.path exactly once so that the renderer
and schema can be imported without polluting the packaging contract.

Only import this module from executors that need to render HTML or parse
CourseContent.  Do not import it at module definition time in contracts or
validators to keep those modules free of the path side-effect.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PIPELINE_SRC = (
    Path(__file__).resolve()
    .parent  # elearning_bundle/
    .parent  # tools/
    .parent  # learning_pipeline/
    .parent  # src/
    .parent  # repo root
    / "pipeline"
    / "src"
)

if not _PIPELINE_SRC.is_dir():
    raise ImportError(
        f"pipeline/src not found at {_PIPELINE_SRC}. "
        "Ensure the repository layout has pipeline/ at the repo root."
    )

_path_str = str(_PIPELINE_SRC)
if _path_str not in sys.path:
    sys.path.insert(0, _path_str)

# These imports must come after the sys.path mutation above.
from renderer import render_course_html as _render_course_html  # noqa: E402
from schema import (  # noqa: E402
    CourseContent,
    VideoPlayerScreen,
    VideoSlotScreen,
)

__all__ = [
    "render_course_html",
    "CourseContent",
    "VideoPlayerScreen",
    "VideoSlotScreen",
]


def render_course_html(course: "CourseContent", theme_id: str = "deloitte-green") -> str:
    """Thin wrapper that delegates to pipeline's deterministic renderer."""
    return _render_course_html(course, theme_id=theme_id)
