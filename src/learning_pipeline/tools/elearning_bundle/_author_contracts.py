"""Phase 14B authoring contracts.

These contracts own the model-copy and compiled-draft boundaries. The key invariant:

    The model returns only component-specific learner-facing copy.
    Identity, lineage, assessments, navigation, and layout are deterministic.

Course structure contracts (AuthoredScreenRequirement, VideoSlotRequirement,
CourseStructureRequirement) live in contracts.py to avoid circular imports and
to expose them at the public tool boundary.

Screen type safety
------------------
- AUTHORABLE_SCREEN_TYPES: types the LLM is allowed to produce
- RESERVED_SCREEN_TYPES: types the LLM must never produce (video_slot, video_player)

Content safety
--------------
_assert_no_unsafe_content() recursively rejects any string value containing
<script>, javascript:, on*= handlers, <iframe>, <object>, or <embed>.  The
LLM produces typed dicts; the Jinja renderer handles HTML escaping.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model, field_validator, model_validator

from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy  # noqa: F401 — re-exported for callers
from learning_pipeline.tools.elearning_bundle.contracts import SlotPreservationReport


# ── Screen content sub-models ──────────────────────────────────────────────────
# All nested models use FrozenModel (extra="forbid") so the JSON schema includes
# additionalProperties: false — required for OpenAI responses.parse() strict mode.


class TitleMetadata(FrozenModel):
    firm: str | None = None
    level: str | None = None
    duration_minutes: int | None = None
    duration: str | None = None
    audience: str | None = None
    version: str | None = None


class CardContent(FrozenModel):
    """Card slot used by concept_flip_card and card_grid screen types."""
    id: str | None = None
    front_label: str | None = None
    front_teaser: str | None = None
    back_definition: str | None = None
    back_examples: list[str] | None = None
    back_safeguard: str | None = None
    eyebrow: str | None = None
    heading: str | None = None
    body: str | None = None
    icon: str | None = None


class BranchOption(FrozenModel):
    id: str
    label: str


class KnowledgeCheckChoice(FrozenModel):
    id: str
    text: str
    correct: bool
    feedback: str


class KnowledgeCheckQuestion(FrozenModel):
    question_id: str
    stem: str
    question_type: Literal["multiple_choice_single", "multiple_choice_multi"]
    options: list[KnowledgeCheckChoice] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def _valid_correct_answer_count(self) -> "KnowledgeCheckQuestion":
        correct_count = sum(option.correct for option in self.options)
        if self.question_type == "multiple_choice_single" and correct_count != 1:
            raise ValueError("multiple_choice_single must have exactly one correct option")
        if self.question_type == "multiple_choice_multi" and correct_count < 1:
            raise ValueError("multiple_choice_multi must have at least one correct option")
        return self


class ProcessStepItem(FrozenModel):
    label: str
    detail: str


class MisconceptionPairItem(FrozenModel):
    claim: str
    correction: str


class ComparisonTableRow(FrozenModel):
    label: str
    values: list[str]


class TabItem(FrozenModel):
    label: str
    heading: str
    body: str


class ItemContent(FrozenModel):
    """Item slot used by structured_list and disclosure_list screen types."""
    label: str | None = None
    heading: str | None = None
    detail: str | None = None
    body: str | None = None


class RelationshipNodeContent(FrozenModel):
    id: str
    label: str
    detail: str | None = None
    position: Literal[
        "top_left", "top_right", "bottom_left", "bottom_right"
    ] | None = None


class ContrastSideContent(FrozenModel):
    label: str
    description: str
    reason: str


class ComparisonPanelContent(FrozenModel):
    label: str
    summary: str | None = None
    points: list[str]


class ScreenContent(FrozenModel):
    """Normalized internal content container for all authorable screen types.

    This is not exposed as the model response schema. Exact component-specific
    learner-copy models are compiled into this container after protected fields
    have been injected deterministically.
    """

    # ── title ──────────────────────────────────────────────────────────────────
    course_title: str | None = Field(None, description="[title] Full course title.")
    subtitle: str | None = Field(None, description="[title] One-sentence description of the course.")
    hook: str | None = Field(None, description="[title] Brief scenario or question that draws the learner in.")
    metadata: TitleMetadata | None = Field(None, description="[title] Optional metadata pills: firm, level, duration.")

    # ── heading — used by many screen types, NOT concept_flip_card ────────────
    heading: str | None = Field(
        None,
        description=(
            "[objectives | process_sequence | misconception_buster | comparison_table | "
            "tabbed_content | rule_card | reflection_prompt | key_takeaways | card_grid | "
            "callout_focus | structured_list | paired_comparison | disclosure_list | "
            "relationship_diagram | completion] Screen heading. "
            "Do NOT use for concept_flip_card — use section_label instead."
        ),
    )

    # ── objectives ─────────────────────────────────────────────────────────────
    objectives: list[str] | None = Field(None, description="[objectives] List of learning objective strings.")

    # ── concept_flip_card ──────────────────────────────────────────────────────
    section_label: str | None = Field(None, description="[concept_flip_card ONLY] Section label shown above the card set.")
    instruction: str | None = Field(None, description="[concept_flip_card | tabbed_content | disclosure_list] Learner-facing instruction text.")
    cards: list[CardContent] | None = Field(
        None,
        description=(
            "[concept_flip_card] Use fields: id, front_label, front_teaser, back_definition, back_examples, back_safeguard. "
            "[card_grid] Use fields: eyebrow, heading, body, icon."
        ),
    )

    # ── worked_example ─────────────────────────────────────────────────────────
    # title also used by: contrast_example, scenario_setup, scenario_resolution
    title: str | None = Field(
        None,
        description="[worked_example | contrast_example | scenario_setup | scenario_resolution] Screen title. NOT for title screen — use course_title there.",
    )
    scenario: str | None = Field(None, description="[worked_example] Scenario description text.")
    analysis: str | None = Field(None, description="[worked_example] Analysis of the scenario.")
    resolution: str | None = Field(None, description="[worked_example] How the scenario resolves.")
    lesson: str | None = Field(None, description="[worked_example] Key lesson drawn from the example.")

    # ── contrast_example ───────────────────────────────────────────────────────
    acceptable: ContrastSideContent | None = Field(None, description="[contrast_example] Acceptable side (label, description, reason).")
    unacceptable: ContrastSideContent | None = Field(None, description="[contrast_example] Unacceptable side (label, description, reason).")

    # ── scenario_setup ────────────────────────────────────────────────────────
    setup_text: str | None = Field(None, description="[scenario_setup] Scenario context paragraph.")
    prompt: str | None = Field(None, description="[scenario_setup | reflection_prompt] Decision prompt or reflection question.")
    branches: list[BranchOption] | None = Field(None, description="[scenario_setup] List of branch choices (id, label).")

    # ── scenario_branch ───────────────────────────────────────────────────────
    branch_id: str | None = Field(None, description="[scenario_branch] ID matching a branch from the scenario_setup.")
    outcome_type: str | None = Field(None, description="[scenario_branch] 'correct' or 'incorrect'.")
    feedback_title: str | None = Field(None, description="[scenario_branch] Short feedback heading.")
    feedback_body: str | None = Field(None, description="[scenario_branch] Feedback explanation body.")
    resolution_screen_id: str | None = Field(None, description="[scenario_branch] screen_id of the resolution screen.")

    # ── scenario_resolution / callout_focus ───────────────────────────────────
    body: str | None = Field(None, description="[scenario_resolution | callout_focus] Body / resolution text.")

    # ── knowledge_check ───────────────────────────────────────────────────────
    question_id: str | None = Field(None, description="[knowledge_check] Stable question identifier.")
    stem: str | None = Field(None, description="[knowledge_check] Question stem text.")
    question_type: Literal["multiple_choice_single", "multiple_choice_multi"] | None = Field(
        None,
        description="[knowledge_check] 'multiple_choice_single' or 'multiple_choice_multi'.",
    )
    options: list[KnowledgeCheckChoice] | None = Field(None, description="[knowledge_check] Answer choices (id, text, correct, feedback).")
    questions: list[KnowledgeCheckQuestion] | None = Field(
        None,
        description=(
            "[knowledge_check] Optional supplemental ordered assessment group when a "
            "screen is assigned more than one approved item. Do not use this instead "
            "of question_id, stem, question_type, and options."
        ),
    )

    # ── completion ─────────────────────────────────────────────────────────────
    message: str | None = Field(None, description="[completion] Completion message body.")
    skills_reinforced: list[str] | None = Field(None, description="[completion] List of skill strings reinforced by this module.")

    # ── process_sequence ──────────────────────────────────────────────────────
    # introduction also used by: card_grid, structured_list, paired_comparison, relationship_diagram
    introduction: str | None = Field(
        None,
        description="[process_sequence | card_grid | structured_list | paired_comparison | relationship_diagram] Optional introductory text below the heading.",
    )
    steps: list[ProcessStepItem] | None = Field(None, description="[process_sequence] Ordered steps (label, detail).")

    # ── misconception_buster ───────────────────────────────────────────────────
    pairs: list[MisconceptionPairItem] | None = Field(None, description="[misconception_buster] Myth/correction pairs (claim, correction).")

    # ── comparison_table ──────────────────────────────────────────────────────
    columns: list[str] | None = Field(None, description="[comparison_table] Column header strings.")
    rows: list[ComparisonTableRow] | None = Field(None, description="[comparison_table] Table rows (label, values list matching columns count).")

    # ── tabbed_content ────────────────────────────────────────────────────────
    tabs: list[TabItem] | None = Field(None, description="[tabbed_content] Tabs (label, heading, body).")

    # ── rule_card ─────────────────────────────────────────────────────────────
    principle: str | None = Field(None, description="[rule_card] The rule or principle statement.")
    supporting_detail: str | None = Field(None, description="[rule_card] Supporting detail / explanation.")
    examples: list[str] | None = Field(None, description="[rule_card] Example strings illustrating the rule.")

    # ── reflection_prompt ─────────────────────────────────────────────────────
    guidance: str | None = Field(None, description="[reflection_prompt] Guidance text shown after the prompt.")

    # ── key_takeaways ─────────────────────────────────────────────────────────
    takeaways: list[str] | None = Field(None, description="[key_takeaways] List of takeaway strings.")

    # ── card_grid / callout_focus ─────────────────────────────────────────────
    eyebrow: str | None = Field(None, description="[card_grid | callout_focus] Small label shown above the main heading or headline.")

    # ── callout_focus ─────────────────────────────────────────────────────────
    headline: str | None = Field(None, description="[callout_focus] Main highlighted statement.")
    attribution: str | None = Field(None, description="[callout_focus] Optional attribution / source.")

    # ── structured_list / disclosure_list ─────────────────────────────────────
    items: list[ItemContent] | None = Field(
        None,
        description=(
            "[structured_list] Use fields: label (optional), detail (required). "
            "[disclosure_list] Use fields: label (required), heading (optional), body (required)."
        ),
    )

    # ── paired_comparison ────────────────────────────────────────────────────
    left: ComparisonPanelContent | None = Field(None, description="[paired_comparison] Left panel (label, summary?, points list).")
    right: ComparisonPanelContent | None = Field(None, description="[paired_comparison] Right panel (label, summary?, points list).")

    # ── relationship_diagram ──────────────────────────────────────────────────
    nodes: list[RelationshipNodeContent] | None = Field(None, description="[relationship_diagram] Nodes (id, label, detail?, position?).")
    x_axis_label: str | None = Field(None, description="[relationship_diagram] Optional X-axis label for matrix layouts.")
    y_axis_label: str | None = Field(None, description="[relationship_diagram] Optional Y-axis label for matrix layouts.")


# ── Learner-copy-only structured output ───────────────────────────────────────


class ConceptCardCopy(FrozenModel):
    front_label: str
    front_teaser: str
    back_definition: str
    back_examples: list[str]
    back_safeguard: str


class CardGridCopy(FrozenModel):
    eyebrow: str | None = None
    heading: str
    body: str
    icon: str | None = None


class ScenarioChoiceCopy(FrozenModel):
    label: str


class StructuredItemCopy(FrozenModel):
    label: str | None = None
    detail: str


class DisclosureItemCopy(FrozenModel):
    label: str
    heading: str | None = None
    body: str


class RelationshipNodeCopy(FrozenModel):
    label: str
    detail: str | None = None


_SCREEN_COPY_FIELDS: dict[str, dict[str, tuple[Any, Any]]] = {
    "title": {
        "course_title": (str, ...),
        "subtitle": (str, ...),
        "hook": (str, ...),
    },
    "objectives": {"heading": (str, ...), "objectives": (list[str], ...)},
    "concept_flip_card": {
        "section_label": (str, ...),
        "instruction": (str, ...),
        "cards": (list[ConceptCardCopy], ...),
    },
    "worked_example": {
        "title": (str, ...),
        "scenario": (str, ...),
        "analysis": (str, ...),
        "resolution": (str, ...),
        "lesson": (str, ...),
    },
    "contrast_example": {
        "title": (str, ...),
        "acceptable": (ContrastSideContent, ...),
        "unacceptable": (ContrastSideContent, ...),
    },
    "scenario_setup": {
        "title": (str, ...),
        "setup_text": (str, ...),
        "prompt": (str, ...),
        "branches": (list[ScenarioChoiceCopy], ...),
    },
    "scenario_branch": {
        "outcome_type": (Literal["correct", "incorrect"], ...),
        "feedback_title": (str, ...),
        "feedback_body": (str, ...),
    },
    "scenario_resolution": {"title": (str, ...), "body": (str, ...)},
    # Assessment wording and answer data are hydrated from approved source.
    "knowledge_check": {},
    "completion": {
        "heading": (str, ...),
        "message": (str, ...),
        "skills_reinforced": (list[str], ...),
    },
    "process_sequence": {
        "heading": (str, ...),
        "introduction": (str, ...),
        "steps": (list[ProcessStepItem], ...),
    },
    "misconception_buster": {
        "heading": (str, ...),
        "pairs": (list[MisconceptionPairItem], ...),
    },
    "comparison_table": {
        "heading": (str, ...),
        "columns": (list[str], ...),
        "rows": (list[ComparisonTableRow], ...),
    },
    "tabbed_content": {
        "heading": (str, ...),
        "instruction": (str, ...),
        "tabs": (list[TabItem], ...),
    },
    "rule_card": {
        "heading": (str, ...),
        "principle": (str, ...),
        "supporting_detail": (str, ...),
        "examples": (list[str], ...),
    },
    "reflection_prompt": {
        "heading": (str, ...),
        "prompt": (str, ...),
        "guidance": (str, ...),
    },
    "key_takeaways": {"heading": (str, ...), "takeaways": (list[str], ...)},
    "card_grid": {
        "heading": (str, ...),
        "introduction": (str | None, None),
        "cards": (list[CardGridCopy], ...),
    },
    "callout_focus": {
        "eyebrow": (str | None, None),
        "headline": (str, ...),
        "body": (str, ...),
        "attribution": (str | None, None),
    },
    "structured_list": {
        "heading": (str, ...),
        "introduction": (str | None, None),
        "items": (list[StructuredItemCopy], ...),
    },
    "paired_comparison": {
        "heading": (str, ...),
        "introduction": (str | None, None),
        "left": (ComparisonPanelContent, ...),
        "right": (ComparisonPanelContent, ...),
    },
    "disclosure_list": {
        "heading": (str, ...),
        "instruction": (str, ...),
        "items": (list[DisclosureItemCopy], ...),
    },
    "relationship_diagram": {
        "heading": (str, ...),
        "introduction": (str | None, None),
        "nodes": (list[RelationshipNodeCopy], ...),
        "x_axis_label": (str | None, None),
        "y_axis_label": (str | None, None),
    },
}


@lru_cache(maxsize=None)
def learner_copy_model_for_screen_type(screen_type: str) -> type[BaseModel]:
    fields = _SCREEN_COPY_FIELDS.get(screen_type)
    if fields is None:
        raise ValueError(f"No learner-copy schema for screen_type {screen_type!r}")
    model_name = "".join(part.title() for part in screen_type.split("_")) + "Copy"
    return create_model(model_name, __base__=FrozenModel, **fields)


def build_learner_copy_batch_model(
    requirements: list[dict[str, Any]],
) -> type[BaseModel]:
    """Create an exact mixed-screen response model without structural fields."""
    fields: dict[str, tuple[Any, Any]] = {}
    type_names: list[str] = []
    for index, requirement in enumerate(requirements, start=1):
        screen_type = str(requirement["screen_type"])
        fields[f"screen_{index}"] = (
            learner_copy_model_for_screen_type(screen_type),
            ...,
        )
        type_names.append(screen_type)
    digest = hashlib.sha256(":".join(type_names).encode()).hexdigest()[:10]
    return create_model(
        f"LearnerCopyBatch{digest}",
        __base__=FrozenModel,
        **fields,
    )


def build_learner_patch_batch_model(
    requirements: list[dict[str, Any]],
    *,
    findings: list[dict[str, Any]],
) -> type[BaseModel]:
    """Create an exact response model containing only reviewed top-level fields."""
    paths_by_screen: dict[str, set[str]] = {}
    for finding in findings:
        screen_id = str(finding["screen_id"])
        field_path = str(finding.get("field_path") or "")
        field_name = field_path.removeprefix("content.").split(".", 1)[0]
        if not field_name:
            raise ValueError(f"Finding for {screen_id!r} has no editable field path")
        paths_by_screen.setdefault(screen_id, set()).add(field_name)

    batch_fields: dict[str, tuple[Any, Any]] = {}
    signature: list[str] = []
    for index, requirement in enumerate(requirements, start=1):
        screen_id = str(requirement["screen_id"])
        screen_type = str(requirement["screen_type"])
        requested_fields = paths_by_screen.get(screen_id, set())
        available_fields = _SCREEN_COPY_FIELDS[screen_type]
        unknown = requested_fields - set(available_fields)
        if unknown:
            raise ValueError(
                f"Patch for {screen_id!r} cites protected fields: {sorted(unknown)}"
            )
        if not requested_fields:
            raise ValueError(f"Patch batch has no findings for screen {screen_id!r}")
        patch_fields = {
            field_name: (available_fields[field_name][0], ...)
            for field_name in sorted(requested_fields)
        }
        patch_type = create_model(
            "".join(part.title() for part in screen_type.split("_"))
            + f"Patch{index}",
            __base__=FrozenModel,
            **patch_fields,
        )
        batch_fields[f"screen_{index}"] = (patch_type, ...)
        signature.extend(f"{screen_type}:{name}" for name in sorted(requested_fields))
    digest = hashlib.sha256(":".join(signature).encode()).hexdigest()[:10]
    return create_model(
        f"LearnerPatchBatch{digest}",
        __base__=FrozenModel,
        **batch_fields,
    )


# ── Screen type registry ───────────────────────────────────────────────────────

AUTHORABLE_SCREEN_TYPES: frozenset[str] = frozenset({
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
    "card_grid",
    "callout_focus",
    "structured_list",
    "paired_comparison",
    "disclosure_list",
    "relationship_diagram",
})

RESERVED_SCREEN_TYPES: frozenset[str] = frozenset({"video_slot", "video_player"})

# All screen types recognised by the pipeline schema.
ALL_SCREEN_TYPES: frozenset[str] = AUTHORABLE_SCREEN_TYPES | RESERVED_SCREEN_TYPES

# Authoritative required content fields per screen type.
# Derived from pipeline/src/schema.py required (non-Optional, no default) fields.
# Used by AuthoredScreenDraft._validate_required_content_fields to catch missing fields
# at parse time — before the LLM response reaches the content builder.
# NOTE: title.metadata is excluded; the content builder adds {} when absent.
_REQUIRED_CONTENT_FIELDS: dict[str, frozenset[str]] = {
    "title":               frozenset({"course_title", "subtitle", "hook"}),
    "objectives":          frozenset({"heading", "objectives"}),
    "concept_flip_card":   frozenset({"section_label", "instruction", "cards"}),
    "worked_example":      frozenset({"title", "scenario", "analysis", "resolution", "lesson"}),
    "contrast_example":    frozenset({"title", "acceptable", "unacceptable"}),
    "scenario_setup":      frozenset({"title", "setup_text", "prompt", "branches"}),
    "scenario_branch":     frozenset({
        "branch_id", "outcome_type", "feedback_title", "feedback_body", "resolution_screen_id"
    }),
    "scenario_resolution": frozenset({"title", "body"}),
    "knowledge_check":     frozenset({"question_id", "stem", "question_type", "options"}),
    "completion":          frozenset({"heading", "message", "skills_reinforced"}),
    "process_sequence":    frozenset({"heading", "introduction", "steps"}),
    "misconception_buster": frozenset({"heading", "pairs"}),
    "comparison_table":    frozenset({"heading", "columns", "rows"}),
    "tabbed_content":      frozenset({"heading", "instruction", "tabs"}),
    "rule_card":           frozenset({"heading", "principle", "supporting_detail", "examples"}),
    "reflection_prompt":   frozenset({"heading", "prompt", "guidance"}),
    "key_takeaways":       frozenset({"heading", "takeaways"}),
    "card_grid":           frozenset({"heading", "cards"}),
    "callout_focus":       frozenset({"headline", "body"}),
    "structured_list":     frozenset({"heading", "items"}),
    "paired_comparison":   frozenset({"heading", "left", "right"}),
    "disclosure_list":     frozenset({"heading", "instruction", "items"}),
    "relationship_diagram": frozenset({"heading", "nodes"}),
}


# ── Content safety ─────────────────────────────────────────────────────────────

_UNSAFE_CONTENT_RE = re.compile(
    r"<script|javascript:|on[a-z]+=|<iframe|<object|<embed",
    re.IGNORECASE,
)


def _assert_no_unsafe_content(value: Any, path: str = "") -> None:
    """Recursively raise ValueError if any string contains unsafe content."""
    if isinstance(value, str):
        if _UNSAFE_CONTENT_RE.search(value):
            raise ValueError(
                f"Unsafe content detected in field {path!r}: "
                f"raw scripts, event handlers, and embeds are not allowed."
            )
    elif isinstance(value, dict):
        for k, v in value.items():
            _assert_no_unsafe_content(v, f"{path}.{k}" if path else k)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _assert_no_unsafe_content(v, f"{path}[{i}]")


# ── LLM draft contracts ────────────────────────────────────────────────────────


class GeneratedAssetRequest(FrozenModel):
    """Declares an image the author would like generated.

    Asset generation is disabled by default (Phase 14B).  When enabled,
    each request is bounded and recorded in the authoring trace.
    """

    asset_id: str = Field(..., description="Stable unique ID, used to derive the filename.")
    logical_path: str = Field(
        ..., description="Relative bundle path, e.g. 'assets/concept-map.png'."
    )
    prompt: str = Field(..., description="Image generation prompt (no text/labels).")
    media_type: str = "image/png"

    @field_validator("asset_id", "logical_path", "prompt")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be blank")
        return v


class AuthoredScreenDraft(FrozenModel):
    """One normalized screen compiled from learner copy and protected structure.

    screen_id must match an AuthoredScreenEntry.screen_id from the brief.
    screen_type must be in that entry's allowed_screen_types.
    content is a plain dict validated against the corresponding schema model.
    """

    screen_id: str
    screen_type: str
    source_scene_ids: tuple[str, ...]
    content: ScreenContent = Field(default_factory=ScreenContent)
    image_prompt: str | None = None

    @field_validator("screen_id")
    @classmethod
    def _not_blank_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("screen_id must not be blank")
        return v

    @field_validator("screen_type")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        if v in RESERVED_SCREEN_TYPES:
            raise ValueError(
                f"screen_type {v!r} is reserved — the LLM must not author video slots."
            )
        if v not in ALL_SCREEN_TYPES:
            raise ValueError(f"Unknown screen_type {v!r}.")
        return v

    @field_validator("source_scene_ids")
    @classmethod
    def _non_empty_scenes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("source_scene_ids must not be empty")
        return v

    @model_validator(mode="after")
    def _no_unsafe_content(self) -> "AuthoredScreenDraft":
        _assert_no_unsafe_content(self.content.model_dump(exclude_none=True), "content")
        if self.image_prompt:
            _assert_no_unsafe_content(self.image_prompt, "image_prompt")
        return self

    @model_validator(mode="after")
    def _validate_required_content_fields(self) -> "AuthoredScreenDraft":
        """Enforce per-screen-type required content fields at parse time.

        Catches wrong field sets from the LLM immediately on output parsing so
        the authoring client's retry loop can re-call with useful repair feedback,
        rather than failing silently inside the content builder after the loop closes.
        """
        required = _REQUIRED_CONTENT_FIELDS.get(self.screen_type)
        if required is None:
            return self

        content_dict = self.content.model_dump(exclude_none=True)

        # Mirror the section_label→heading normalization in the content builder so
        # that LLMs using the common alias pass parse-time validation for process_sequence
        # and other heading-bearing types (concept_flip_card uses section_label natively).
        if self.screen_type != "concept_flip_card":
            if "section_label" in content_dict and "heading" not in content_dict:
                content_dict["heading"] = content_dict.pop("section_label")

        missing = required - set(content_dict)
        # A multi-item check may arrive as the supported `questions` collection
        # without its first question duplicated into the legacy top-level slots.
        # This is a lossless intermediate shape: source hydration populates both
        # representations deterministically before build and validation.
        questions_only_knowledge_check = (
            self.screen_type == "knowledge_check"
            and bool(self.content.questions)
            and missing == required
        )
        if missing and not questions_only_knowledge_check:
            raise ValueError(
                f"screen_type {self.screen_type!r} is missing required content fields: "
                f"{sorted(missing)}. "
                f"Present fields: {sorted(content_dict)}."
            )
        if self.screen_type == "knowledge_check":
            if questions_only_knowledge_check:
                return self
            options = self.content.options or []
            if not 2 <= len(options) <= 5:
                raise ValueError("knowledge_check must have between 2 and 5 options")
            correct_count = sum(option.correct for option in options)
            if self.content.question_type == "multiple_choice_single" and correct_count != 1:
                raise ValueError(
                    "multiple_choice_single knowledge_check must have exactly one correct option"
                )
            if self.content.question_type == "multiple_choice_multi" and correct_count < 1:
                raise ValueError(
                    "multiple_choice_multi knowledge_check must have at least one correct option"
                )
        return self


class ElearningCourseAuthorDraft(FrozenModel):
    """Full internal draft compiled from typed learner-copy responses.

    Validated before it reaches the deterministic course builder.
    """

    draft_id: str
    title: str
    authored_screens: tuple[AuthoredScreenDraft, ...]
    generated_asset_requests: tuple[GeneratedAssetRequest, ...] = ()

    @field_validator("draft_id", "title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be blank")
        return v

    @model_validator(mode="after")
    def _unique_screen_ids(self) -> "ElearningCourseAuthorDraft":
        ids = [s.screen_id for s in self.authored_screens]
        if len(ids) != len(set(ids)):
            raise ValueError("authored_screens must have unique screen_ids")
        return self


def _scenario_structure(
    protected_structure: list[dict[str, Any]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    branch_ids_by_setup: dict[str, tuple[str, ...]] = {}
    resolution_by_branch: dict[str, str] = {}
    for index, requirement in enumerate(protected_structure):
        if requirement.get("screen_type") != "scenario_setup":
            continue
        branch_ids: list[str] = []
        resolution_id: str | None = None
        for candidate in protected_structure[index + 1 :]:
            candidate_type = candidate.get("screen_type")
            if candidate_type == "scenario_setup":
                break
            if candidate_type == "scenario_branch":
                branch_ids.append(str(candidate["screen_id"]))
            elif candidate_type == "scenario_resolution":
                resolution_id = str(candidate["screen_id"])
                break
        branch_ids_by_setup[str(requirement["screen_id"])] = tuple(branch_ids)
        if resolution_id:
            resolution_by_branch.update(
                {branch_id: resolution_id for branch_id in branch_ids}
            )
    return branch_ids_by_setup, resolution_by_branch


def _compile_screen_content(
    *,
    requirement: dict[str, Any],
    copy_value: BaseModel,
    branch_ids_by_setup: dict[str, tuple[str, ...]],
    resolution_by_branch: dict[str, str],
) -> dict[str, Any]:
    screen_id = str(requirement["screen_id"])
    screen_type = str(requirement["screen_type"])
    content = copy_value.model_dump(mode="json", exclude_none=True)

    if screen_type == "concept_flip_card":
        content["cards"] = [
            {"id": f"{screen_id}-card-{index}", **card}
            for index, card in enumerate(content.get("cards", ()), start=1)
        ]
    elif screen_type == "scenario_setup":
        branch_ids = branch_ids_by_setup.get(screen_id, ())
        choices = content.get("branches", ())
        if len(choices) != len(branch_ids):
            raise ValueError(
                f"Scenario setup {screen_id!r} returned {len(choices)} choices "
                f"for {len(branch_ids)} planned scenario branches."
            )
        content["branches"] = [
            {"id": branch_id, "label": choice["label"]}
            for branch_id, choice in zip(branch_ids, choices, strict=True)
        ]
    elif screen_type == "scenario_branch":
        resolution_id = resolution_by_branch.get(screen_id)
        if resolution_id is None:
            raise ValueError(
                f"Scenario branch {screen_id!r} has no protected resolution target."
            )
        content["branch_id"] = screen_id
        content["resolution_screen_id"] = resolution_id
    elif screen_type == "knowledge_check":
        # Source hydration replaces this complete deterministic placeholder before
        # validation or publication. Preflight guarantees an approved source item.
        content = {
            "question_id": "pending-approved-assessment",
            "stem": "Approved assessment pending deterministic hydration.",
            "question_type": "multiple_choice_single",
            "options": [
                {
                    "id": "pending-correct",
                    "text": "Pending approved option",
                    "correct": True,
                    "feedback": "Pending approved feedback.",
                },
                {
                    "id": "pending-incorrect",
                    "text": "Pending approved option",
                    "correct": False,
                    "feedback": "Pending approved feedback.",
                },
            ],
        }
    elif screen_type == "relationship_diagram":
        positions = ("top_left", "top_right", "bottom_left", "bottom_right")
        nodes = content.get("nodes", ())
        content["nodes"] = [
            {
                "id": f"{screen_id}-node-{index}",
                **node,
                **({"position": positions[index - 1]} if len(nodes) <= 4 else {}),
            }
            for index, node in enumerate(nodes, start=1)
        ]
    return content


def compile_learner_copy_batch(
    parsed: BaseModel,
    *,
    requirements: list[dict[str, Any]],
    protected_structure: list[dict[str, Any]],
    deliverable_id: str,
) -> ElearningCourseAuthorDraft:
    """Inject protected identity, lineage, navigation, and source-owned fields."""
    if len(parsed.model_fields_set) != len(requirements):
        raise ValueError("Learner-copy response does not match the requested batch size.")
    branch_ids_by_setup, resolution_by_branch = _scenario_structure(
        protected_structure
    )
    screens: list[AuthoredScreenDraft] = []
    for index, requirement in enumerate(requirements, start=1):
        copy_value = getattr(parsed, f"screen_{index}")
        content = _compile_screen_content(
            requirement=requirement,
            copy_value=copy_value,
            branch_ids_by_setup=branch_ids_by_setup,
            resolution_by_branch=resolution_by_branch,
        )
        screens.append(
            AuthoredScreenDraft(
                screen_id=str(requirement["screen_id"]),
                screen_type=str(requirement["screen_type"]),
                source_scene_ids=tuple(requirement["source_scene_ids"]),
                content=content,
            )
        )
    title = next(
        (
            screen.content.course_title
            for screen in screens
            if screen.screen_type == "title" and screen.content.course_title
        ),
        deliverable_id,
    )
    digest = hashlib.sha256(
        (
            parsed.model_dump_json()
            + ":"
            + ":".join(str(item["screen_id"]) for item in requirements)
        ).encode()
    ).hexdigest()[:12]
    return ElearningCourseAuthorDraft(
        draft_id=f"learner-copy-{digest}",
        title=title,
        authored_screens=tuple(screens),
    )


def _restore_protected_nested_fields(
    *,
    screen: AuthoredScreenDraft,
    field_name: str,
    value: Any,
) -> Any:
    """Reattach deterministic identifiers omitted from learner-copy patches."""
    existing = getattr(screen.content, field_name)
    if field_name == "branches":
        existing_items = list(existing or ())
        if len(value) != len(existing_items):
            raise ValueError(
                f"Patch for {screen.screen_id!r} cannot change scenario branch count."
            )
        return [
            {"id": current.id, "label": replacement["label"]}
            for current, replacement in zip(existing_items, value, strict=True)
        ]
    if field_name == "nodes":
        existing_items = list(existing or ())
        if len(value) != len(existing_items):
            raise ValueError(
                f"Patch for {screen.screen_id!r} cannot change diagram node count."
            )
        return [
            {
                "id": current.id,
                **replacement,
                **({"position": current.position} if current.position else {}),
            }
            for current, replacement in zip(existing_items, value, strict=True)
        ]
    if field_name == "cards" and screen.screen_type == "concept_flip_card":
        existing_items = list(existing or ())
        if len(value) != len(existing_items):
            raise ValueError(
                f"Patch for {screen.screen_id!r} cannot change concept-card count."
            )
        return [
            {"id": current.id, **replacement}
            for current, replacement in zip(existing_items, value, strict=True)
        ]
    return value


def compile_learner_patch_batch(
    parsed: BaseModel,
    *,
    existing_draft: ElearningCourseAuthorDraft,
    requirements: list[dict[str, Any]],
) -> ElearningCourseAuthorDraft:
    """Apply learner-copy patches while retaining all protected draft structure."""
    if len(parsed.model_fields_set) != len(requirements):
        raise ValueError("Learner-copy patch does not match the requested batch size.")
    existing_by_id = {
        screen.screen_id: screen for screen in existing_draft.authored_screens
    }
    patched_screens: list[AuthoredScreenDraft] = []
    for index, requirement in enumerate(requirements, start=1):
        screen_id = str(requirement["screen_id"])
        screen = existing_by_id.get(screen_id)
        if screen is None:
            raise ValueError(f"Patch cites unknown screen {screen_id!r}.")
        if screen.screen_type != str(requirement["screen_type"]):
            raise ValueError(f"Patch cannot change screen_type for {screen_id!r}.")
        patch = getattr(parsed, f"screen_{index}").model_dump(
            mode="json", exclude_none=False, exclude_unset=True
        )
        content = screen.content.model_dump(mode="json", exclude_none=True)
        for field_name, value in patch.items():
            content[field_name] = _restore_protected_nested_fields(
                screen=screen,
                field_name=field_name,
                value=value,
            )
        screen_payload = screen.model_dump(mode="json")
        screen_payload["content"] = ScreenContent.model_validate(content).model_dump(
            mode="json", exclude_none=True
        )
        patched_screens.append(AuthoredScreenDraft.model_validate(screen_payload))
    digest = hashlib.sha256(
        (
            existing_draft.draft_id
            + ":"
            + parsed.model_dump_json()
        ).encode()
    ).hexdigest()[:12]
    return existing_draft.model_copy(
        update={
            "draft_id": f"learner-patch-{digest}",
            "authored_screens": tuple(patched_screens),
        }
    )


# AgenticExecutionPolicy lives in tools/_agentic_policy.py and is re-exported
# above via the import. Existing code that imports it from here continues to work.

# ── Authoring execution trace ──────────────────────────────────────────────────


class ElearningAuthoringTrace(FrozenModel):
    """Structured trace persisted after each authoring run.

    Written to the artifact store; referenced via ElearningAuthorOutput.trace_uri.
    """

    workflow_id: str
    task_id: str
    brief_hash: str
    context_hash: str

    prompt_version: str
    model: str

    model_call_count: int = Field(..., ge=0)
    internal_tool_call_count: int = Field(..., ge=0)
    fitting_attempt_count: int = Field(..., ge=0)
    repair_attempt_count: int = Field(..., ge=0)

    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    initial_batch_mode: Literal["not_run", "sequential", "parallel"] = "not_run"
    initial_batch_peak_concurrency: int = Field(0, ge=0)
    initial_batch_elapsed_seconds: float = Field(0, ge=0)

    authored_screen_ids: tuple[str, ...]
    selected_screen_types: dict[str, str]

    slot_report: SlotPreservationReport
    validation_warnings: tuple[str, ...] = ()
    review_status: str | None = None
    revision_count: int = Field(0, ge=0)
    review_findings: tuple[str, ...] = ()
    finding_counts_by_owner: dict[str, int] = Field(default_factory=dict)
    finding_counts_by_code: dict[str, int] = Field(default_factory=dict)
    repair_outcomes: tuple[str, ...] = ()
    checkpoint_stages_reused: tuple[str, ...] = ()
    checkpoint_recovery_events: tuple[str, ...] = ()
    seat_time_estimate_minutes: int | None = Field(default=None, ge=1)
    seat_time_policy_version: str | None = None
