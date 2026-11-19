"""Framework-neutral service entrypoint for RLO-to-course rendering."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel, Field

from llm_gateway import load_lite_llm_settings

from rlo_schema import RLO

from agents import FittingAgent, SelectionAgent
from component_registry import ComponentRegistry
from image_generator import generate_image
from renderer import render_course_html
from schema import CourseContent, ScreenPlan


class RenderResult(BaseModel):
    plan: ScreenPlan
    course: CourseContent
    html: str
    warnings: list[str] = Field(default_factory=list)


ImageGenerator = Callable[[str, str, str, str], str | None]


def _default_registry() -> ComponentRegistry:
    connection = load_lite_llm_settings(required=False)
    return ComponentRegistry(
        qdrant_url=os.environ.get("QDRANT_URL", "http://qdrant:6333"),
        litellm_base_url=connection.base_url,
        litellm_api_key=connection.api_key,
    )


def render_course(
    rlo: RLO,
    *,
    theme: str = "deloitte-green",
    registry: ComponentRegistry | None = None,
    selection_agent: SelectionAgent | None = None,
    fitting_agent: FittingAgent | None = None,
    generate_images: bool = True,
    image_generator: ImageGenerator = generate_image,
) -> RenderResult:
    """Plan, fit, validate, and render one RLO without filesystem or CLI assumptions."""
    registry = registry or _default_registry()
    selection_agent = selection_agent or SelectionAgent()
    fitting_agent = fitting_agent or FittingAgent()

    plan = selection_agent.run(rlo, registry)
    print(f"[service] Selected {len(plan.screens)} screens")
    screens = []
    for item in plan.screens:
        print(f"[service] Fitting {item.sequence}/{len(plan.screens)}: {item.type}")
        screens.append(fitting_agent.run(item, rlo, registry))
    warnings: list[str] = []

    if generate_images:
        connection = load_lite_llm_settings(required=False)
        for screen in screens:
            if not screen.image_prompt:
                continue
            path = image_generator(
                screen.image_prompt,
                screen.screen_id,
                connection.base_url,
                connection.api_key,
            )
            screen.image_path = path
            if path is None:
                warnings.append(f"Image generation failed for {screen.screen_id}; used fallback styling.")

    course = CourseContent(
        rlo_id=rlo.id,
        rlo_version=rlo.version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        theme_id=theme,
        screens=screens,
    )
    return RenderResult(
        plan=plan,
        course=course,
        html=render_course_html(course, theme_id=theme),
        warnings=warnings,
    )
