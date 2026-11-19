"""Starting proficiency derivation — Phase 12."""
from __future__ import annotations

from learning_pipeline.contracts.common import TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import RLOAssemblyContext
from learning_pipeline.contracts.learner import LearnerContext

PROFICIENCY_POLICY_VERSION = "proficiency_v1"


def derive_starting_proficiency(
    learner: LearnerContext,
    context: RLOAssemblyContext,
) -> tuple[TopicProficiency, str]:
    """Derive starting proficiency and the source used for derivation.

    Resolution order (policy_v1):
      1. Exact topic-specific proficiency from learner.topic_proficiencies
      2. learner.default_proficiency

    Deloitte level does NOT determine proficiency.

    Returns:
        (proficiency, source_label)
        source_label is one of "topic_specific" or "default".
    """
    topic = context.topic
    if topic in learner.topic_proficiencies:
        return learner.topic_proficiencies[topic], "topic_specific"
    return learner.default_proficiency, "default"
