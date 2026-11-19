"""OpenAI-compatible model clients configured exclusively through LiteLLM."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dotenv import load_dotenv
from llm_gateway import ModelAlias, load_lite_llm_settings
from openai import OpenAI

if TYPE_CHECKING:
    from pydantic_ai.models.openai import OpenAIChatModel

load_dotenv()


def litellm_settings() -> tuple[str, str]:
    settings = load_lite_llm_settings(required=False)
    return settings.base_url, settings.api_key


def make_openai_client(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> OpenAI:
    """Return the shared OpenAI-compatible synchronous LiteLLM client."""
    default_url, default_key = litellm_settings()
    return OpenAI(
        base_url=(base_url or default_url).rstrip("/"),
        api_key=api_key or default_key,
    )


def make_model(model_name: str | None = None) -> "OpenAIChatModel":
    """Return a PydanticAI chat model backed by the LiteLLM proxy."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    base_url, api_key = litellm_settings()
    return OpenAIChatModel(
        model_name or ModelAlias.SLIDE_CONTENT_FITTING,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )
