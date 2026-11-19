"""Versioned system prompts and the composition loader.

Prompt files live in subfolders by pipeline stage. Shared paragraphs live in
``shared/`` and are composed into prompts at load time via
``{{include:shared/<name>.md}}`` markers — see ``loader.load_prompt``.
"""
from .loader import PromptIncludeError, load_prompt

__all__ = ["PromptIncludeError", "load_prompt"]
