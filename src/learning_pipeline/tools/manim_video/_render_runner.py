"""Canonical render-container runner interface for video.manim.render.

Retry ownership:
- Infrastructure failures (container startup, OOM, timeout) → this layer retries
  with the same source, up to ManimRenderPolicy.max_render_attempts.
- Source errors → the controller calls the LLM for repair, then re-renders.
  The runner itself never calls the LLM.

The runner owns:
- Container launch and teardown.
- Structured result parsing (ManimRenderResult).
- Infrastructure-level transient retry (container start failure, not source error).

The controller owns:
- Source repair decisions.
- LLM calls.
- Artifact publication.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import textwrap
import threading
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from learning_pipeline.tools._fake_media import fake_mp4_bytes
from learning_pipeline.tools.manim_video._contracts import (
    ManimRenderRequest,
    ManimRenderResult,
)

logger = logging.getLogger(__name__)

# ── Minimal fake MP4 and VTT for the fake runner ──────────────────────────────

_FAKE_MP4_BYTES = fake_mp4_bytes()

_FAKE_VTT_BYTES = (
    b"WEBVTT\n\n"
    b"00:00:00.000 --> 00:00:05.000\n"
    b"[Placeholder narration]\n"
)


# ── Protocol ──────────────────────────────────────────────────────────────────


@runtime_checkable
class ManimRenderRunner(Protocol):
    """Async interface for the render execution boundary.

    Implementations must be fail-closed: if the isolation boundary is
    unavailable, raise ManimInfrastructureError rather than executing
    the source in the calling process.
    """

    async def render(self, request: ManimRenderRequest) -> ManimRenderResult: ...


# ── Fake runner (tests and reference mode) ────────────────────────────────────


class FakeManimRenderRunner:
    """Deterministic fake render runner for tests.

    Parameters
    ----------
    fail_attempts:
        Number of initial attempts that return failure before succeeding.
        Set to 0 for always-success. Set to a very high number combined
        with a low max_render_attempts policy to test budget exhaustion.
    fail_category:
        Failure category string returned on failed attempts.
        "source_error" and "geometry_validation_error" (the container's
        pre-render layout gate) trigger LLM repair; "infrastructure_error"
        retries the same source without an LLM call.
    include_captions:
        When True, the success result includes fake VTT captions.
    captions_bytes:
        Explicit caption bytes to return instead of the fake VTT — e.g. SRT
        bytes to exercise the controller's SRT → VTT normalisation path.
    """

    def __init__(
        self,
        *,
        fail_attempts: int = 0,
        fail_category: str = "source_error",
        include_captions: bool = True,
        captions_bytes: bytes | None = None,
    ) -> None:
        self._fail_attempts = fail_attempts
        self._fail_category = fail_category
        self._include_captions = include_captions
        self._captions_bytes = captions_bytes
        self._call_count = 0

    async def render(self, request: ManimRenderRequest) -> ManimRenderResult:
        self._call_count += 1
        if self._call_count <= self._fail_attempts:
            return ManimRenderResult(
                status="failure",
                log_bytes=f"[fake] Render attempt {self._call_count} failed.".encode(),
                failure_category=self._fail_category,
                failure_message=f"FakeManimRenderRunner: simulated {self._fail_category} failure.",
            )
        if self._captions_bytes is not None:
            captions = self._captions_bytes
        else:
            captions = _FAKE_VTT_BYTES if self._include_captions else None
        return ManimRenderResult(
            status="success",
            video_bytes=_FAKE_MP4_BYTES,
            captions_bytes=captions,
            log_bytes=b"[fake] Render succeeded.",
            duration_seconds=float(request.expected_duration_seconds or 60),
            has_audio=True,
        )

    @property
    def call_count(self) -> int:
        return self._call_count


# ── Real container runner ─────────────────────────────────────────────────────


class ContainerManimRenderRunner:
    """Runs Manim source inside the isolated render container.

    Architecture
    ------------
    1. Write request.json and scene.py to a temp input directory.
    2. docker create + docker cp to pass inputs to the container.
    3. docker start --attach; wait for completion.
    4. docker cp output files out.
    5. Parse result.json; return video.mp4 and render.log.

    When lite_llm_base_url is set, network access is enabled and
    LITE_LLM_BASE_URL / LITE_LLM_API_KEY
    are injected so the renderer can reach the shared LiteLLM proxy.
    Without it, --network=none enforces full isolation.

    Parameters
    ----------
    image:
        Docker image name/tag for the Manim renderer.
    timeout_seconds:
        Maximum wall-clock seconds for the container run.
    cpu_limit:
        Docker --cpus value (fractional cores).
    memory_limit:
        Docker --memory value, e.g. "4g".
    lite_llm_base_url:
        Shared LiteLLM URL that the render container can reach.
        When None, network access is disabled (--network=none).
    lite_llm_api_key:
        API key for the shared LiteLLM proxy.
    docker_network:
        Docker network used to resolve an internal LiteLLM hostname.
    brand_outro:
        Whether the renderer appends the approved Deloitte tagline outro.
        Disable for content the tagline must not carry (e.g. A&A, T&L).
    """

    def __init__(
        self,
        *,
        image: str = "manim-renderer:latest",
        timeout_seconds: int = 300,
        cpu_limit: str = "2",
        memory_limit: str = "4g",
        lite_llm_base_url: str | None = None,
        lite_llm_api_key: str | None = None,
        docker_network: str | None = None,
        brand_outro: bool = True,
    ) -> None:
        self._image = image
        self._timeout = timeout_seconds
        self._cpu_limit = cpu_limit
        self._memory_limit = memory_limit
        self._lite_llm_base_url = lite_llm_base_url
        self._lite_llm_api_key = lite_llm_api_key
        self._docker_network = docker_network
        self._brand_outro = brand_outro
        self._voiceover_caches: dict[str, dict[str, bytes]] = {}
        self._voiceover_cache_lock = threading.Lock()

    def _seed_voiceover_cache(self, cache_key: str, input_dir: Path) -> int:
        with self._voiceover_cache_lock:
            cached_files = dict(self._voiceover_caches.get(cache_key, {}))
        if not cached_files:
            return 0
        cache_dir = input_dir / "voiceovers"
        for relative_name, data in cached_files.items():
            target = cache_dir / relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return len(cached_files)

    def _capture_voiceover_cache(self, cache_key: str, output_dir: Path) -> int:
        cache_dir = output_dir / "voiceovers"
        if not cache_dir.exists():
            with self._voiceover_cache_lock:
                return len(self._voiceover_caches.get(cache_key, {}))
        cached_files = {
            str(path.relative_to(cache_dir)): path.read_bytes()
            for path in cache_dir.rglob("*")
            if path.is_file()
        }
        with self._voiceover_cache_lock:
            self._voiceover_caches[cache_key] = cached_files
        return len(cached_files)

    def _discard_voiceover_cache(self, cache_key: str) -> None:
        with self._voiceover_cache_lock:
            self._voiceover_caches.pop(cache_key, None)

    def _build_create_args(self, request: ManimRenderRequest | None = None) -> list[str]:
        args = [
            "docker", "create",
            f"--cpus={self._cpu_limit}",
            f"--memory={self._memory_limit}",
            "--security-opt=no-new-privileges",
            "--env", f"MANIM_BRAND_OUTRO={'on' if self._brand_outro else 'off'}",
            "--env", "PYTHONUNBUFFERED=1",
        ]
        if request is not None:
            args.extend(["--label", f"omnichannel.render_job_id={request.job_id}"])
            if request.workflow_id:
                args.extend(["--label", f"omnichannel.workflow_id={request.workflow_id}"])
            if request.task_id:
                args.extend(["--label", f"omnichannel.task_id={request.task_id}"])
        if self._lite_llm_base_url:
            if self._docker_network:
                args.append(f"--network={self._docker_network}")
            args.extend(["--env", f"LITE_LLM_BASE_URL={self._lite_llm_base_url}"])
            if self._lite_llm_api_key:
                args.extend(["--env", f"LITE_LLM_API_KEY={self._lite_llm_api_key}"])
            if request is not None and request.workflow_id:
                args.extend(["--env", f"LLM_TELEMETRY_JOB_ID={request.workflow_id}"])
            if request is not None and request.task_id:
                args.extend(["--env", f"LLM_TELEMETRY_TASK_ID={request.task_id}"])
        else:
            args.insert(2, "--network=none")
        args.extend([self._image, "--render"])
        return args

    async def render(self, request: ManimRenderRequest) -> ManimRenderResult:
        import tempfile

        cancel_requested = threading.Event()
        active_container: dict[str, str | None] = {"id": None}

        def _run_sync() -> ManimRenderResult:
            # Use docker create + docker cp instead of bind mounts.
            # Bind mounts fail on Docker Desktop (Mac/Windows) because the daemon
            # resolves paths on the host VM, not inside the pipeline container.
            # docker cp works from any Docker client regardless of file sharing config.
            container_id: str | None = None

            with tempfile.TemporaryDirectory(prefix="manim-in-") as in_dir, \
                 tempfile.TemporaryDirectory(prefix="manim-out-") as out_dir:
                in_path = Path(in_dir)
                out_path = Path(out_dir)

                # Write source and request manifest locally.
                (in_path / "scene.py").write_text(request.source_code, encoding="utf-8")
                manifest = {
                    "job_id": request.job_id,
                    "scene_class": request.scene_class,
                    "quality": request.quality,
                    "expected_duration_seconds": request.expected_duration_seconds,
                }
                (in_path / "request.json").write_text(
                    json.dumps(manifest, indent=2), encoding="utf-8"
                )
                seeded_cache_files = self._seed_voiceover_cache(
                    request.idempotency_key, in_path
                )
                started_at = time.monotonic()
                logger.info(
                    "manim-render phase=starting workflow_id=%s task_id=%s "
                    "render_job_id=%s cached_files=%s",
                    request.workflow_id,
                    request.task_id,
                    request.job_id,
                    seeded_cache_files,
                )

                try:
                    # 1. Create container (does not start it).
                    create_args = self._build_create_args(request)
                    create = subprocess.run(create_args, capture_output=True)
                    if create.returncode != 0:
                        log = create.stdout + create.stderr
                        detail = " ".join(log.decode(errors="replace").split())
                        return ManimRenderResult(
                            status="failure",
                            log_bytes=log,
                            failure_category="infrastructure_error",
                            # Keep the Docker detail on the first line because the
                            # worker deliberately persists only that line to the UI.
                            failure_message=(
                                f"docker create failed (code {create.returncode}): {detail}"
                            ),
                        )
                    container_id = create.stdout.decode().strip()
                    active_container["id"] = container_id
                    if cancel_requested.is_set():
                        subprocess.run(
                            ["docker", "rm", "-f", container_id], capture_output=True
                        )
                        raise RuntimeError("Manim render canceled.")

                    # 2. Copy input files into container.
                    cp_in = subprocess.run(
                        ["docker", "cp", f"{in_dir}/.", f"{container_id}:/app/input/"],
                        capture_output=True,
                    )
                    if cp_in.returncode != 0:
                        log = cp_in.stdout + cp_in.stderr
                        return ManimRenderResult(
                            status="failure",
                            log_bytes=log,
                            failure_category="infrastructure_error",
                            failure_message="docker cp (input) failed.\n"
                                            + log.decode(errors="replace").strip(),
                        )

                    # 3. Start and wait (captures stdout+stderr).
                    log_bytes = b""
                    timed_out = False
                    try:
                        start = subprocess.run(
                            ["docker", "start", "--attach", container_id],
                            capture_output=True,
                            timeout=self._timeout,
                        )
                        log_bytes = start.stdout + start.stderr
                        returncode = start.returncode
                    except subprocess.TimeoutExpired:
                        subprocess.run(["docker", "stop", container_id], capture_output=True)
                        timed_out = True
                        returncode = -1
                        log_bytes = b"Container timed out."

                    # 4. Copy output files out of container (best-effort).
                    subprocess.run(
                        ["docker", "cp", f"{container_id}:/app/output/.", f"{out_dir}/"],
                        capture_output=True,
                    )
                    cached_files = self._capture_voiceover_cache(
                        request.idempotency_key, out_path
                    )

                    if timed_out:
                        logger.warning(
                            "manim-render phase=timeout workflow_id=%s task_id=%s "
                            "render_job_id=%s elapsed_seconds=%.2f cached_files=%s",
                            request.workflow_id,
                            request.task_id,
                            request.job_id,
                            time.monotonic() - started_at,
                            cached_files,
                        )
                        return ManimRenderResult(
                            status="failure",
                            log_bytes=log_bytes,
                            failure_category="infrastructure_error",
                            failure_message=f"Container exceeded {self._timeout}s timeout.",
                        )

                    # Prefer render.log from the output dir — the container
                    # captures Manim subprocess output there (not to stdout).
                    log_file = out_path / "render.log"
                    if log_file.exists():
                        log_bytes = log_file.read_bytes()

                except FileNotFoundError:
                    return ManimRenderResult(
                        status="failure",
                        log_bytes=b"docker not found.",
                        failure_category="infrastructure_error",
                        failure_message="docker command not found — is Docker installed?",
                    )
                finally:
                    if container_id:
                        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
                    active_container["id"] = None

                # Parse result.json if present.
                result_json_path = out_path / "result.json"
                if not result_json_path.exists():
                    docker_log = log_bytes.decode(errors="replace").strip()
                    detail = f"\nDocker output:\n{docker_log}" if docker_log else ""
                    return ManimRenderResult(
                        status="failure",
                        log_bytes=log_bytes,
                        failure_category="infrastructure_error" if returncode != 0 else "source_error",
                        failure_message=f"Container exited with code {returncode}, no result.json written.{detail}",
                    )

                try:
                    result_data = json.loads(result_json_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    return ManimRenderResult(
                        status="failure",
                        log_bytes=log_bytes,
                        failure_category="infrastructure_error",
                        failure_message=f"Could not parse result.json: {exc}",
                    )

                if result_data.get("status") != "success":
                    return ManimRenderResult(
                        status="failure",
                        log_bytes=log_bytes,
                        failure_category=result_data.get("failure_category", "render_error"),
                        failure_message=result_data.get("failure_message", "Unknown render failure"),
                    )

                video_path = out_path / "video.mp4"
                video_bytes = video_path.read_bytes() if video_path.exists() else None

                # The container exports SRT (Manim's native subcaption format);
                # VTT is accepted too. The controller normalises SRT → VTT.
                captions_path = out_path / "captions.vtt"
                if not captions_path.exists():
                    captions_path = out_path / "captions.srt"
                captions_bytes = captions_path.read_bytes() if captions_path.exists() else None

                result = ManimRenderResult(
                    status="success",
                    video_bytes=video_bytes,
                    captions_bytes=captions_bytes,
                    log_bytes=log_bytes,
                    duration_seconds=result_data.get("duration_seconds"),
                    has_audio=result_data.get("has_audio"),
                )
                self._discard_voiceover_cache(request.idempotency_key)
                return result

        try:
            return await asyncio.to_thread(_run_sync)
        except asyncio.CancelledError:
            cancel_requested.set()
            container_id = active_container["id"]
            if container_id:
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "rm", "-f", container_id],
                    capture_output=True,
                )
            raise
        except Exception as exc:
            return ManimRenderResult(
                status="failure",
                log_bytes=str(exc).encode(),
                failure_category="infrastructure_error",
                failure_message=str(exc),
            )
