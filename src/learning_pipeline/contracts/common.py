from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Modality(StrEnum):
    VIDEO = "video"
    PODCAST = "podcast"
    ELEARNING = "elearning"


class TopicProficiency(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ContentDepth(StrEnum):
    SUMMARY = "summary"
    WORKING = "working"
    COMPREHENSIVE = "comprehensive"


PROFICIENCY_ORDER: dict[TopicProficiency, int] = {
    TopicProficiency.BEGINNER: 0,
    TopicProficiency.INTERMEDIATE: 1,
    TopicProficiency.ADVANCED: 2,
}


class LiteralInput(FrozenModel):
    kind: Literal["literal"] = "literal"
    value: Any


class TaskOutputInput(FrozenModel):
    kind: Literal["task_output"] = "task_output"
    task_id: str
    output_key: str


class ListInput(FrozenModel):
    """Composite binding: resolves to a list by recursively resolving each item."""

    kind: Literal["list"] = "list"
    items: tuple[InputBinding, ...]


class ObjectInput(FrozenModel):
    """Composite binding: resolves to a dict by recursively resolving each field."""

    kind: Literal["object"] = "object"
    fields: dict[str, InputBinding]


InputBinding = Annotated[
    LiteralInput | TaskOutputInput | ListInput | ObjectInput,
    Field(discriminator="kind"),
]

# Rebuild models that reference InputBinding forward — required by Pydantic v2
# when from __future__ import annotations defers annotation evaluation.
_ns = {"InputBinding": InputBinding}
ListInput.model_rebuild(_types_namespace=_ns)
ObjectInput.model_rebuild(_types_namespace=_ns)
