"""
Thin compatibility wrapper — translates a legacy video spec.json into
AvatarVideoRenderInput and submits it via the learning_pipeline provider layer.

Legacy behaviour preserved:
  --spec   path to video/spec.json
  --out    output directory (default: /generated/video/<spec-id>)
  --scene  single scene_id string to render in isolation (cheaper for testing)

New behaviour:
  Avatar and voice IDs are resolved at runtime via the HeyGen profile registry.
  The actual API call uses AsyncHeyGenClient + RealAvatarVideoExecutor, which
  checkpoints submitted jobs to disk so interrupted runs can resume without
  re-billing.

Environment variables (all required for real execution):
  HEYGEN_API_KEY                  — HeyGen REST API key
  HEYGEN_AVATAR_PROFILE_DEFAULT_INSTRUCTOR_ID   — avatar ID for default_instructor
  HEYGEN_VOICE_PROFILE_DEFAULT_INSTRUCTOR_ID    — voice ID for default_instructor
  HEYGEN_OPERATION_STORE_ROOT     — checkpoint directory (default: /tmp/heygen-ops)
  HEYGEN_ASSET_CACHE_ROOT         — asset dedup cache root (default: /tmp/heygen-cache)
  HEYGEN_POLL_INTERVAL            — polling interval seconds (default: 15)
  HEYGEN_MAX_POLL_WAIT            — max poll wait seconds (default: 1800)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Resolve sys.path so this script can be run directly from the repo root.
_REPO_ROOT = Path(__file__).parent.parent.resolve()
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass  # python-dotenv is optional for standalone execution


def _spec_scenes_to_render_inputs(
    spec: dict,
    scene_filter: str | None = None,
) -> list[dict]:
    """Convert legacy spec scenes to AvatarVideoScene dicts."""
    raw_scenes: list[dict] = spec.get("scenes", [])
    outro = spec.get("outro", {})
    if outro.get("avatar_script"):
        raw_scenes = [*raw_scenes, {**outro, "scene_id": "outro"}]

    results = []
    for scene in raw_scenes:
        sid = str(scene.get("scene_id", "unknown"))
        if scene_filter is not None and sid != scene_filter:
            continue

        script = (
            scene.get("avatar_script")
            or scene.get("script")
            or scene.get("narration", "")
        ).strip()

        bg = scene.get("background")
        if bg and isinstance(bg, dict) and bg.get("kind") == "color":
            background = bg
        else:
            background = {"kind": "color", "color": "#1A1A2E"}

        results.append(
            {
                "scene_id": sid,
                "source_scene_ids": [sid],
                "title": scene.get("title", sid),
                "script": script,
                "background": background,
                "estimated_duration_seconds": float(
                    scene.get("duration_hint") or scene.get("estimated_duration_seconds") or 30
                ),
            }
        )
    return results


def _build_render_input(spec: dict, scenes: list[dict]) -> dict:
    return {
        "deliverable_id": spec.get("id", "legacy-video"),
        "scenes": scenes,
        "avatar": {"profile": "default_instructor"},
        "voice": {
            "profile": "default_instructor",
            "speed": float(os.environ.get("HEYGEN_SPEED", "1.0")),
        },
        "dimensions": {"width": 1280, "height": 720},
        "captions": False,
    }


async def _run(render_input: dict, out_dir: Path, spec_id: str) -> None:
    from learning_pipeline.artifact_store import FileArtifactStore
    from learning_pipeline.execution import ExecutionContext
    from learning_pipeline.providers.heygen.asset_cache import ProviderAssetCache
    from learning_pipeline.providers.heygen.client import AsyncHeyGenClient
    from learning_pipeline.providers.heygen.mapper import HeyGenSceneMapper
    from learning_pipeline.providers.heygen.operation_store import FileExternalOperationStore
    from learning_pipeline.tools.avatar_video.executor_real import RealAvatarVideoExecutor
    from learning_pipeline.tools.avatar_video.pricing import load_pricing_config
    from learning_pipeline.tools.avatar_video.profiles import load_profile_settings

    api_key = os.environ.get("HEYGEN_API_KEY", "")
    if not api_key:
        print("Error: HEYGEN_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    _user_cache = Path.home() / ".cache" / "heygen"
    op_root = Path(os.environ.get("HEYGEN_OPERATION_STORE_ROOT", str(_user_cache / "ops")))
    cache_root = Path(os.environ.get("HEYGEN_ASSET_CACHE_ROOT", str(_user_cache / "assets")))
    artifact_root = out_dir / "artifacts"
    poll_interval = float(os.environ.get("HEYGEN_POLL_INTERVAL", "15"))
    max_poll_wait = float(os.environ.get("HEYGEN_MAX_POLL_WAIT", "1800"))

    client = AsyncHeyGenClient(api_key=api_key)
    profile_registry = load_profile_settings()
    pricing = load_pricing_config()
    executor = RealAvatarVideoExecutor(
        client=client,
        artifact_store=FileArtifactStore(artifact_root),
        profile_registry=profile_registry,
        operation_store=FileExternalOperationStore(op_root),
        asset_cache=ProviderAssetCache(cache_root),
        scene_mapper=HeyGenSceneMapper(),
        pricing=pricing,
        poll_interval=poll_interval,
        max_poll_wait=max_poll_wait,
    )

    workflow_id = f"legacy-{spec_id}"
    ctx = ExecutionContext(
        workflow_id=workflow_id,
        task_id="render-video",
        attempt=1,
        inputs=render_input,
    )

    print(f"\n[video_renderer] Submitting {len(render_input['scenes'])} scene(s) to HeyGen…")
    result = await executor.execute(ctx)

    # Download MP4 from artifact store to the output directory
    from learning_pipeline.artifact_store import FileArtifactStore as _FAS
    store = _FAS(artifact_root)
    mp4_bytes = await store.get_bytes(result["video_uri"])
    mp4_path = out_dir / f"{spec_id}.mp4"
    mp4_path.write_bytes(mp4_bytes)
    print(f"\n✓ MP4 saved:     {mp4_path}")

    if result.get("cost_report_uri"):
        cost_bytes = await store.get_bytes(result["cost_report_uri"])
        costs_path = out_dir / "costs.json"
        costs_path.write_bytes(cost_bytes)
        print(f"✓ Costs saved:   {costs_path}")

    duration = result.get("duration_seconds")
    if duration:
        print(f"✓ Duration:      {duration:.1f}s ({duration / 60:.1f} min)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a video spec to MP4 via HeyGen (pipeline-aware wrapper)."
    )
    parser.add_argument("--spec", required=True, help="Path to video spec JSON.")
    parser.add_argument("--out", default=None, help="Output directory.")
    parser.add_argument(
        "--scene",
        default=None,
        help="Render a single scene by scene_id string (cheaper for testing).",
    )
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"Error: spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_id = spec.get("id", spec_path.stem)

    out_dir = (
        Path(args.out).resolve()
        if args.out
        else Path("/generated/video") / spec_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    scenes = _spec_scenes_to_render_inputs(spec, scene_filter=args.scene)
    if not scenes:
        suffix = f" matching scene_id={args.scene!r}" if args.scene else ""
        print(f"Error: no scenes found{suffix}", file=sys.stderr)
        sys.exit(1)

    render_input = _build_render_input(spec, scenes)

    print(f"\n[video_renderer] Spec:   {spec_path}")
    print(f"[video_renderer] Out:    {out_dir}")
    print(f"[video_renderer] Scenes: {len(scenes)}")
    for s in scenes:
        print(f"  {s['scene_id']}: {s['title']!r} (~{s['estimated_duration_seconds']:.0f}s)")

    asyncio.run(_run(render_input, out_dir, spec_id))


if __name__ == "__main__":
    main()
