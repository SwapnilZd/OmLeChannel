"""Prompt loading with shared-block composition — WS6 of docs/prompt-tuning-plan.md.

``load_prompt`` reads a prompt file and resolves ``{{include:<relpath>}}``
markers against the prompts package root, so shared paragraphs (style charter,
personalization boundary, vocabulary) exist in exactly one file.

Rules:
- Include paths are relative to ``src/learning_pipeline/prompts/``.
- One level only: an included file must not itself contain include markers.
- A leading ``#`` header line in an included file is stripped, so shared files
  may carry a documentation header without it leaking into composed prompts.
- The composed text is what callers hash and send — changing a shared file
  changes every composed prompt, so bump the including prompts' PROMPT_VERSION
  constants when editing shared blocks.
"""
from __future__ import annotations

import re
from pathlib import Path

PROMPTS_ROOT = Path(__file__).parent

_INCLUDE_RE = re.compile(r"\{\{include:([A-Za-z0-9_\-./]+)\}\}")


class PromptIncludeError(ValueError):
    """An include marker could not be resolved."""


def _strip_header(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


def load_prompt(path: Path | str) -> str:
    """Read *path* and resolve ``{{include:...}}`` markers.

    Raises:
        PromptIncludeError: On missing include targets, path traversal outside
            the prompts root, or nested includes.
        OSError: If *path* itself cannot be read.
    """
    text = Path(path).read_text(encoding="utf-8")

    def _resolve(match: re.Match[str]) -> str:
        rel = match.group(1)
        target = (PROMPTS_ROOT / rel).resolve()
        if not target.is_relative_to(PROMPTS_ROOT.resolve()):
            raise PromptIncludeError(f"include escapes prompts root: {rel!r}")
        try:
            included = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromptIncludeError(
                f"cannot resolve {{{{include:{rel}}}}} in {path}: {exc}"
            ) from exc
        if _INCLUDE_RE.search(included):
            raise PromptIncludeError(
                f"nested includes are not supported (found in {rel!r})"
            )
        return _strip_header(included)

    return _INCLUDE_RE.sub(_resolve, text)
