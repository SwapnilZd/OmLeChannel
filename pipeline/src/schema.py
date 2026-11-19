"""Presentation contracts produced by the slide pipeline.

The source-of-truth content contract lives in :mod:`rlo_schema`.  This module
contains only plan and rendered-screen models, keeping source content separate
from presentation choices.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator


ScreenType = Literal[
    "title",
    "objectives",
    "concept_flip_card",
    "worked_example",
    "contrast_example",
    "scenario_setup",
    "scenario_branch",
    "scenario_resolution",
    "knowledge_check",
    "completion",
    "process_sequence",
    "misconception_buster",
    "comparison_table",
    "tabbed_content",
    "rule_card",
    "reflection_prompt",
    "key_takeaways",
    "video_player",
    "video_slot",
    "card_grid",
    "callout_focus",
    "structured_list",
    "paired_comparison",
    "disclosure_list",
    "relationship_diagram",
]

SlideCategory = Literal[
    "intro",
    "content",
    "practice",
    "assessment",
    "media",
    "navigation",
    "completion",
]
ContentDensity = Literal["sparse", "balanced", "text_heavy"]
MediaRequirement = Literal["none", "optional", "required"]
SequencePosition = Literal["intro", "middle", "end", "any"]


class SlideNeed(BaseModel):
    """Template-independent description of what one slide must represent."""

    category: SlideCategory
    purpose: str
    content_shape: str
    relationship: str = "none"
    item_count: int | None = Field(default=None, ge=0)
    density: ContentDensity = "balanced"
    estimated_total_chars: int | None = Field(default=None, ge=0)
    interaction_preferences: list[str] = Field(default_factory=list)
    media_requirement: MediaRequirement = "none"
    sequence_position: SequencePosition = "middle"

    def retrieval_text(self) -> str:
        count = f"{self.item_count} items" if self.item_count is not None else "unspecified item count"
        interactions = ", ".join(self.interaction_preferences) or "no interaction preference"
        return (
            f"{self.category} slide for {self.purpose}. Represents {self.content_shape} "
            f"with {self.relationship} relationships, {count}, and {self.density} density. "
            f"Interaction preferences: {interactions}. Media requirement: {self.media_requirement}."
        )


class SlideNeedPlanItem(BaseModel):
    screen_id: str
    sequence: int = Field(ge=1)
    rlo_source_refs: list[str] = Field(min_length=1)
    need: SlideNeed
    content_hints: dict[str, str] | None = None


class SlideNeedsPlan(BaseModel):
    rlo_id: str
    rlo_version: str
    slides: list[SlideNeedPlanItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered_needs(self) -> "SlideNeedsPlan":
        ids = [slide.screen_id for slide in self.slides]
        if len(ids) != len(set(ids)):
            raise ValueError("Slide need IDs must be unique.")
        actual = [slide.sequence for slide in self.slides]
        expected = list(range(1, len(self.slides) + 1))
        if actual != expected:
            raise ValueError(f"Slide need sequences must be consecutive from 1; got {actual}.")
        return self


class TemplateCandidate(BaseModel):
    template_id: str
    variant_id: str = "default"
    score: float | None = None
    retrieval_summary: str
    descriptor: dict[str, Any]


class TemplateChoice(BaseModel):
    sequence: int = Field(ge=1)
    template_id: ScreenType
    variant_id: str = "default"
    rationale: str


class TemplateChoices(BaseModel):
    choices: list[TemplateChoice] = Field(min_length=1)


class ScreenPlanItem(BaseModel):
    screen_id: str
    sequence: int = Field(ge=1)
    type: ScreenType
    rlo_source_refs: list[str] = Field(min_length=1)
    layout_variant: str | None = None
    slide_need: SlideNeed | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    content_hints: dict[str, str] | None = None


class ScreenPlan(BaseModel):
    rlo_id: str
    rlo_version: str
    screens: list[ScreenPlanItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ordered_screens(self) -> "ScreenPlan":
        ids = [screen.screen_id for screen in self.screens]
        if len(ids) != len(set(ids)):
            raise ValueError("Screen IDs must be unique.")
        expected = list(range(1, len(self.screens) + 1))
        actual = [screen.sequence for screen in self.screens]
        if actual != expected:
            raise ValueError(f"Screen sequences must be consecutive from 1; got {actual}.")
        return self


class ScreenBase(BaseModel):
    screen_id: str
    sequence: int = Field(ge=1)
    rlo_source_refs: list[str] = Field(min_length=1)
    layout_variant: str | None = None
    image_prompt: str | None = None
    image_path: str | None = None


class TitleScreen(ScreenBase):
    type: Literal["title"]
    course_title: str
    subtitle: str
    hook: str
    metadata: dict[str, str | int | None]


class ObjectivesScreen(ScreenBase):
    type: Literal["objectives"]
    heading: str
    objectives: list[str]


class FlipCardContent(BaseModel):
    id: str
    front_label: str
    front_teaser: str
    back_definition: str
    back_examples: list[str]
    back_safeguard: str


class ConceptFlipCardScreen(ScreenBase):
    type: Literal["concept_flip_card"]
    section_label: str
    instruction: str
    cards: list[FlipCardContent]


class WorkedExampleScreen(ScreenBase):
    type: Literal["worked_example"]
    title: str
    scenario: str
    analysis: str
    resolution: str
    lesson: str


class ContrastColumn(BaseModel):
    label: str
    description: str
    reason: str


class ContrastExampleScreen(ScreenBase):
    type: Literal["contrast_example"]
    title: str
    acceptable: ContrastColumn
    unacceptable: ContrastColumn


class BranchChoice(BaseModel):
    id: str
    label: str


class ScenarioSetupScreen(ScreenBase):
    type: Literal["scenario_setup"]
    title: str
    setup_text: str
    prompt: str
    branches: list[BranchChoice]


class ScenarioBranchScreen(ScreenBase):
    type: Literal["scenario_branch"]
    branch_id: str
    outcome_type: Literal["correct", "incorrect"]
    feedback_title: str
    feedback_body: str
    resolution_screen_id: str


class ScenarioResolutionScreen(ScreenBase):
    type: Literal["scenario_resolution"]
    title: str
    body: str


class KnowledgeCheckOption(BaseModel):
    id: str
    text: str
    correct: bool
    feedback: str


class KnowledgeCheckQuestion(BaseModel):
    question_id: str
    stem: str
    question_type: Literal["multiple_choice_single", "multiple_choice_multi"]
    options: list[KnowledgeCheckOption] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def validate_answers(self) -> "KnowledgeCheckQuestion":
        correct_count = sum(option.correct for option in self.options)
        if self.question_type == "multiple_choice_single" and correct_count != 1:
            raise ValueError("multiple_choice_single must have exactly one correct option")
        if self.question_type == "multiple_choice_multi" and correct_count < 1:
            raise ValueError("multiple_choice_multi must have at least one correct option")
        return self


class KnowledgeCheckScreen(ScreenBase):
    type: Literal["knowledge_check"]
    question_id: str
    stem: str
    question_type: Literal["multiple_choice_single", "multiple_choice_multi"]
    options: list[KnowledgeCheckOption] = Field(min_length=2, max_length=5)
    questions: list[KnowledgeCheckQuestion] | None = None

    @model_validator(mode="after")
    def validate_answers(self) -> "KnowledgeCheckScreen":
        correct_count = sum(option.correct for option in self.options)
        if self.question_type == "multiple_choice_single" and correct_count != 1:
            raise ValueError("multiple_choice_single must have exactly one correct option")
        if self.question_type == "multiple_choice_multi" and correct_count < 1:
            raise ValueError("multiple_choice_multi must have at least one correct option")
        return self


class CompletionScreen(ScreenBase):
    type: Literal["completion"]
    heading: str
    message: str
    skills_reinforced: list[str]


class ProcessStep(BaseModel):
    label: str
    detail: str


class ProcessSequenceScreen(ScreenBase):
    type: Literal["process_sequence"]
    heading: str
    introduction: str
    steps: list[ProcessStep]


class MisconceptionPair(BaseModel):
    claim: str
    correction: str


class MisconceptionBusterScreen(ScreenBase):
    type: Literal["misconception_buster"]
    heading: str
    pairs: list[MisconceptionPair]


class ComparisonRow(BaseModel):
    label: str
    values: list[str]


class ComparisonTableScreen(ScreenBase):
    type: Literal["comparison_table"]
    heading: str
    columns: list[str]
    rows: list[ComparisonRow]

    @model_validator(mode="after")
    def _rectangular_table(self) -> "ComparisonTableScreen":
        for row in self.rows:
            if len(row.values) != len(self.columns):
                raise ValueError(
                    f"Comparison row {row.label!r} has {len(row.values)} values "
                    f"for {len(self.columns)} columns."
                )
        return self


class TabContent(BaseModel):
    label: str
    heading: str
    body: str


class TabbedContentScreen(ScreenBase):
    type: Literal["tabbed_content"]
    heading: str
    instruction: str
    tabs: list[TabContent]


class RuleCardScreen(ScreenBase):
    type: Literal["rule_card"]
    heading: str
    principle: str
    supporting_detail: str
    examples: list[str]


class ReflectionPromptScreen(ScreenBase):
    type: Literal["reflection_prompt"]
    heading: str
    prompt: str
    guidance: str


class KeyTakeawaysScreen(ScreenBase):
    type: Literal["key_takeaways"]
    heading: str
    takeaways: list[str]


class VideoPlayerScreen(ScreenBase):
    type: Literal["video_player"]
    title: str | None = None
    video_src: str
    poster_path: str | None = None
    captions_path: str | None = None


class VideoSlotScreen(ScreenBase):
    """Intermediate placeholder inserted by elearning.course.author.

    The bundle assembler replaces every VideoSlotScreen with a VideoPlayerScreen
    before final HTML rendering.  A VideoSlotScreen must never appear in the
    final assembled CourseContent.
    """

    type: Literal["video_slot"] = "video_slot"
    slot_id: str
    source_scene_ids: tuple[str, ...] = ()
    title: str | None = None
    captions_required: bool = False
    poster_required: bool = False


class CardGridItem(BaseModel):
    eyebrow: str | None = None
    heading: str
    body: str
    icon: str | None = None


class CardGridScreen(ScreenBase):
    type: Literal["card_grid"]
    heading: str
    introduction: str | None = None
    cards: list[CardGridItem]


class CalloutFocusScreen(ScreenBase):
    type: Literal["callout_focus"]
    eyebrow: str | None = None
    headline: str
    body: str
    attribution: str | None = None


class StructuredListItem(BaseModel):
    label: str | None = None
    detail: str


class StructuredListScreen(ScreenBase):
    type: Literal["structured_list"]
    heading: str
    introduction: str | None = None
    items: list[StructuredListItem]


class ComparisonPanel(BaseModel):
    label: str
    summary: str | None = None
    points: list[str]


class PairedComparisonScreen(ScreenBase):
    type: Literal["paired_comparison"]
    heading: str
    introduction: str | None = None
    left: ComparisonPanel
    right: ComparisonPanel


class DisclosureItem(BaseModel):
    label: str
    heading: str | None = None
    body: str


class DisclosureListScreen(ScreenBase):
    type: Literal["disclosure_list"]
    heading: str
    instruction: str
    items: list[DisclosureItem]


class RelationshipNode(BaseModel):
    id: str
    label: str
    detail: str | None = None
    position: Literal["top_left", "top_right", "bottom_left", "bottom_right"] | None = None


class RelationshipDiagramScreen(ScreenBase):
    type: Literal["relationship_diagram"]
    heading: str
    introduction: str | None = None
    nodes: list[RelationshipNode]
    x_axis_label: str | None = None
    y_axis_label: str | None = None


ScreenContent = Annotated[
    Union[
        TitleScreen,
        ObjectivesScreen,
        ConceptFlipCardScreen,
        WorkedExampleScreen,
        ContrastExampleScreen,
        ScenarioSetupScreen,
        ScenarioBranchScreen,
        ScenarioResolutionScreen,
        KnowledgeCheckScreen,
        CompletionScreen,
        ProcessSequenceScreen,
        MisconceptionBusterScreen,
        ComparisonTableScreen,
        TabbedContentScreen,
        RuleCardScreen,
        ReflectionPromptScreen,
        KeyTakeawaysScreen,
        VideoPlayerScreen,
        VideoSlotScreen,
        CardGridScreen,
        CalloutFocusScreen,
        StructuredListScreen,
        PairedComparisonScreen,
        DisclosureListScreen,
        RelationshipDiagramScreen,
    ],
    Field(discriminator="type"),
]


SCREEN_MODELS: dict[str, type[ScreenBase]] = {
    "title": TitleScreen,
    "objectives": ObjectivesScreen,
    "concept_flip_card": ConceptFlipCardScreen,
    "worked_example": WorkedExampleScreen,
    "contrast_example": ContrastExampleScreen,
    "scenario_setup": ScenarioSetupScreen,
    "scenario_branch": ScenarioBranchScreen,
    "scenario_resolution": ScenarioResolutionScreen,
    "knowledge_check": KnowledgeCheckScreen,
    "completion": CompletionScreen,
    "process_sequence": ProcessSequenceScreen,
    "misconception_buster": MisconceptionBusterScreen,
    "comparison_table": ComparisonTableScreen,
    "tabbed_content": TabbedContentScreen,
    "rule_card": RuleCardScreen,
    "reflection_prompt": ReflectionPromptScreen,
    "key_takeaways": KeyTakeawaysScreen,
    "video_player": VideoPlayerScreen,
    "video_slot": VideoSlotScreen,
    "card_grid": CardGridScreen,
    "callout_focus": CalloutFocusScreen,
    "structured_list": StructuredListScreen,
    "paired_comparison": PairedComparisonScreen,
    "disclosure_list": DisclosureListScreen,
    "relationship_diagram": RelationshipDiagramScreen,
}


class CourseContent(BaseModel):
    rlo_id: str
    rlo_version: str
    generated_at: str
    theme_id: str = "deloitte-green"
    screens: list[ScreenContent]
