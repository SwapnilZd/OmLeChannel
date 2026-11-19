from __future__ import annotations

import json
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


_ROOT = Path(__file__).parents[2]
_CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
)


def _chrome() -> Path | None:
    discovered = shutil.which("google-chrome") or shutil.which("chromium")
    if discovered:
        return Path(discovered)
    return next((path for path in _CHROME_CANDIDATES if path.exists()), None)


class _JobsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib callback name
        if self.path == "/jobs":
            self._respond(
                (_ROOT / "api/templates/jobs.html").read_bytes(), "text/html; charset=utf-8"
            )
            return
        if self.path.startswith("/api/commissioning-jobs/") and "/deliverables" in self.path:
            podcast = "/job-podcast/" in self.path
            self._json([
                {
                    "deliverable_id": "download-1",
                    "filename": "podcast.mp3" if podcast else "course.zip",
                    "media_type": "audio/mpeg" if podcast else "application/zip",
                    "size_bytes": 100,
                    "primary": True,
                    "download_url": (
                        "/api/commissioning-jobs/job-browser/deliverables/"
                        "download-1/download"
                    ),
                }
            ])
            return
        if self.path.startswith("/api/commissioning-jobs"):
            now = datetime.now(UTC).isoformat()
            self._json([
                {
                    "job_id": "job-browser",
                    "request_id": "request-browser",
                    "course_goal": "Browser-tested learning module",
                    "state": "queued_for_execution",
                    "status": "completed",
                    "stage_label": "Content ready",
                    "selected_modality": "elearning",
                    "workflow_id": "workflow-browser",
                    "completed_tasks": 2,
                    "total_tasks": 2,
                    "downloadable": True,
                    "blueprint_available": True,
                    "error_summary": None,
                    "created_at": now,
                    "updated_at": now,
                    "poll_after_ms": None,
                },
                {
                    "job_id": "job-podcast",
                    "request_id": "request-podcast",
                    "course_goal": "Browser-tested podcast",
                    "state": "queued_for_execution",
                    "status": "completed",
                    "stage_label": "Content ready",
                    "selected_modality": "podcast",
                    "workflow_id": "workflow-podcast",
                    "completed_tasks": 2,
                    "total_tasks": 2,
                    "downloadable": True,
                    "blueprint_available": True,
                    "error_summary": None,
                    "created_at": now,
                    "updated_at": now,
                    "poll_after_ms": None,
                },
            ])
            return
        self.send_error(404)

    def log_message(self, *_args):
        pass

    def _json(self, value):
        self._respond(json.dumps(value).encode(), "application/json")

    def _respond(self, body: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_completed_job_renders_download_action_in_browser(tmp_path):
    chrome = _chrome()
    if chrome is None:
        pytest.skip("Chrome/Chromium is not installed")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8010), _JobsHandler)
    except OSError:
        pytest.skip("port 8010 is unavailable for the browser smoke test")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command = [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={tmp_path / 'chrome-profile'}",
            "--virtual-time-budget=3000",
            "--dump-dom",
            "http://127.0.0.1:8010/jobs",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            # Chrome can keep its browser process alive because the page owns a
            # future polling timer, even after --dump-dom has emitted the final
            # document. subprocess.run terminates it and preserves that output.
            returncode = 0
            stdout = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr = (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert returncode == 0, stderr
    assert "Browser-tested learning module" in stdout
    assert "Browser-tested podcast" in stdout
    assert stdout.count(">Open course</a>") == 1
    assert stdout.index(">Open course</a>") < stdout.index(">Download course package</a>")
    assert "Download course package" in stdout
    assert "download-1/download" in stdout
