"""
Compatibility tests for pipeline/src/podcast_renderer.py.

Verifies that the feasibility renderer:
- Responds to --help without creating an OpenAI client.
- Does not require TTS credentials for --help.
- Has not been broken by Phase 5 container changes.

These tests run in-process where openai is available (local dev or the
feasibility pipeline container). They are skipped automatically when openai
is not installed — the learning-pipeline image does not depend on it.

Do not add tests here that invoke rendering — that requires real TTS calls
and incurs cost. The renderer is preserved as a feasibility reference only.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

_RENDERER = (
    Path(__file__).parent.parent.parent / "pipeline" / "src" / "podcast_renderer.py"
)

# Skip the entire module when openai is not importable (learning-pipeline container)
openai_available = importlib.util.find_spec("openai") is not None
pytestmark = pytest.mark.skipif(
    not openai_available,
    reason="openai not installed — podcast_renderer tests skipped in this environment",
)


def _run_renderer(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_RENDERER), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_renderer_script_exists():
    assert _RENDERER.exists(), f"feasibility renderer not found at {_RENDERER}"


def test_renderer_help_exits_zero():
    """--help must succeed without TTS credentials."""
    result = _run_renderer(["--help"])
    assert result.returncode == 0, result.stderr


def test_renderer_help_does_not_require_credentials():
    """--help must work with TTS env vars absent."""
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("OPENAI_API_KEY", "LITE_LLM_API_KEY", "LITE_LLM_BASE_URL")}
    result = _run_renderer(["--help"], env=clean_env)
    assert result.returncode == 0, result.stderr


def test_renderer_help_output_contains_spec_flag():
    """Sanity-check that --help prints the expected --spec flag."""
    result = _run_renderer(["--help"])
    assert "--spec" in result.stdout or "--spec" in result.stderr
