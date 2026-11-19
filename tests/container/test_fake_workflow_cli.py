"""
Subprocess tests for the reference-mode workflow CLI path.

These tests run `python -m learning_pipeline.cli` in a subprocess and verify:
- The podcast reference BuildPlan completes successfully.
- The CLI exits zero.
- Stdout deserialises as WorkflowResult.
- The deliverable is the assembly task.
- Run-state JSON is persisted to --run-dir.
- Reference mode does not require TTS environment variables.
- An invalid plan path exits nonzero.
- A file with invalid JSON exits nonzero.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from learning_pipeline.contracts import WorkflowResult

_REFERENCE_PLAN = (
    Path(__file__).parent.parent.parent
    / "examples"
    / "reference"
    / "podcast"
    / "build_plan.json"
)


def _run_cli(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "learning_pipeline.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


# ── Success path ──────────────────────────────────────────────────────────────


def test_fake_cli_exits_zero(tmp_path):
    result = _run_cli(["run-workflow", str(_REFERENCE_PLAN), "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode == 0, result.stderr


def test_fake_cli_stdout_is_valid_workflow_result(tmp_path):
    result = _run_cli(["run-workflow", str(_REFERENCE_PLAN), "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    WorkflowResult.model_validate(data)


def test_fake_cli_deliverable_is_assembly_task(tmp_path):
    result = _run_cli(["run-workflow", str(_REFERENCE_PLAN), "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    deliverables = data["deliverables"]
    assert len(deliverables) == 1
    assert deliverables[0]["task_id"] == "assemble-podcast"


def test_fake_cli_deliverable_contains_audio_uri(tmp_path):
    result = _run_cli(["run-workflow", str(_REFERENCE_PLAN), "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    outputs = data["deliverables"][0]["outputs"]
    assert "audio_uri" in outputs
    assert outputs["audio_uri"].startswith("fake://deliverables/")


def test_fake_cli_persists_run_state_json(tmp_path):
    result = _run_cli(["run-workflow", str(_REFERENCE_PLAN), "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode == 0, result.stderr
    workflow_id = json.loads(result.stdout)["workflow_id"]
    state_file = tmp_path / workflow_id / "run-state.json"
    assert state_file.exists(), f"expected run-state.json at {state_file}"


def test_fake_cli_persisted_snapshot_shows_succeeded(tmp_path):
    result = _run_cli(["run-workflow", str(_REFERENCE_PLAN), "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode == 0, result.stderr
    workflow_id = json.loads(result.stdout)["workflow_id"]
    state = json.loads((tmp_path / workflow_id / "run-state.json").read_text())
    assert state["workflow_status"] == "succeeded"
    for task_id in ("speech-segment-1", "speech-segment-2", "assemble-podcast"):
        assert state["statuses"][task_id] == "succeeded"
        assert task_id in state["results"]


# ── Credential isolation ──────────────────────────────────────────────────────


def test_fake_cli_does_not_require_tts_env_vars(tmp_path):
    """Fake mode must complete with no TTS credentials in the environment."""
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("OPENAI_API_KEY", "LITE_LLM_API_KEY", "LITE_LLM_BASE_URL")}
    result = _run_cli(
        ["run-workflow", str(_REFERENCE_PLAN), "--run-dir", str(tmp_path), "--mode", "reference"],
        env=clean_env,
    )
    assert result.returncode == 0, result.stderr


# ── Failure paths ─────────────────────────────────────────────────────────────


def test_invalid_plan_path_exits_nonzero(tmp_path):
    result = _run_cli(["run-workflow", "/nonexistent/path/build_plan.json", "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode != 0


def test_invalid_plan_json_exits_nonzero(tmp_path):
    bad_plan = tmp_path / "bad.json"
    bad_plan.write_text("this is not json", encoding="utf-8")
    result = _run_cli(["run-workflow", str(bad_plan), "--run-dir", str(tmp_path), "--mode", "reference"])
    assert result.returncode != 0
