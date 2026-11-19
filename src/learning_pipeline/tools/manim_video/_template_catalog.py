"""Canonical Manim template catalog.

ManimTemplateCatalog wraps the existing manim/templates/REGISTRY,
exposing typed metadata (ManimTemplateManifest) for controller use
without importing template code at module load time.

The catalog:
- Searches templates by learning pattern and visual type.
- Validates component bindings via the template's own validate().
- Renders Python source via the template's render() with TTS injected inline.

The render container (manim/Dockerfile) imports templates/ directly
to execute the generated source — this module does not replace that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ManimTemplateManifest:
    """Typed metadata for one Manim template.

    This metadata is used by the controller for search and selection.
    It does NOT contain the rendering implementation.
    """

    template_id: str
    version: str
    title: str
    description: str
    tags: tuple[str, ...]
    supported_patterns: tuple[str, ...]
    min_items: int = 1
    max_items: int = 8
    source_location: str = ""


# ── Hardcoded manifests for all templates ─────────────────────────────────────

_MANIFESTS: dict[str, ManimTemplateManifest] = {
    "vertical_stack": ManimTemplateManifest(
        template_id="vertical_stack",
        version="1.0",
        title="Vertical Stack",
        description="Stacked cards revealed one by one — best for 3–5 enumerated items, steps, or rules.",
        tags=("list", "sequential", "steps", "rules", "enumeration"),
        supported_patterns=("enumerated_list", "steps", "key_points", "rules"),
        min_items=3,
        max_items=5,
        source_location="manim/templates/vertical_stack/",
    ),
    "central_callouts": ManimTemplateManifest(
        template_id="central_callouts",
        version="1.0",
        title="Central Callouts",
        description="Hub-and-spoke diagram with a central concept and radiating callouts (3–8 items).",
        tags=("hub", "radial", "callouts", "concept", "relationships"),
        supported_patterns=("hub_and_spoke", "central_concept", "relationships", "attributes"),
        min_items=3,
        max_items=8,
        source_location="manim/templates/central_callouts/",
    ),
    "two_column": ManimTemplateManifest(
        template_id="two_column",
        version="1.0",
        title="Two Column Comparison",
        description="Side-by-side comparison of 2–6 paired items with a divider.",
        tags=("comparison", "contrast", "before-after", "pros-cons", "two-column"),
        supported_patterns=("comparison", "contrast", "before_after", "pros_cons"),
        min_items=2,
        max_items=6,
        source_location="manim/templates/two_column/",
    ),
    "chess_board": ManimTemplateManifest(
        template_id="chess_board",
        version="1.0",
        title="Chess Board",
        description="8×8 board with animated piece movements — for board position rules or legal moves.",
        tags=("chess", "board", "moves", "positions", "spatial"),
        supported_patterns=("chess_positions", "board_game", "spatial_rules"),
        min_items=2,
        max_items=6,
        source_location="manim/templates/chess_board/",
    ),
    "myth_vs_reality": ManimTemplateManifest(
        template_id="myth_vs_reality",
        version="1.0",
        title="Myth vs Reality",
        description="Myth/correction pairs that reveal the truth (up to 3 pairs).",
        tags=("misconception", "myth", "reality", "correction", "clarification"),
        supported_patterns=("misconception_correction", "myth_busting", "false_vs_true"),
        min_items=1,
        max_items=3,
        source_location="manim/templates/myth_vs_reality/",
    ),
    "scenario": ManimTemplateManifest(
        template_id="scenario",
        version="1.0",
        title="Scenario",
        description="4-element scenario: setup, question, wrong answer, correct answer reveal.",
        tags=("scenario", "decision", "right-wrong", "case-study", "example"),
        supported_patterns=("scenario_decision", "worked_example", "case_study"),
        min_items=4,
        max_items=4,
        source_location="manim/templates/scenario/",
    ),
    "definition": ManimTemplateManifest(
        template_id="definition",
        version="1.0",
        title="Definition",
        description="Large term + formal definition + 2–4 key attributes revealed one by one. For vocabulary, technical terms, and core concepts.",
        tags=("definition", "concept", "term", "vocabulary", "attribute", "breakdown"),
        supported_patterns=("concept_definition", "term_breakdown", "key_attributes", "vocabulary"),
        min_items=2,
        max_items=4,
        source_location="manim/templates/definition/",
    ),
    "pyramid": ManimTemplateManifest(
        template_id="pyramid",
        version="1.0",
        title="Pyramid",
        description="3–5 stacked horizontal bands revealed bottom-up, widest at the base. For hierarchies, foundations, and progressive structures.",
        tags=("pyramid", "hierarchy", "layers", "levels", "foundation", "maslow", "bloom"),
        supported_patterns=("hierarchy", "layered_structure", "foundational_progression", "levels"),
        min_items=3,
        max_items=5,
        source_location="manim/templates/pyramid/",
    ),
    "timeline": ManimTemplateManifest(
        template_id="timeline",
        version="1.0",
        title="Timeline",
        description="Horizontal timeline with 3–5 events/milestones revealed left-to-right. For chronological sequences, project phases, and historical progressions.",
        tags=("timeline", "chronological", "events", "milestones", "history", "phases", "sequence"),
        supported_patterns=("chronological_sequence", "project_phases", "historical_progression", "milestones"),
        min_items=3,
        max_items=5,
        source_location="manim/templates/timeline/",
    ),
    "process_flow": ManimTemplateManifest(
        template_id="process_flow",
        version="1.0",
        title="Process Flow",
        description="3–5 numbered steps in a horizontal row connected by arrows. For procedures, workflows, and cause-and-effect chains.",
        tags=("process", "flow", "steps", "workflow", "procedure", "sequential", "arrows"),
        supported_patterns=("process_steps", "workflow", "procedure", "cause_and_effect", "sequential_flow"),
        min_items=3,
        max_items=5,
        source_location="manim/templates/process_flow/",
    ),
    "cycle": ManimTemplateManifest(
        template_id="cycle",
        version="1.0",
        title="Cycle",
        description="3–5 steps arranged in a circle with directional arrows. For iterative processes, feedback loops, and continuous improvement cycles.",
        tags=("cycle", "loop", "iterative", "circular", "pdca", "feedback", "agile", "continuous"),
        supported_patterns=("iterative_process", "feedback_loop", "continuous_improvement", "lifecycle"),
        min_items=3,
        max_items=5,
        source_location="manim/templates/cycle/",
    ),
    "quadrant": ManimTemplateManifest(
        template_id="quadrant",
        version="1.0",
        title="Quadrant Matrix",
        description="2×2 matrix with axis labels and items in each quadrant, revealed quadrant by quadrant. For prioritization, risk matrices, and effort/impact analysis.",
        tags=("quadrant", "matrix", "2x2", "prioritization", "urgent", "important", "risk", "effort", "impact"),
        supported_patterns=("prioritization_matrix", "risk_matrix", "effort_impact", "two_by_two"),
        min_items=4,
        max_items=4,
        source_location="manim/templates/quadrant/",
    ),
}


class ManimTemplateCatalog:
    """Typed catalog of Manim scene templates.

    The catalog uses lazy imports for the actual template objects
    so that the manim/ bridge is not imported at module load time.
    """

    def __init__(self) -> None:
        self._registry: dict | None = None

    def _load_registry(self) -> dict:
        if self._registry is None:
            from learning_pipeline.tools.manim_video._manim_bridge import REGISTRY
            self._registry = REGISTRY
        return self._registry

    def manifests(self) -> tuple[ManimTemplateManifest, ...]:
        """Return all available template manifests."""
        return tuple(_MANIFESTS.values())

    def get(self, template_id: str) -> ManimTemplateManifest:
        """Return the manifest for a template by ID."""
        try:
            return _MANIFESTS[template_id]
        except KeyError:
            raise KeyError(
                f"Template {template_id!r} not in catalog. "
                f"Available: {sorted(_MANIFESTS)}"
            )

    def validate_bindings(self, template_id: str, bindings: dict[str, Any]) -> dict[str, Any]:
        """Validate component bindings via the template's own validate().

        Returns the normalised (clamped/trimmed) bindings dict.
        """
        registry = self._load_registry()
        if template_id not in registry:
            raise KeyError(
                f"Template {template_id!r} not in REGISTRY. "
                f"Available: {sorted(registry)}"
            )
        return registry[template_id].validate(bindings)

    def render_source(
        self,
        template_id: str,
        bindings: dict[str, Any],
        scene_id: str,
        *,
        tts_import: str = "",
        service_call: str = "",
    ) -> str:
        """Render Python source from a validated template + bindings.

        Pass tts_import and service_call to embed inline TTS into the scene.
        When omitted, the template renders with empty TTS strings (no audio).
        """
        registry = self._load_registry()
        if template_id not in registry:
            raise KeyError(f"Template {template_id!r} not in REGISTRY.")
        validated = registry[template_id].validate(bindings)
        safe_scene_id = scene_id.replace("-", "_")
        return registry[template_id].render(validated, safe_scene_id, tts_import, service_call)
