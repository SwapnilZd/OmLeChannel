"""Screen planning through the typed selection agent."""

from rlo_schema import RLO

from agents import SelectionAgent
from component_registry import ComponentRegistry
from schema import ScreenPlan


def plan_screens(
    rlo: RLO,
    registry: ComponentRegistry,
    agent: SelectionAgent | None = None,
) -> ScreenPlan:
    return (agent or SelectionAgent()).run(rlo, registry)
