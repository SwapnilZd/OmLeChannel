"""
Slot-based Manim scene templates.

Public API (unchanged from the old templates.py):
    from templates import REGISTRY, TEMPLATE_SYSTEM, Template

Architecture:
  - LLM fills a small typed JSON schema (labels + narration) via fill_prompt.
  - validate() enforces length limits and item counts before rendering.
  - render() returns a complete runnable Python file; it owns all coordinate math.

Adding a new template:
  1. Create manim/templates/<name>/  with layout.py and template.py.
  2. Define TEMPLATE = Template(...) at the bottom of template.py.
  3. Import it here and add it to REGISTRY.
"""
from __future__ import annotations

from ._types import Template  # re-exported for callers

TEMPLATE_SYSTEM = (
    "You extract scene plan content into a typed JSON schema for a Manim template. "
    "Return ONLY valid JSON matching the schema exactly — no extra keys, no comments, "
    "no markdown fences."
)

from .vertical_stack.template   import TEMPLATE as _vs    # noqa: E402
from .central_callouts.template import TEMPLATE as _cc    # noqa: E402
from .two_column.template       import TEMPLATE as _tc    # noqa: E402
from .chess_board.template      import TEMPLATE as _cb    # noqa: E402
from .myth_vs_reality.template  import TEMPLATE as _mvr   # noqa: E402
from .scenario.template         import TEMPLATE as _sc    # noqa: E402
from .definition.template       import TEMPLATE as _dfn   # noqa: E402
from .pyramid.template          import TEMPLATE as _py    # noqa: E402
from .timeline.template         import TEMPLATE as _tl    # noqa: E402
from .process_flow.template     import TEMPLATE as _pf    # noqa: E402
from .cycle.template            import TEMPLATE as _cy    # noqa: E402
from .quadrant.template         import TEMPLATE as _qd    # noqa: E402

REGISTRY: dict[str, Template] = {
    "vertical_stack":   _vs,
    "central_callouts": _cc,
    "two_column":       _tc,
    "chess_board":      _cb,
    "myth_vs_reality":  _mvr,
    "scenario":         _sc,
    "definition":       _dfn,
    "pyramid":          _py,
    "timeline":         _tl,
    "process_flow":     _pf,
    "cycle":            _cy,
    "quadrant":         _qd,
}
