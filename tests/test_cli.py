import json
import subprocess
import sys
from pathlib import Path

_REFERENCE_PLAN = (
    Path(__file__).parent.parent
    / "examples"
    / "reference"
    / "podcast"
    / "build_plan.json"
)


def test_run_workflow_produces_deliverable(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "learning_pipeline.cli",
            "run-workflow",
            str(_REFERENCE_PLAN),
            "--run-dir",
            str(tmp_path),
            "--mode",
            "reference",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert len(result["deliverables"]) == 1
    assert result["deliverables"][0]["task_id"] == "assemble-podcast"
