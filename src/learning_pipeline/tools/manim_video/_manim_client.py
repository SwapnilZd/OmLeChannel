"""Manim LLM client protocol and implementations.

Analogous to ElearningAuthoringClient — the controller depends on
ManimLLMClient (a Protocol), not on any provider SDK.

FakeManimLLMClient
    Returns a configurable ManimSceneDraft without any LLM call.
    Used in tests and fake-mode execution.

LiteLLMManimClient
    PydanticAI-backed client for real LLM-driven scene draft generation.
    Uses the same OpenAI-compatible endpoint pattern as the authoring client.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from llm_gateway import ModelAlias, build_langfuse_headers, build_litellm_metadata
from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.manim_video._contracts import (
    ManimPolicyError,
    ManimSceneDraft,
)

PROMPT_VERSION = "manim_scene_draft_v7"


# ── Response model ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManimSceneDraftResponse:
    """Typed result from ManimLLMClient.draft_scene()."""

    draft: ManimSceneDraft
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    model_call_count: int = 1


# ── Protocol ──────────────────────────────────────────────────────────────────


@runtime_checkable
class ManimLLMClient(Protocol):
    """Async provider-neutral interface for bounded Manim scene drafting."""

    async def draft_scene(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> ManimSceneDraftResponse: ...


# ── Client errors ──────────────────────────────────────────────────────────────


class ManimClientError(RuntimeError):
    """Raised on provider errors, malformed output, or safety violations."""


# ── Fake client (for tests and fake mode) ─────────────────────────────────────


class FakeManimLLMClient:
    """Returns a configurable ManimSceneDraft with no LLM call.

    Parameters
    ----------
    draft:
        Pre-built draft returned verbatim on each call.
    call_count_limit:
        Raise ManimPolicyError after this many calls. 0 = always succeed.
    fail_on_call:
        If True, raise ManimClientError on every call.
    repair_draft:
        When set, return this draft on any call after the first (simulates
        a successful repair that produces a different scene draft).
    """

    def __init__(
        self,
        *,
        draft: ManimSceneDraft | None = None,
        call_count_limit: int = 0,
        fail_on_call: bool = False,
        repair_draft: ManimSceneDraft | None = None,
    ) -> None:
        self._draft = draft or _default_fake_draft()
        self._repair_draft = repair_draft
        self._call_count_limit = call_count_limit
        self._fail_on_call = fail_on_call
        self._calls = 0
        self.last_payload: dict[str, Any] | None = None

    async def draft_scene(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> ManimSceneDraftResponse:
        await asyncio.sleep(0)
        self._calls += 1
        if self._fail_on_call:
            raise ManimClientError("FakeManimLLMClient: configured to fail.")
        limit = self._call_count_limit or policy.max_model_calls
        if limit > 0 and self._calls > limit:
            raise ManimPolicyError(
                f"FakeManimLLMClient: call_count_limit {limit} exceeded."
            )
        _ = system_prompt
        self.last_payload = payload

        draft = self._draft
        if self._repair_draft and self._calls > 1:
            draft = self._repair_draft

        return ManimSceneDraftResponse(
            draft=draft,
            model="fake-model",
            prompt_version=PROMPT_VERSION,
            input_tokens=None,
            output_tokens=None,
            estimated_cost_usd=None,
            model_call_count=1,
        )

    @property
    def call_count(self) -> int:
        return self._calls


def _default_fake_draft() -> ManimSceneDraft:
    """Return a safe, valid ManimSceneDraft for tests."""
    return ManimSceneDraft(
        scene_id="fake-scene",
        source_scene_ids=("scene-introduction",),
        template_id="vertical_stack",
        template_version="1.0",
        visual_summary="Three key concepts presented as stacked cards.",
        component_bindings={
            "scene_narration": "Welcome to this lesson.",
            "title": "Key Concepts",
            "items": [
                {"label": "Concept A", "detail": "First concept.", "narration": "This is A."},
                {"label": "Concept B", "detail": "Second concept.", "narration": "This is B."},
                {"label": "Concept C", "detail": "Third concept.", "narration": "This is C."},
            ],
            "closing_narration": "Those are the key concepts.",
        },
        estimated_duration_seconds=60.0,
    )


def _free_form_fake_draft(scene_id: str = "fake-scene") -> ManimSceneDraft:
    """Return a free-form (no template) ManimSceneDraft for tests."""
    scene_class = "Scene_" + scene_id.replace("-", "_")
    safe_source = (
        "from manim import *\n"
        "from manim_voiceover import VoiceoverScene\n\n"
        f"class {scene_class}(VoiceoverScene):\n"
        "    def construct(self):\n"
        "        title = Text('Fake Manim Scene')\n"
        "        with self.voiceover(text='This is the narration.') as tracker:\n"
        "            self.play(Write(title), run_time=tracker.duration)\n"
    )
    return ManimSceneDraft(
        scene_id=scene_id,
        source_scene_ids=("scene-introduction",),
        visual_summary="Simple title card generated as free-form source.",
        generated_source=safe_source,
        estimated_duration_seconds=30.0,
    )


# ── LiteLLM client (real mode) ────────────────────────────────────────────────


@dataclass
class LiteLLMManimSettings:
    """Explicit credentials for LiteLLMManimClient."""

    base_url: str
    api_key: str
    model_name: str = ModelAlias.MANIM_SCENE_GENERATION
    repair_model_name: str = ModelAlias.MANIM_SCENE_REPAIR
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0


class LiteLLMManimClient:
    """PydanticAI-backed Manim scene draft client.

    Uses the same OpenAI-compatible endpoint pattern as the authoring client.
    Credentials passed explicitly — never read from environment variables here.
    The SDK has no local timeout or retries; LiteLLM is the single owner of
    those policies.
    """

    def __init__(self, settings: LiteLLMManimSettings) -> None:
        self._settings = settings

    async def draft_scene(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> ManimSceneDraftResponse:
        settings = self._settings
        repair_mode = bool(payload.get("repair_mode"))
        model_name = (
            settings.repair_model_name if repair_mode else settings.model_name
        )
        operation = "repair" if repair_mode else "draft"
        prompt_text = (
            "Generate a Manim scene draft for the following animation brief.\n\n"
            + json.dumps(payload, indent=2, ensure_ascii=False)
        )

        def _run_sync() -> Any:
            from openai import OpenAI

            client = OpenAI(
                base_url=settings.base_url.rstrip("/"),
                api_key=settings.api_key,
                max_retries=0,
                timeout=None,
            )
            return client.responses.parse(
                model=model_name,
                metadata=build_litellm_metadata(
                    model_name,
                    operation=operation,
                ),
                extra_headers=build_langfuse_headers(
                    model_name,
                    operation=operation,
                ),
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text},
                ],
                text_format=ManimSceneDraft,
            )

        try:
            result = await asyncio.to_thread(_run_sync)
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            raise ManimClientError(f"Scene draft client error: {detail}") from exc

        draft = getattr(result, "output_parsed", None)
        if draft is None:
            raise ManimClientError("Scene draft model returned no parsed output.")
        if not isinstance(draft, ManimSceneDraft):
            raise ManimClientError(
                f"Scene draft model output has unexpected type: {type(draft)}"
            )

        usage = getattr(result, "usage", None)
        input_tokens: int | None = getattr(usage, "input_tokens", None) if usage else None
        output_tokens: int | None = getattr(usage, "output_tokens", None) if usage else None

        estimated_cost: float | None = None
        if input_tokens and output_tokens:
            estimated_cost = (
                input_tokens * settings.input_cost_per_token
                + output_tokens * settings.output_cost_per_token
            )
        if (
            policy.max_cost_usd is not None
            and estimated_cost is not None
            and estimated_cost > policy.max_cost_usd
        ):
            raise ManimPolicyError(
                f"Scene draft cost {estimated_cost:.4f} USD exceeds policy limit "
                f"{policy.max_cost_usd:.4f} USD."
            )

        return ManimSceneDraftResponse(
            draft=draft,
            model=settings.model_name,
            prompt_version=PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost,
            model_call_count=1,
        )
