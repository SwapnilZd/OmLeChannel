"""Tests for fake implementations: FakeManimLLMClient, FakeManimRenderRunner, FakeManimNarrationService."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.manim_video._contracts import (
    ManimRenderRequest,
    ManimPolicyError,
)
from learning_pipeline.tools.manim_video._manim_client import (
    FakeManimLLMClient,
    LiteLLMManimClient,
    LiteLLMManimSettings,
    ManimClientError,
    ManimSceneDraft,
    _default_fake_draft,
    _free_form_fake_draft,
)
from learning_pipeline.tools.manim_video._render_runner import (
    ContainerManimRenderRunner,
    FakeManimRenderRunner,
    _FAKE_MP4_BYTES,
    _FAKE_VTT_BYTES,
)
from learning_pipeline.tools.manim_video._tts import FakeManimNarrationService

_POLICY = AgenticExecutionPolicy()


def _render_request(scene_class: str = "SceneTest") -> ManimRenderRequest:
    return ManimRenderRequest(
        job_id="job-1",
        idempotency_key="abc",
        scene_class=scene_class,
        source_code="from manim import *\n",
        quality="medium_quality",
    )


# ── FakeManimLLMClient ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_client_returns_default_draft():
    client = FakeManimLLMClient()
    resp = await client.draft_scene(
        system_prompt="sys", payload={}, policy=_POLICY
    )
    assert resp.draft.template_id == "vertical_stack"
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_fake_client_returns_custom_draft():
    custom = _free_form_fake_draft("custom-scene")
    client = FakeManimLLMClient(draft=custom)
    resp = await client.draft_scene(system_prompt="", payload={}, policy=_POLICY)
    assert resp.draft.scene_id == "custom-scene"


@pytest.mark.asyncio
async def test_fake_client_returns_repair_draft_on_second_call():
    base = _default_fake_draft()
    repair = _free_form_fake_draft("repaired-scene")
    client = FakeManimLLMClient(draft=base, repair_draft=repair)

    resp1 = await client.draft_scene(system_prompt="", payload={}, policy=_POLICY)
    resp2 = await client.draft_scene(system_prompt="", payload={}, policy=_POLICY)

    assert resp1.draft.template_id == "vertical_stack"
    assert resp2.draft.scene_id == "repaired-scene"
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_fake_client_fail_on_call():
    client = FakeManimLLMClient(fail_on_call=True)
    with pytest.raises(ManimClientError):
        await client.draft_scene(system_prompt="", payload={}, policy=_POLICY)


@pytest.mark.asyncio
async def test_fake_client_call_count_limit():
    client = FakeManimLLMClient(call_count_limit=1)
    await client.draft_scene(system_prompt="", payload={}, policy=_POLICY)
    with pytest.raises(ManimPolicyError, match="call_count_limit"):
        await client.draft_scene(system_prompt="", payload={}, policy=_POLICY)


@pytest.mark.asyncio
async def test_real_client_delegates_timeout_and_retries_to_litellm(monkeypatch):
    client_kwargs: list[dict] = []
    parse_kwargs: list[dict] = []

    class FakeResponses:
        def parse(self, **kwargs):
            parse_kwargs.append(kwargs)
            return type("Response", (), {
                "output_parsed": _default_fake_draft(),
                "usage": None,
            })()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            client_kwargs.append(kwargs)
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LiteLLMManimClient(LiteLLMManimSettings(
        base_url="http://litellm:4000",
        api_key="test-key",
    ))

    await client.draft_scene(system_prompt="system", payload={}, policy=_POLICY)

    assert client_kwargs == [{
        "base_url": "http://litellm:4000",
        "api_key": "test-key",
        "max_retries": 0,
        "timeout": None,
    }]
    assert parse_kwargs[0]["model"] == "manim-scene-generation"


@pytest.mark.asyncio
async def test_real_client_routes_repairs_to_low_effort_alias(monkeypatch):
    parse_kwargs: list[dict] = []

    class FakeResponses:
        def parse(self, **kwargs):
            parse_kwargs.append(kwargs)
            return type("Response", (), {
                "output_parsed": _default_fake_draft(),
                "usage": None,
            })()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LiteLLMManimClient(LiteLLMManimSettings(
        base_url="http://litellm:4000",
        api_key="test-key",
    ))

    await client.draft_scene(
        system_prompt="system",
        payload={"repair_mode": True},
        policy=_POLICY,
    )

    assert parse_kwargs[0]["model"] == "manim-scene-repair"


@pytest.mark.asyncio
async def test_real_client_never_emits_a_blank_provider_error(monkeypatch):
    class FakeResponses:
        def parse(self, **kwargs):
            raise TimeoutError()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LiteLLMManimClient(LiteLLMManimSettings(
        base_url="http://litellm:4000",
        api_key="test-key",
    ))

    with pytest.raises(ManimClientError, match="Scene draft client error: TimeoutError"):
        await client.draft_scene(system_prompt="system", payload={}, policy=_POLICY)


# ── FakeManimRenderRunner ─────────────────────────────────────────────────────


def test_container_runner_joins_configured_litellm_network():
    runner = ContainerManimRenderRunner(
        lite_llm_base_url="http://litellm:4000",
        lite_llm_api_key="test-key",
        docker_network="omnichannel-learning_default",
    )

    args = runner._build_create_args()

    assert "--network=omnichannel-learning_default" in args
    assert "LITE_LLM_BASE_URL=http://litellm:4000" in args


def test_container_runner_remains_isolated_without_litellm():
    args = ContainerManimRenderRunner()._build_create_args()
    assert "--network=none" in args


def test_container_runner_passes_workflow_telemetry_to_manim_tts():
    runner = ContainerManimRenderRunner(
        lite_llm_base_url="http://litellm:4000",
        lite_llm_api_key="test-key",
    )
    request = _render_request().model_copy(
        update={"workflow_id": "workflow-assembly-123", "task_id": "manim-slot-1"}
    )

    args = runner._build_create_args(request)

    assert "LLM_TELEMETRY_JOB_ID=workflow-assembly-123" in args
    assert "LLM_TELEMETRY_TASK_ID=manim-slot-1" in args
    assert "omnichannel.workflow_id=workflow-assembly-123" in args
    assert "omnichannel.task_id=manim-slot-1" in args
    assert "omnichannel.render_job_id=job-1" in args


def test_container_runner_preserves_voiceover_cache_between_attempts(tmp_path):
    runner = ContainerManimRenderRunner()
    output_dir = tmp_path / "output"
    cache_dir = output_dir / "voiceovers"
    cache_dir.mkdir(parents=True)
    (cache_dir / "audio.wav").write_bytes(b"RIFF-audio")
    (cache_dir / "cache.json").write_text("[]")

    assert runner._capture_voiceover_cache("job-1", output_dir) == 2

    next_input = tmp_path / "next-input"
    assert runner._seed_voiceover_cache("job-1", next_input) == 2
    assert (next_input / "voiceovers" / "audio.wav").read_bytes() == b"RIFF-audio"
    assert (next_input / "voiceovers" / "cache.json").read_text() == "[]"


def test_container_runner_keeps_voiceover_caches_isolated_by_job(tmp_path):
    runner = ContainerManimRenderRunner()
    output_dir = tmp_path / "output"
    cache_dir = output_dir / "voiceovers"
    cache_dir.mkdir(parents=True)
    (cache_dir / "audio.wav").write_bytes(b"job-one-audio")

    runner._capture_voiceover_cache("job-1", output_dir)

    assert runner._seed_voiceover_cache("job-2", tmp_path / "job-2-input") == 0
    assert runner._seed_voiceover_cache("job-1", tmp_path / "job-1-input") == 1


@pytest.mark.asyncio
async def test_container_runner_captures_voiceovers_after_timeout(monkeypatch, tmp_path):
    def fake_run(args, **kwargs):
        if args[:2] == ["docker", "create"]:
            return subprocess.CompletedProcess(args, 0, stdout=b"container-1\n", stderr=b"")
        if args[:3] == ["docker", "start", "--attach"]:
            raise subprocess.TimeoutExpired(args, timeout=1)
        if args[:2] == ["docker", "cp"] and ":/app/output/." in args[2]:
            # The runner supplies a temporary destination; populate that path as
            # docker cp would so this test exercises timeout recovery end to end.
            output_dir = Path(args[3])
            cache_dir = output_dir / "voiceovers"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "audio.wav").write_bytes(b"completed-before-timeout")
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(
        "learning_pipeline.tools.manim_video._render_runner.subprocess.run",
        fake_run,
    )
    runner = ContainerManimRenderRunner(timeout_seconds=1)

    result = await runner.render(_render_request())

    assert result.status == "failure"
    assert result.failure_message == "Container exceeded 1s timeout."
    assert runner._seed_voiceover_cache("abc", tmp_path / "retry-input") == 1
    assert (
        tmp_path / "retry-input" / "voiceovers" / "audio.wav"
    ).read_bytes() == b"completed-before-timeout"


@pytest.mark.asyncio
async def test_fake_runner_success_on_first_attempt():
    runner = FakeManimRenderRunner(fail_attempts=0)
    result = await runner.render(_render_request())
    assert result.status == "success"
    assert result.video_bytes == _FAKE_MP4_BYTES
    assert runner.call_count == 1


@pytest.mark.asyncio
async def test_fake_runner_fails_n_times_then_succeeds():
    runner = FakeManimRenderRunner(fail_attempts=2)
    r1 = await runner.render(_render_request())
    r2 = await runner.render(_render_request())
    r3 = await runner.render(_render_request())
    assert r1.status == "failure"
    assert r2.status == "failure"
    assert r3.status == "success"


@pytest.mark.asyncio
async def test_fake_runner_infrastructure_fail_category():
    runner = FakeManimRenderRunner(fail_attempts=1, fail_category="infrastructure_error")
    result = await runner.render(_render_request())
    assert result.failure_category == "infrastructure_error"


@pytest.mark.asyncio
async def test_fake_runner_no_captions_when_disabled():
    runner = FakeManimRenderRunner(include_captions=False)
    result = await runner.render(_render_request())
    assert result.status == "success"
    assert result.captions_bytes is None


@pytest.mark.asyncio
async def test_fake_runner_duration_from_request():
    runner = FakeManimRenderRunner()
    req = ManimRenderRequest(
        job_id="j",
        idempotency_key="k",
        scene_class="S",
        source_code="from manim import *\n",
        quality="low_quality",
        expected_duration_seconds=90.0,
    )
    result = await runner.render(req)
    assert result.duration_seconds == 90.0


# ── FakeManimNarrationService ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_narration_returns_wav_bytes():
    svc = FakeManimNarrationService()
    wav = await svc.synthesize(text="Hello world", voice_profile="default")
    assert wav[:4] == b"RIFF"
    assert svc.call_count == 1


@pytest.mark.asyncio
async def test_fake_narration_increments_call_count():
    svc = FakeManimNarrationService()
    for _ in range(3):
        await svc.synthesize(text="x", voice_profile=None)
    assert svc.call_count == 3


@pytest.mark.asyncio
async def test_fake_narration_accepts_none_profile():
    svc = FakeManimNarrationService()
    wav = await svc.synthesize(text="test", voice_profile=None)
    assert len(wav) > 44
