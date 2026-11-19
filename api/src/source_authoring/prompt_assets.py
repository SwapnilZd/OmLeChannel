"""Versioned prompt assets for source authoring operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


PROMPTS_ROOT = Path(__file__).parent / "prompts" / "objective_extraction"


@dataclass(frozen=True)
class PromptAsset:
    prompt_id: str
    version: str
    filename: str
    text: str
    sha256: str


def load_prompt_asset(
    filename: str,
    *,
    prompt_id: str,
    version: str,
    group: str | None = None,
) -> PromptAsset:
    path = PROMPTS_ROOT.parent / group / filename if group else PROMPTS_ROOT / filename
    text = path.read_text(encoding="utf-8").strip()
    if f"Prompt ID: `{prompt_id}`" not in text:
        raise ValueError(f"prompt {filename!r} does not declare ID {prompt_id!r}")
    if f"Prompt Version: `{version}`" not in text:
        raise ValueError(f"prompt {filename!r} does not declare version {version!r}")
    return PromptAsset(
        prompt_id=prompt_id,
        version=version,
        filename=f"{group}/{filename}" if group else filename,
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def compose_prompt_asset(primary: PromptAsset, *included: PromptAsset) -> PromptAsset:
    """Build one auditable prompt from independently editable prompt assets."""
    text = "\n\n---\n\n".join(asset.text for asset in (primary, *included))
    return PromptAsset(
        prompt_id=primary.prompt_id,
        version=primary.version,
        filename=" + ".join(asset.filename for asset in (primary, *included)),
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
