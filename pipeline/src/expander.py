"""Screen expansion through the typed fitting agent."""

from rlo_schema import RLO

from agents import FittingAgent
from component_registry import ComponentRegistry
from schema import ScreenContent, ScreenPlanItem


def expand_screen(
    plan_item: ScreenPlanItem,
    rlo: RLO,
    registry: ComponentRegistry,
    agent: FittingAgent | None = None,
) -> ScreenContent:
    return (agent or FittingAgent()).run(plan_item, rlo, registry)
