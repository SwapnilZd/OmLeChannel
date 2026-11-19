"""ElearningAuthoringClient — provider-independent authoring interface.

Architecture
------------
The executor depends on ElearningAuthoringClient (a Protocol), not on any
provider SDK.  This keeps credentials, retries, and model choices outside the
executor and allows testing with FakeElearningAuthoringClient.

LiteLLMElearningAuthoringClient
    Uses component-specific learner-copy schemas against the LiteLLM proxy,
    then injects protected structure into the internal course draft.
    Runs blocking SDK calls inside asyncio.to_thread(). Timeout and retry
    behavior is delegated to the LiteLLM router.
    Credentials are passed explicitly at construction — never read from
    environment variables inside the client.

FakeElearningAuthoringClient
    Returns a configurable ElearningCourseAuthorDraft without any LLM call.
    Used in tests and fake-mode execution.

Content safety is enforced after deterministic compilation in
_author_contracts.AuthoredScreenDraft, before the draft reaches the builder.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from llm_gateway import ModelAlias, build_langfuse_headers, build_litellm_metadata
from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
    AgenticExecutionPolicy,
    build_learner_copy_batch_model,
    build_learner_patch_batch_model,
    compile_learner_copy_batch,
    compile_learner_patch_batch,
)
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    AuthoringFinding,
)

PROMPT_VERSION = "course_author_v6"


def _screen_telemetry(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "screen_count": len(requirements),
        "screen_families": ",".join(
            sorted({str(item.get("screen_type", "unknown")) for item in requirements})
        ),
    }


# ── Response model ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StructuredAuthoringResponse:
    """Typed result returned by ElearningAuthoringClient.author()."""

    draft: ElearningCourseAuthorDraft
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    model_call_count: int = 1


class PublicationReviewResult(FrozenModel):
    """Semantic publication review. Findings must cite visible draft evidence."""

    findings: tuple[AuthoringFinding, ...] = ()


@dataclass(frozen=True)
class StructuredReviewResponse:
    result: PublicationReviewResult
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    model_call_count: int = 1


# ── Client protocol ────────────────────────────────────────────────────────────


class ElearningAuthoringClient(Protocol):
    """Async provider-neutral interface for bounded e-learning course authoring."""

    async def author(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> StructuredAuthoringResponse:
        """Author course content and return a validated structured draft.

        Parameters
        ----------
        system_prompt:
            Complete versioned authoring instructions.
        payload:
            JSON-serialisable dict including brief, context, requirements, etc.
        policy:
            Execution bounds (max calls, timeout, cost ceiling).

        Returns
        -------
        StructuredAuthoringResponse
            Validated draft with token / cost metadata.

        Raises
        ------
        AuthoringPolicyError
            When a policy limit (calls, cost, timeout) would be exceeded.
        AuthoringClientError
            On provider errors, malformed output, or safety violations.
        """
        ...

    async def patch(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> StructuredAuthoringResponse:
        """Patch only the learner-copy fields cited by blocking findings."""
        ...


# ── Client errors ──────────────────────────────────────────────────────────────


class AuthoringClientError(RuntimeError):
    """Raised by the authoring client on provider or safety errors."""


class AuthoringPolicyError(RuntimeError):
    """Raised when an execution policy limit is reached."""


# ── Fake client (for tests and fake mode) ─────────────────────────────────────


class FakeElearningAuthoringClient:
    """Returns a configurable ElearningCourseAuthorDraft with no LLM call.

    Parameters
    ----------
    screens:
        Pre-built AuthoredScreenDraft list returned verbatim.
    title:
        Course title for the returned draft.
    call_count_limit:
        Simulate policy enforcement — raise AuthoringPolicyError after this
        many calls.  0 means always succeed.
    fail_on_call:
        If True, raise AuthoringClientError on the first call.
    """

    def __init__(
        self,
        *,
        screens: list[AuthoredScreenDraft] | None = None,
        title: str = "Fake E-Learning Course",
        call_count_limit: int = 0,
        fail_on_call: bool = False,
    ) -> None:
        self._screens = screens or []
        self._title = title
        self._call_count_limit = call_count_limit
        self._fail_on_call = fail_on_call
        self._calls = 0

    async def author(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> StructuredAuthoringResponse:
        await asyncio.sleep(0)
        self._calls += 1
        if self._fail_on_call:
            raise AuthoringClientError("FakeElearningAuthoringClient: configured to fail.")
        limit = self._call_count_limit or policy.max_model_calls
        if limit > 0 and self._calls > limit:
            raise AuthoringPolicyError(
                f"FakeElearningAuthoringClient: call_count_limit {limit} exceeded."
            )

        draft_id = hashlib.sha256(
            (system_prompt + json.dumps(payload, sort_keys=True)).encode()
        ).hexdigest()[:12]

        draft = ElearningCourseAuthorDraft(
            draft_id=draft_id,
            title=self._title,
            authored_screens=tuple(self._screens),
        )
        return StructuredAuthoringResponse(
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


# ── LiteLLM client (real mode) ────────────────────────────────────────────────


@dataclass
class LiteLLMAuthoringSettings:
    """Explicit credentials and model settings for LiteLLMElearningAuthoringClient.

    Never read from environment variables inside the client.  The caller
    (config.py or the executor factory) supplies these explicitly.
    """

    base_url: str
    api_key: str
    model_name: str = ModelAlias.ELEARNING_COURSE_AUTHORING
    review_model_name: str = ModelAlias.ELEARNING_COURSE_REVIEW
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0


class LiteLLMElearningAuthoringClient:
    """Responses-backed authoring client using an OpenAI-compatible LiteLLM proxy.

    Blocking SDK calls run inside asyncio.to_thread() so the executor stays async.
    Credentials are passed explicitly; no environment variables are read here.
    The SDK has no local timeout or retries; LiteLLM is the single owner of
    those policies.
    """

    def __init__(self, settings: LiteLLMAuthoringSettings) -> None:
        self._settings = settings

    async def author(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> StructuredAuthoringResponse:
        settings = self._settings
        model_name = settings.model_name
        requirements = list(payload.get("authored_screen_requirements", ()))
        protected_structure = list(
            payload.get("protected_course_structure", requirements)
        )
        response_model = build_learner_copy_batch_model(requirements)
        response_map = {
            f"screen_{index}": {
                "screen_id": requirement["screen_id"],
                "screen_type": requirement["screen_type"],
                "source_scene_ids": requirement["source_scene_ids"],
            }
            for index, requirement in enumerate(requirements, start=1)
        }
        model_payload = {**payload, "learner_copy_response_map": response_map}
        batch_contract = payload.get("batch_contract", {})
        telemetry_attributes = {
            "call_purpose": "initial_learner_copy",
            "batch_number": batch_contract.get("batch_number"),
            "batch_count": batch_contract.get("batch_count"),
            **_screen_telemetry(requirements),
        }

        prompt_text = (
            "Author only the learner-facing copy fields in the response schema. "
            "The system injects identity, lineage, navigation, assessment data, "
            "and layout structure.\n\n"
            + json.dumps(model_payload, indent=2, ensure_ascii=False)
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
                    operation="draft",
                    attributes=telemetry_attributes,
                ),
                extra_headers=build_langfuse_headers(
                    model_name,
                    operation="draft",
                    attributes=telemetry_attributes,
                ),
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text},
                ],
                text_format=response_model,
            )

        try:
            result = await asyncio.to_thread(_run_sync)
        except ValidationError as exc:
            assignments = ", ".join(
                f"{key}={value['screen_type']}"
                for key, value in response_map.items()
            )
            failures = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}:"
                f"{error['type']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise AuthoringClientError(
                "Authoring learner-copy validation failed for "
                f"{assignments or 'empty batch'}: {failures}"
            ) from exc
        except Exception as exc:
            raise AuthoringClientError(f"Authoring client error: {exc}") from exc

        parsed = getattr(result, "output_parsed", None)
        if parsed is None:
            raise AuthoringClientError("Authoring model returned no parsed output.")
        if not isinstance(parsed, response_model):
            raise AuthoringClientError(
                f"Authoring model output has unexpected type: {type(parsed)}"
            )
        try:
            draft = compile_learner_copy_batch(
                parsed,
                requirements=requirements,
                protected_structure=protected_structure,
                deliverable_id=str(payload.get("deliverable_id", "elearning-course")),
            )
        except Exception as exc:
            raise AuthoringClientError(
                f"Authoring learner-copy compilation failed: {exc}"
            ) from exc

        # Token + cost accounting
        usage = getattr(result, "usage", None)
        input_tokens: int | None = None
        output_tokens: int | None = None
        estimated_cost: float | None = None
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            if input_tokens and output_tokens:
                estimated_cost = (
                    input_tokens * settings.input_cost_per_token
                    + output_tokens * settings.output_cost_per_token
                )
            # Budget check
            if (
                policy.max_cost_usd is not None
                and estimated_cost is not None
                and estimated_cost > policy.max_cost_usd
            ):
                raise AuthoringPolicyError(
                    f"Authoring cost {estimated_cost:.4f} USD exceeds policy limit "
                    f"{policy.max_cost_usd:.4f} USD."
                )

        return StructuredAuthoringResponse(
            draft=draft,
            model=model_name,
            prompt_version=PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost,
            model_call_count=1,
        )

    async def patch(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> StructuredAuthoringResponse:
        """Request and compile an exact field-level learner-copy patch."""
        settings = self._settings
        requirements = list(payload.get("authored_screen_requirements", ()))
        findings = list(payload.get("blocking_findings", ()))
        try:
            response_model = build_learner_patch_batch_model(
                requirements, findings=findings
            )
            existing_draft = ElearningCourseAuthorDraft.model_validate(
                payload["existing_draft"]
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise AuthoringClientError(f"Invalid authoring patch contract: {exc}") from exc

        response_map = {
            f"screen_{index}": {
                "screen_id": requirement["screen_id"],
                "editable_fields": sorted(
                    {
                        str(finding["field_path"])
                        .removeprefix("content.")
                        .split(".", 1)[0]
                        for finding in findings
                        if finding.get("screen_id") == requirement["screen_id"]
                    }
                ),
                "addressed_finding_ids": [
                    finding.get("finding_id")
                    for finding in findings
                    if finding.get("screen_id") == requirement["screen_id"]
                    and finding.get("finding_id")
                ],
            }
            for index, requirement in enumerate(requirements, start=1)
        }
        model_payload = {**payload, "learner_patch_response_map": response_map}
        telemetry_attributes = {
            "call_purpose": "targeted_learner_copy_repair",
            "repair_outcome": "requested",
            "finding_codes": ",".join(
                sorted({str(item.get("code")) for item in findings})
            ),
            "finding_owners": ",".join(
                sorted({str(item.get("owner")) for item in findings})
            ),
            **_screen_telemetry(requirements),
        }
        prompt_text = (
            "Return only the learner-facing fields in the patch response schema. "
            "Revise each field according to its cited blocking finding and evidence. "
            "Do not repeat or alter identity, lineage, navigation, assessment data, "
            "layout, or any uncited learner-copy field.\n\n"
            + json.dumps(model_payload, indent=2, ensure_ascii=False)
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
                model=settings.model_name,
                metadata=build_litellm_metadata(
                    settings.model_name,
                    operation="patch",
                    attributes=telemetry_attributes,
                ),
                extra_headers=build_langfuse_headers(
                    settings.model_name,
                    operation="patch",
                    attributes=telemetry_attributes,
                ),
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text},
                ],
                text_format=response_model,
            )

        try:
            result = await asyncio.to_thread(_run_sync)
        except ValidationError as exc:
            failures = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}:{error['type']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise AuthoringClientError(
                f"Authoring learner-copy patch validation failed: {failures}"
            ) from exc
        except Exception as exc:
            raise AuthoringClientError(f"Authoring patch client error: {exc}") from exc

        parsed = getattr(result, "output_parsed", None)
        if not isinstance(parsed, response_model):
            raise AuthoringClientError("Authoring patch model returned no parsed output.")
        try:
            draft = compile_learner_patch_batch(
                parsed,
                existing_draft=existing_draft,
                requirements=requirements,
            )
        except Exception as exc:
            raise AuthoringClientError(
                f"Authoring learner-copy patch compilation failed: {exc}"
            ) from exc

        usage = getattr(result, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        estimated_cost = None
        if input_tokens is not None and output_tokens is not None:
            estimated_cost = (
                input_tokens * settings.input_cost_per_token
                + output_tokens * settings.output_cost_per_token
            )
        if (
            policy.max_cost_usd is not None
            and estimated_cost is not None
            and estimated_cost > policy.max_cost_usd
        ):
            raise AuthoringPolicyError(
                f"Authoring patch cost {estimated_cost:.4f} USD exceeds policy limit "
                f"{policy.max_cost_usd:.4f} USD."
            )
        return StructuredAuthoringResponse(
            draft=draft,
            model=settings.model_name,
            prompt_version=PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost,
        )

    async def review(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        policy: AgenticExecutionPolicy,
    ) -> StructuredReviewResponse:
        """Review a draft without granting authority to alter its structure."""
        settings = self._settings
        model_name = settings.review_model_name
        prompt_text = json.dumps(payload, indent=2, ensure_ascii=False)
        learner_view = list(payload.get("learner_view", ()))
        deterministic_signals = list(payload.get("deterministic_signals", ()))
        telemetry_attributes = {
            "call_purpose": "learner_visible_semantic_review",
            "screen_count": len(learner_view),
            "screen_families": ",".join(
                sorted(
                    {
                        str(item.get("screen_type", "unknown"))
                        for item in learner_view
                    }
                )
            ),
            "deterministic_finding_codes": ",".join(
                sorted(
                    {str(item.get("code")) for item in deterministic_signals}
                )
            ),
        }

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
                    operation="review",
                    attributes=telemetry_attributes,
                ),
                extra_headers=build_langfuse_headers(
                    model_name,
                    operation="review",
                    attributes=telemetry_attributes,
                ),
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text},
                ],
                text_format=PublicationReviewResult,
            )

        try:
            result = await asyncio.to_thread(_run_sync)
        except Exception as exc:
            raise AuthoringClientError(f"Authoring review client error: {exc}") from exc

        parsed = getattr(result, "output_parsed", None)
        if not isinstance(parsed, PublicationReviewResult):
            raise AuthoringClientError("Authoring reviewer returned no parsed result.")

        usage = getattr(result, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        estimated_cost = None
        if input_tokens is not None and output_tokens is not None:
            estimated_cost = (
                input_tokens * settings.input_cost_per_token
                + output_tokens * settings.output_cost_per_token
            )
        if (
            policy.max_cost_usd is not None
            and estimated_cost is not None
            and estimated_cost > policy.max_cost_usd
        ):
            raise AuthoringPolicyError(
                f"Authoring review cost {estimated_cost:.4f} USD exceeds policy limit "
                f"{policy.max_cost_usd:.4f} USD."
            )
        return StructuredReviewResponse(
            result=parsed,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost,
        )
