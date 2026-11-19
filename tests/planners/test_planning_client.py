"""Tests for StructuredPlanningClient implementations — Phase 9."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts.planning import (
    PodcastProductionDraft,
    PodcastSpeechSegmentDraft,
    StructuredPlanningResponse,
)
from learning_pipeline.planners.client import (
    FakePlanningClient,
    PlanningClientError,
    PlanningOutputValidationError,
    StructuredPlanningClient,
)


def _minimal_draft() -> PodcastProductionDraft:
    return PodcastProductionDraft(
        draft_id="test-draft",
        title="Test",
        narrative_summary="Test narrative",
        segments=(
            PodcastSpeechSegmentDraft(
                segment_id="seg-01",
                source_scene_ids=("scene-a",),
                speaker="Host",
                text="Hello world.",
                learning_purpose="Introduction",
            ),
        ),
    )


class TestFakePlanningClient:
    def test_implements_protocol(self) -> None:
        client = FakePlanningClient(draft=_minimal_draft())
        assert isinstance(client, StructuredPlanningClient)

    @pytest.mark.asyncio
    async def test_returns_injected_draft(self) -> None:
        draft = _minimal_draft()
        client = FakePlanningClient(draft=draft)
        response = await client.generate(
            system_prompt="sys",
            user_payload={"scene": "data"},
            output_model=PodcastProductionDraft,
            model="gpt-5.6",
        )
        assert isinstance(response, StructuredPlanningResponse)
        assert response.result is draft

    @pytest.mark.asyncio
    async def test_increments_call_count_on_each_call(self) -> None:
        client = FakePlanningClient(draft=_minimal_draft())
        assert client.call_count == 0
        await client.generate(
            system_prompt="s",
            user_payload={},
            output_model=PodcastProductionDraft,
            model="gpt-5.6",
        )
        assert client.call_count == 1
        await client.generate(
            system_prompt="s",
            user_payload={},
            output_model=PodcastProductionDraft,
            model="gpt-5.6",
        )
        assert client.call_count == 2

    @pytest.mark.asyncio
    async def test_records_last_system_prompt(self) -> None:
        client = FakePlanningClient(draft=_minimal_draft())
        assert client.last_system_prompt is None
        await client.generate(
            system_prompt="my-system-prompt",
            user_payload={},
            output_model=PodcastProductionDraft,
            model="gpt-5.6",
        )
        assert client.last_system_prompt == "my-system-prompt"

    @pytest.mark.asyncio
    async def test_records_last_user_payload(self) -> None:
        client = FakePlanningClient(draft=_minimal_draft())
        payload = {"blueprint_id": "bp-01", "scenes": []}
        await client.generate(
            system_prompt="s",
            user_payload=payload,
            output_model=PodcastProductionDraft,
            model="gpt-5.6",
        )
        assert client.last_user_payload == payload

    @pytest.mark.asyncio
    async def test_response_includes_model_and_prompt_version(self) -> None:
        client = FakePlanningClient(draft=_minimal_draft(), prompt_version="podcast_v2")
        response = await client.generate(
            system_prompt="s",
            user_payload={},
            output_model=PodcastProductionDraft,
            model="gpt-5.6",
        )
        assert response.model == "gpt-5.6"
        assert response.prompt_version == "podcast_v2"

    @pytest.mark.asyncio
    async def test_one_call_rule_single_call_per_request(self) -> None:
        """Verify a single planning request makes exactly one client call."""
        client = FakePlanningClient(draft=_minimal_draft())
        await client.generate(
            system_prompt="s",
            user_payload={},
            output_model=PodcastProductionDraft,
            model="gpt-5.6",
        )
        assert client.call_count == 1
