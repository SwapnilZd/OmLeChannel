"""Tests for the ElearningAuthoringClient boundary.

All tests use FakeElearningAuthoringClient — no LLM calls.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_gateway import ModelAlias
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AgenticExecutionPolicy,
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
    build_learner_copy_batch_model,
    build_learner_patch_batch_model,
    compile_learner_copy_batch,
    compile_learner_patch_batch,
)
from learning_pipeline.tools.elearning_bundle._authoring_client import (
    PROMPT_VERSION,
    AuthoringClientError,
    AuthoringPolicyError,
    FakeElearningAuthoringClient,
    LiteLLMAuthoringSettings,
    LiteLLMElearningAuthoringClient,
    PublicationReviewResult,
    StructuredAuthoringResponse,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _policy() -> AgenticExecutionPolicy:
    return AgenticExecutionPolicy()


def _title_draft(screen_id: str = "screen-title") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="title",
        source_scene_ids=("scene-01",),
        content={
            "course_title": "Test Course",
            "subtitle": "A neutral subtitle.",
            "hook": "What will you discover?",
            "metadata": {},
        },
    )


def _payload() -> dict:
    return {
        "deliverable_id": "course-001",
        "authored_screen_requirements": [
            {
                "screen_id": "screen-title",
                "source_scene_ids": ["scene-01"],
                "learning_purpose": "Introduction",
                "content_direction": "Write a title.",
                "screen_type": "title",
            }
        ],
    }


def test_learner_copy_schema_excludes_protected_screen_fields():
    requirements = _payload()["authored_screen_requirements"]
    batch_model = build_learner_copy_batch_model(requirements)
    content_model = batch_model.model_fields["screen_1"].annotation

    assert "course_title" in content_model.model_fields
    assert "screen_id" not in content_model.model_fields
    assert "screen_type" not in content_model.model_fields
    assert "source_scene_ids" not in content_model.model_fields
    assert "metadata" not in content_model.model_fields


def test_learner_copy_compiler_injects_protected_identity_and_lineage():
    requirements = _payload()["authored_screen_requirements"]
    batch_model = build_learner_copy_batch_model(requirements)
    parsed = batch_model.model_validate(
        {
            "screen_1": {
                "course_title": "Compiled Course",
                "subtitle": "A concise introduction.",
                "hook": "Where would you begin?",
            }
        }
    )

    draft = compile_learner_copy_batch(
        parsed,
        requirements=requirements,
        protected_structure=requirements,
        deliverable_id="course-001",
    )

    screen = draft.authored_screens[0]
    assert screen.screen_id == "screen-title"
    assert screen.screen_type == "title"
    assert screen.source_scene_ids == ("scene-01",)
    assert screen.content.metadata is None


def test_relationship_copy_schema_excludes_ids_and_layout_positions():
    requirements = [
        {
            "screen_id": "screen-map",
            "screen_type": "relationship_diagram",
            "source_scene_ids": ["scene-01"],
            "content_direction": "Show the approved relationships.",
        }
    ]
    batch_model = build_learner_copy_batch_model(requirements)
    content_model = batch_model.model_fields["screen_1"].annotation
    node_model = content_model.model_fields["nodes"].annotation.__args__[0]

    assert set(node_model.model_fields) == {"label", "detail"}


def test_relationship_compiler_assigns_ids_and_layout_positions():
    requirements = [
        {
            "screen_id": "screen-map",
            "screen_type": "relationship_diagram",
            "source_scene_ids": ["scene-01"],
        }
    ]
    batch_model = build_learner_copy_batch_model(requirements)
    parsed = batch_model.model_validate(
        {
            "screen_1": {
                "heading": "How the concepts connect",
                "nodes": [
                    {"label": "First", "detail": "The first concept."},
                    {"label": "Second", "detail": "The second concept."},
                ],
            }
        }
    )

    draft = compile_learner_copy_batch(
        parsed,
        requirements=requirements,
        protected_structure=requirements,
        deliverable_id="course-001",
    )

    nodes = draft.authored_screens[0].content.nodes
    assert nodes is not None
    assert [node.id for node in nodes] == ["screen-map-node-1", "screen-map-node-2"]
    assert [node.position for node in nodes] == ["top_left", "top_right"]


def test_knowledge_check_copy_schema_contains_no_source_controlled_fields():
    requirements = [
        {
            "screen_id": "screen-check",
            "screen_type": "knowledge_check",
            "source_scene_ids": ["scene-assessment"],
        }
    ]
    batch_model = build_learner_copy_batch_model(requirements)
    content_model = batch_model.model_fields["screen_1"].annotation

    assert content_model.model_fields == {}


def test_scenario_compiler_injects_choice_ids_and_resolution_navigation():
    requirements = [
        {
            "screen_id": "screen-setup",
            "screen_type": "scenario_setup",
            "source_scene_ids": ["scene-01"],
        },
        {
            "screen_id": "screen-branch-a",
            "screen_type": "scenario_branch",
            "source_scene_ids": ["scene-01"],
        },
        {
            "screen_id": "screen-resolution",
            "screen_type": "scenario_resolution",
            "source_scene_ids": ["scene-01"],
        },
    ]
    batch_model = build_learner_copy_batch_model(requirements)
    parsed = batch_model.model_validate(
        {
            "screen_1": {
                "title": "Choose a response",
                "setup_text": "A generic situation requires a decision.",
                "prompt": "What should you do?",
                "branches": [{"label": "Use the approved approach"}],
            },
            "screen_2": {
                "outcome_type": "correct",
                "feedback_title": "That is the supported response",
                "feedback_body": "The source supports this approach.",
            },
            "screen_3": {
                "title": "Resolution",
                "body": "Apply the approved approach in the relevant situation.",
            },
        }
    )

    draft = compile_learner_copy_batch(
        parsed,
        requirements=requirements,
        protected_structure=requirements,
        deliverable_id="course-001",
    )

    setup, branch, _resolution = draft.authored_screens
    assert setup.content.branches is not None
    assert setup.content.branches[0].id == "screen-branch-a"
    assert branch.content.branch_id == "screen-branch-a"
    assert branch.content.resolution_screen_id == "screen-resolution"


def test_patch_schema_contains_only_the_reviewed_editable_field():
    requirements = _payload()["authored_screen_requirements"]
    patch_model = build_learner_patch_batch_model(
        requirements,
        findings=[
            {
                "screen_id": "screen-title",
                "field_path": "content.hook",
                "code": "LEARNER_INSTRUCTION_UNUSABLE",
                "owner": "author",
            }
        ],
    )
    title_patch = patch_model.model_fields["screen_1"].annotation

    assert set(title_patch.model_fields) == {"hook"}

    with pytest.raises(ValidationError, match="extra_forbidden"):
        patch_model.model_validate(
            {
                "screen_1": {
                    "hook": "Valid replacement.",
                    "screen_id": "mutated-screen-id",
                }
            }
        )


def test_patch_schema_rejects_protected_content_field():
    with pytest.raises(ValueError, match="protected fields"):
        build_learner_patch_batch_model(
            _payload()["authored_screen_requirements"],
            findings=[
                {
                    "screen_id": "screen-title",
                    "field_path": "content.metadata",
                }
            ],
        )


def test_patch_compiler_changes_only_reviewed_field():
    existing = ElearningCourseAuthorDraft(
        draft_id="existing",
        title="Existing Course",
        authored_screens=(_title_draft("screen-title"),),
    )
    requirements = _payload()["authored_screen_requirements"]
    findings = [
        {
            "screen_id": "screen-title",
            "field_path": "content.hook",
        }
    ]
    patch_model = build_learner_patch_batch_model(requirements, findings=findings)
    parsed = patch_model.model_validate(
        {"screen_1": {"hook": "Use the approved process to choose the next step."}}
    )

    patched = compile_learner_patch_batch(
        parsed,
        existing_draft=existing,
        requirements=requirements,
    )

    before = existing.authored_screens[0]
    after = patched.authored_screens[0]
    assert after.content.hook == "Use the approved process to choose the next step."
    assert after.content.course_title == before.content.course_title
    assert after.content.subtitle == before.content.subtitle
    assert after.screen_id == before.screen_id
    assert after.screen_type == before.screen_type
    assert after.source_scene_ids == before.source_scene_ids


# ── FakeElearningAuthoringClient basic ────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_client_returns_response():
    client = FakeElearningAuthoringClient(screens=[_title_draft()])
    response = await client.author(
        system_prompt="System prompt.",
        payload=_payload(),
        policy=_policy(),
    )
    assert isinstance(response, StructuredAuthoringResponse)
    assert isinstance(response.draft, ElearningCourseAuthorDraft)


@pytest.mark.asyncio
async def test_fake_client_returns_configured_screens():
    screens = [_title_draft("s-title")]
    client = FakeElearningAuthoringClient(screens=screens)
    response = await client.author(
        system_prompt="x", payload=_payload(), policy=_policy()
    )
    assert len(response.draft.authored_screens) == 1
    assert response.draft.authored_screens[0].screen_id == "s-title"


@pytest.mark.asyncio
async def test_fake_client_prompt_version_is_current():
    client = FakeElearningAuthoringClient()
    response = await client.author(
        system_prompt="x", payload=_payload(), policy=_policy()
    )
    assert response.prompt_version == PROMPT_VERSION


@pytest.mark.asyncio
async def test_fake_client_no_credentials_needed():
    """FakeElearningAuthoringClient requires no environment variables."""
    client = FakeElearningAuthoringClient(screens=[_title_draft()])
    # No env vars set — should succeed
    response = await client.author(
        system_prompt="x", payload={}, policy=_policy()
    )
    assert response.model == "fake-model"


@pytest.mark.asyncio
async def test_fake_client_tracks_call_count():
    client = FakeElearningAuthoringClient(screens=[_title_draft()])
    assert client.call_count == 0
    await client.author(system_prompt="x", payload={}, policy=_policy())
    assert client.call_count == 1
    await client.author(system_prompt="x", payload={}, policy=_policy())
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_fake_client_fail_on_call():
    client = FakeElearningAuthoringClient(fail_on_call=True)
    with pytest.raises(AuthoringClientError, match="configured to fail"):
        await client.author(system_prompt="x", payload={}, policy=_policy())


@pytest.mark.asyncio
async def test_fake_client_call_count_limit():
    client = FakeElearningAuthoringClient(
        screens=[_title_draft()], call_count_limit=2
    )
    # First two calls succeed
    await client.author(system_prompt="x", payload={}, policy=_policy())
    await client.author(system_prompt="x", payload={}, policy=_policy())
    # Third exceeds limit
    with pytest.raises(AuthoringPolicyError, match="call_count_limit"):
        await client.author(system_prompt="x", payload={}, policy=_policy())


@pytest.mark.asyncio
async def test_fake_client_draft_id_is_deterministic():
    """Same payload produces the same draft_id."""
    client = FakeElearningAuthoringClient(screens=[_title_draft()])
    p = {"key": "value"}
    r1 = await client.author(system_prompt="x", payload=p, policy=_policy())
    r2 = await client.author(system_prompt="x", payload=p, policy=_policy())
    assert r1.draft.draft_id == r2.draft.draft_id


@pytest.mark.asyncio
async def test_fake_client_different_payloads_give_different_draft_ids():
    client = FakeElearningAuthoringClient(screens=[_title_draft()])
    r1 = await client.author(system_prompt="x", payload={"a": 1}, policy=_policy())
    r2 = await client.author(system_prompt="x", payload={"a": 2}, policy=_policy())
    assert r1.draft.draft_id != r2.draft.draft_id


@pytest.mark.asyncio
async def test_fake_client_empty_screens():
    """Zero screens is valid — e.g. a brief with only video slots."""
    client = FakeElearningAuthoringClient(screens=[])
    response = await client.author(
        system_prompt="x", payload={}, policy=_policy()
    )
    assert len(response.draft.authored_screens) == 0


# ── Token + cost fields ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_client_token_fields_are_none():
    client = FakeElearningAuthoringClient(screens=[_title_draft()])
    response = await client.author(
        system_prompt="x", payload={}, policy=_policy()
    )
    assert response.input_tokens is None
    assert response.output_tokens is None
    assert response.estimated_cost_usd is None


@pytest.mark.asyncio
async def test_fake_client_model_call_count_is_one():
    client = FakeElearningAuthoringClient(screens=[_title_draft()])
    response = await client.author(
        system_prompt="x", payload={}, policy=_policy()
    )
    assert response.model_call_count == 1


# ── StructuredAuthoringResponse ───────────────────────────────────────────────


def test_structured_authoring_response_is_frozen():
    draft = ElearningCourseAuthorDraft(
        draft_id="d1",
        title="T",
        authored_screens=(),
    )
    response = StructuredAuthoringResponse(
        draft=draft,
        model="gpt-5.6",
        prompt_version=PROMPT_VERSION,
    )
    assert response.prompt_version == PROMPT_VERSION
    # dataclass(frozen=True) raises FrozenInstanceError on mutation
    with pytest.raises(Exception):
        response.model = "changed"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_real_client_delegates_timeout_and_retries_to_litellm(monkeypatch):
    client_kwargs: list[dict] = []
    request_metadata: list[dict] = []
    request_models: list[str] = []

    class FakeResponses:
        def parse(self, *, text_format, **kwargs):
            request_metadata.append(kwargs["metadata"])
            request_models.append(kwargs["model"])
            if text_format is PublicationReviewResult:
                parsed = PublicationReviewResult()
            else:
                parsed = text_format()
            return type("Response", (), {"output_parsed": parsed, "usage": None})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            client_kwargs.append(kwargs)
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LiteLLMElearningAuthoringClient(
        LiteLLMAuthoringSettings(
            base_url="http://litellm:4000",
            api_key="test-key",
        )
    )

    await client.author(system_prompt="author", payload={}, policy=_policy())
    await client.review(system_prompt="review", payload={}, policy=_policy())

    assert len(client_kwargs) == 2
    assert all(kwargs["max_retries"] == 0 for kwargs in client_kwargs)
    assert all(kwargs["timeout"] is None for kwargs in client_kwargs)
    assert request_models == [
        ModelAlias.ELEARNING_COURSE_AUTHORING,
        ModelAlias.ELEARNING_COURSE_REVIEW,
    ]
    assert request_metadata[1]["model_alias"] == ModelAlias.ELEARNING_COURSE_REVIEW
    assert request_metadata[1]["call_purpose"] == "learner_visible_semantic_review"
    assert request_metadata[1]["screen_count"] == 0


@pytest.mark.asyncio
async def test_real_client_compiles_typed_copy_into_protected_screen(monkeypatch):
    seen_formats = []
    seen_metadata = []

    class FakeResponses:
        def parse(self, *, text_format, **kwargs):
            seen_formats.append(text_format)
            seen_metadata.append(kwargs["metadata"])
            parsed = text_format.model_validate(
                {
                    "screen_1": {
                        "course_title": "Typed Course",
                        "subtitle": "A concise introduction.",
                        "hook": "What should you consider first?",
                    }
                }
            )
            return type("Response", (), {"output_parsed": parsed, "usage": None})()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LiteLLMElearningAuthoringClient(
        LiteLLMAuthoringSettings(
            base_url="http://litellm:4000",
            api_key="test-key",
        )
    )

    response = await client.author(
        system_prompt="author",
        payload={
            **_payload(),
            "protected_course_structure": _payload()[
                "authored_screen_requirements"
            ],
            "batch_contract": {"batch_number": 2, "batch_count": 4},
        },
        policy=_policy(),
    )

    assert seen_formats[0] is not ElearningCourseAuthorDraft
    assert response.draft.authored_screens[0].screen_id == "screen-title"
    assert response.draft.authored_screens[0].content.course_title == "Typed Course"
    assert seen_metadata[0]["call_purpose"] == "initial_learner_copy"
    assert seen_metadata[0]["screen_count"] == 1
    assert seen_metadata[0]["screen_families"] == "title"
    assert seen_metadata[0]["batch_number"] == 2
    assert seen_metadata[0]["batch_count"] == 4


@pytest.mark.asyncio
async def test_real_client_patch_changes_only_cited_field(monkeypatch):
    seen_metadata = []

    class FakeResponses:
        def parse(self, *, text_format, **kwargs):
            seen_metadata.append(kwargs["metadata"])
            parsed = text_format.model_validate(
                {"screen_1": {"hook": "Choose the next step using the source."}}
            )
            return type("Response", (), {"output_parsed": parsed, "usage": None})()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LiteLLMElearningAuthoringClient(
        LiteLLMAuthoringSettings(
            base_url="http://litellm:4000",
            api_key="test-key",
        )
    )
    before = ElearningCourseAuthorDraft(
        draft_id="existing",
        title="Test Course",
        authored_screens=(_title_draft(),),
    )
    payload = {
        **_payload(),
        "existing_draft": before.model_dump(mode="json"),
        "blocking_findings": [
            {
                "screen_id": "screen-title",
                "field_path": "content.hook",
                "code": "LEARNER_INSTRUCTION_UNUSABLE",
                "owner": "author",
                "revision_instruction": "State the learner task directly.",
                "evidence": "What will you discover?",
            }
        ],
    }

    response = await client.patch(
        system_prompt="Patch only the cited field.",
        payload=payload,
        policy=_policy(),
    )

    after = response.draft.authored_screens[0]
    assert after.content.hook == "Choose the next step using the source."
    assert after.content.course_title == before.authored_screens[0].content.course_title
    assert after.content.subtitle == before.authored_screens[0].content.subtitle
    assert after.screen_id == "screen-title"
    assert seen_metadata[0]["call_purpose"] == "targeted_learner_copy_repair"
    assert seen_metadata[0]["finding_codes"] == "LEARNER_INSTRUCTION_UNUSABLE"
    assert seen_metadata[0]["finding_owners"] == "author"
    assert seen_metadata[0]["repair_outcome"] == "requested"


@pytest.mark.asyncio
async def test_real_client_reports_copy_field_errors_without_echoing_input(monkeypatch):
    class FakeResponses:
        def parse(self, *, text_format, **_kwargs):
            return text_format.model_validate(
                {"screen_1": {"screen_id": "do-not-echo-this"}}
            )

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LiteLLMElearningAuthoringClient(
        LiteLLMAuthoringSettings(
            base_url="http://litellm:4000",
            api_key="test-key",
        )
    )

    with pytest.raises(AuthoringClientError) as error:
        await client.author(
            system_prompt="author",
            payload=_payload(),
            policy=_policy(),
        )

    message = str(error.value)
    assert "screen_1=title" in message
    assert "screen_1.course_title" in message
    assert "do-not-echo-this" not in message
