import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from rlo_schema import RLO  # noqa: E402
from schema import (  # noqa: E402
    CompletionScreen,
    ObjectivesScreen,
    ScreenPlan,
    ScreenPlanItem,
    TitleScreen,
)
from service import render_course  # noqa: E402


class FakeSelectionAgent:
    def run(self, rlo, registry):
        return ScreenPlan(
            rlo_id=rlo.id,
            rlo_version=rlo.version,
            screens=[
                ScreenPlanItem(screen_id="title", sequence=1, type="title", rlo_source_refs=["title"]),
                ScreenPlanItem(screen_id="objectives", sequence=2, type="objectives", rlo_source_refs=["enabling_objective"]),
                ScreenPlanItem(screen_id="completion", sequence=3, type="completion", rlo_source_refs=["enabling_objective"]),
            ],
        )


class FakeFittingAgent:
    def run(self, item, rlo, registry):
        base = dict(
            screen_id=item.screen_id,
            sequence=item.sequence,
            rlo_source_refs=item.rlo_source_refs,
        )
        if item.type == "title":
            return TitleScreen(type="title", course_title="Synthetic Course", subtitle="A neutral service test.", hook="What will you discover?", metadata={}, **base)
        if item.type == "objectives":
            return ObjectivesScreen(type="objectives", heading="Objective", objectives=["Explain the concept"], **base)
        return CompletionScreen(type="completion", heading="Complete", message="You reached the end.", skills_reinforced=["Explanation"], **base)


def test_service_renders_without_network_or_filesystem_writes():
    rlo = RLO.model_construct(id="synthetic-rlo", version="1.0.0")
    result = render_course(
        rlo,
        registry=object(),
        selection_agent=FakeSelectionAgent(),
        fitting_agent=FakeFittingAgent(),
        generate_images=False,
    )
    assert result.course.rlo_id == "synthetic-rlo"
    assert len(result.course.screens) == 3
    assert "Synthetic Course" in result.html
    assert result.warnings == []
