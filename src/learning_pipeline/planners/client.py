"""
StructuredPlanningClient — Phase 9.

Protocol and implementations for making one structured model call per planning
request.  The application-level planner depends on this protocol, not on
any specific SDK class.

Implementations:
  FakePlanningClient         — returns injected draft; records call count for tests.
  LiteLLMPlanningClient      — real mode; uses openai-compatible SDK in a thread
                               to avoid blocking the asyncio event loop.

One-call rule
-------------
Each uncached planning request must invoke exactly one structured model call.
Transport-level retries within the SDK adapter are permitted for transient
network errors, but they must not alter the prompt or start a semantic repair loop.
"""
from __future__ import annotations

import asyncio
import functools
import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from llm_gateway import build_langfuse_headers, build_litellm_metadata
from learning_pipeline.contracts.planning import StructuredPlanningResponse


class PlanningClientError(RuntimeError):
    """Raised when the planning client cannot complete a request."""


class PlanningOutputValidationError(ValueError):
    """
    Raised when the model output fails structured-output schema validation.

    Per the one-call rule, the planner must NOT automatically retry.
    The caller receives this error and can choose to surface it to the user.
    """


@runtime_checkable
class StructuredPlanningClient(Protocol):
    """Provider-independent interface for one structured model call."""

    async def generate(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[BaseModel],
        model: str,
    ) -> StructuredPlanningResponse: ...


# ── Fake client ───────────────────────────────────────────────────────────────


class FakePlanningClient:
    """Deterministic planning client for tests and reference-mode operation.

    Returns an injected draft without making any network requests.
    Records call count so tests can assert the one-call rule.
    """

    def __init__(self, draft: BaseModel, *, prompt_version: str = "podcast_v1") -> None:
        self._draft = draft
        self._prompt_version = prompt_version
        self.call_count = 0
        self.last_system_prompt: str | None = None
        self.last_user_payload: dict[str, Any] | None = None

    async def generate(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[BaseModel],
        model: str,
    ) -> StructuredPlanningResponse:
        if not isinstance(self._draft, output_model):
            raise TypeError(
                f"FakePlanningClient draft is {type(self._draft).__name__}, "
                f"not {output_model.__name__}"
            )
        await asyncio.sleep(0)
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_payload = dict(user_payload)
        return StructuredPlanningResponse(
            result=self._draft,
            model=model,
            prompt_version=self._prompt_version,
            provider_request_id=None,
            input_tokens=None,
            output_tokens=None,
            estimated_cost_usd=None,
        )


# ── Real client ───────────────────────────────────────────────────────────────


class LiteLLMPlanningClient:
    """OpenAI-compatible structured planning client backed by LiteLLM.

    Uses the openai SDK (synchronous) in a thread executor to avoid blocking
    the asyncio event loop.  Provider credentials are passed at construction
    and never logged or included in responses.

    The client makes exactly one API call per ``generate()`` invocation.
    SDK-level transport retries are bounded and do not alter the prompt.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        prompt_version: str = "podcast_v1",
        max_retries: int = 2,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._prompt_version = prompt_version
        self._max_retries = max_retries

    async def generate(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[BaseModel],
        model: str,
    ) -> StructuredPlanningResponse:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    self._generate_sync,
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    output_model=output_model,
                    model=model,
                ),
            )
        except PlanningOutputValidationError:
            raise
        except Exception as exc:
            raise PlanningClientError(f"Planning API call failed: {exc}") from exc
        return result

    def _generate_sync(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[BaseModel],
        model: str,
    ) -> StructuredPlanningResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise PlanningClientError(
                "openai package is required for real planning mode"
            ) from exc

        client = OpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            max_retries=self._max_retries,
        )

        user_text = json.dumps(user_payload, ensure_ascii=False, indent=2)
        try:
            response = client.responses.parse(
                model=model,
                metadata=build_litellm_metadata(model),
                extra_headers=build_langfuse_headers(model),
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                text_format=output_model,
            )
        except Exception as exc:
            raise PlanningClientError(f"Provider API error: {exc}") from exc

        parsed = response.output_parsed
        if parsed is None:
            raise PlanningOutputValidationError(
                "Model returned an empty or invalid structured output — "
                "the planning request failed.  Submit a new planning request "
                "to try again."
            )

        usage = getattr(response, "usage", None)
        in_tokens = getattr(usage, "input_tokens", None)
        out_tokens = getattr(usage, "output_tokens", None)
        request_id = getattr(response, "id", None)

        return StructuredPlanningResponse(
            result=parsed,
            model=response.model,
            prompt_version=self._prompt_version,
            provider_request_id=request_id,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            estimated_cost_usd=None,
        )
