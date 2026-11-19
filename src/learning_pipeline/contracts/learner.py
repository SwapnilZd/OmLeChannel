from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FrozenModel, TopicProficiency


class LearnerContext(FrozenModel):
    """
    Learner profile at the time a course is commissioned.

    Organisational level, per-topic proficiency, and instructional depth are
    independent axes — a senior practitioner may be a beginner on a new topic.
    """

    role: str
    deloitte_level: Literal[25, 35, 45, 55, 65] | None = None
    default_proficiency: TopicProficiency
    topic_proficiencies: dict[str, TopicProficiency] = Field(default_factory=dict)
    goals: tuple[str, ...]
    duration_limit_minutes: int | None = None
    business_context: dict[str, str] = Field(default_factory=dict)
