"""
ToolManifest — planner-safe description of a production capability.

A manifest contains everything a Workflow Planner needs to understand what a
capability can do and what data it exchanges.  It contains no secrets,
provider credentials, executor instances, or environment-specific URLs.

Input/output JSON schemas are derived from typed Pydantic models so they
cannot drift from the executable contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from learning_pipeline.contracts.common import FrozenModel, Modality


class ToolManifest(FrozenModel):
    """Planner-safe capability description.

    The ``input_schema`` and ``output_schema`` fields should be generated via
    ``MyModel.model_json_schema()`` so they remain in sync with the contracts.
    """

    capability: str
    """Provider-neutral capability name, e.g. ``speech.synthesize``."""

    contract_version: str
    """Semver-style contract version string, e.g. ``"1.0"``."""

    task_type: str
    """Runtime task type registered in the ExecutorRegistry."""

    description: str
    """Human-readable capability description for planner prompts."""

    supported_modalities: tuple[Modality, ...]
    """Modalities this capability can produce output for."""

    input_schema: dict[str, Any]
    """JSON Schema derived from the typed input model."""

    output_schema: dict[str, Any]
    """JSON Schema derived from the typed output model."""

    constraints: dict[str, Any] = {}
    """Optional capability-level constraints for the planner (no credentials)."""


@dataclass(frozen=True)
class ProductionToolDefinition:
    """Binds a planner-safe manifest to typed input/output contracts.

    The executor itself is registered separately in the ExecutorRegistry.
    Keeping the executor out of the definition ensures the catalog stays
    fully planner-safe and serializable.
    """

    manifest: ToolManifest
    input_model: type[BaseModel]
    output_model: type[BaseModel]
