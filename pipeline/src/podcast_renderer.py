"""
Render a podcast delivery spec to a single WAV file.

One TTS call per spoken line → distinct voice per speaker → stitched output.
Respects short conversational pause durations from the spec. Assessment checks
are rendered as Expert–Host dialogue rather than listener-response silence.
Writes a costs.json usage summary alongside the WAV (LiteLLM does not track audio spend).

Usage:
  docker compose run --rm pipeline python src/podcast_renderer.py \
    --spec /course-definitions/rlo-chess-pawn-movement/podcast/spec.json
"""

import argparse
import io
import json
import os
import sys
import wave
from pathlib import Path

from openai import OpenAI

from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    load_lite_llm_settings,
)
from model_gateway import make_openai_client

DEFAULT_PAUSE_BETWEEN_LINES = 0.35  # seconds of silence between every line
MAX_CONVERSATIONAL_PAUSE_SECONDS = 1.0

VOICE_MAP = {
    "Host": os.environ.get("PODCAST_HOST_VOICE", "Aoede"),
    "Expert": os.environ.get("PODCAST_EXPERT_VOICE", "Charon"),
}

# Match values set in litellm/config.yaml for podcast-speech-synthesis.
# Google bills TTS input per character; we treat 4 chars ≈ 1 token for cost estimation
INPUT_COST_PER_TOKEN  = float(os.environ.get("TTS_INPUT_COST_PER_TOKEN",  "0.000001"))   # $1/M
OUTPUT_COST_PER_TOKEN = float(os.environ.get("TTS_OUTPUT_COST_PER_TOKEN", "0.00002"))    # $20/M
CHARS_PER_TOKEN = 4


def _make_silence(seconds: float, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    n_frames = int(sample_rate * seconds)
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * n_frames * channels * sample_width)
    return buf.getvalue()


def _concat_wavs(segments: list[bytes]) -> bytes:
    buf = io.BytesIO()
    params_set = False
    with wave.open(buf, "wb") as out:
        for seg in segments:
            with wave.open(io.BytesIO(seg)) as w:
                if not params_set:
                    out.setparams(w.getparams())
                    params_set = True
                out.writeframes(w.readframes(w.getnframes()))
    return buf.getvalue()


def _collect_lines(spec: dict) -> list[dict]:
    """Flatten script + assessment + outro into an ordered list of spoken items."""
    items = []

    for item in spec.get("script", []):
        if item["type"] in ("Host", "Expert"):
            items.append({
                "type": item["type"],
                "line": item["line"],
                "pause_after": min(
                    float(item.get("cognitive_pause_duration") or 0),
                    MAX_CONVERSATIONAL_PAUSE_SECONDS,
                ),
                "id": item.get("id", ""),
            })

    assessment = spec.get("assessment", {})
    if assessment:
        expert_prompt = assessment.get("expert_prompt")
        if expert_prompt:
            items.append({
                "type": "Expert",
                "line": expert_prompt,
                "pause_after": 0,
                "id": f"{assessment.get('id', 'assessment')}-expert-prompt",
            })
        elif assessment.get("host_prompt"):
            items.append({
                "type": "Host",
                "line": assessment["host_prompt"],
                "pause_after": 0,
                "id": f"{assessment.get('id', 'assessment')}-host-prompt",
            })
        host_response = assessment.get("host_response")
        if host_response:
            items.append({
                "type": "Host",
                "line": host_response,
                "pause_after": 0,
                "id": f"{assessment.get('id', 'assessment')}-host-response",
            })
        reveal = assessment.get("expert_reveal", {})
        if reveal.get("type") in ("Host", "Expert"):
            items.append({
                "type": reveal["type"],
                "line": reveal["line"],
                "pause_after": min(
                    float(reveal.get("cognitive_pause_duration") or 0),
                    MAX_CONVERSATIONAL_PAUSE_SECONDS,
                ),
                "id": reveal.get("id", "assessment-reveal"),
            })

    for item in spec.get("outro", []):
        if item["type"] in ("Host", "Expert"):
            items.append({
                "type": item["type"],
                "line": item["line"],
                "pause_after": min(
                    float(item.get("cognitive_pause_duration") or 0),
                    MAX_CONVERSATIONAL_PAUSE_SECONDS,
                ),
                "id": item.get("id", ""),
            })

    return items


def _wav_duration_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / w.getframerate()


def render(spec_path: Path, out_dir: Path, model: str, client: OpenAI) -> tuple[Path, dict]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    lines = _collect_lines(spec)
    out_dir.mkdir(parents=True, exist_ok=True)

    segments: list[bytes] = []
    line_usage: list[dict] = []

    for i, item in enumerate(lines, 1):
        voice = VOICE_MAP.get(item["type"], "Aoede")
        text = item["line"]
        label = f"[{item['id']}] {item['type']} ({voice})"
        preview = text[:70].replace("\n", " ")
        print(f"  {i:>2}/{len(lines)}  {label}")
        print(f"        {preview}{'…' if len(text) > 70 else ''}")

        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="wav",
            extra_body={
                "metadata": build_litellm_metadata(
                    model,
                    operation="synthesize",
                    job_id=str(spec.get("job_id") or spec.get("deliverable_id") or "") or None,
                    task_id=item.get("id") or None,
                )
            },
            extra_headers=build_langfuse_headers(
                model,
                operation="synthesize",
                job_id=str(spec.get("job_id") or spec.get("deliverable_id") or "") or None,
                task_id=item.get("id") or None,
            ),
        )
        audio_bytes = response.content
        segments.append(audio_bytes)

        pause_seconds = (item.get("pause_after") or 0) + DEFAULT_PAUSE_BETWEEN_LINES
        segments.append(_make_silence(pause_seconds))

        chars = len(text)
        input_tokens  = chars / CHARS_PER_TOKEN
        audio_duration = _wav_duration_seconds(audio_bytes)
        # Estimate output tokens from audio: 24kHz 16-bit mono → 24000 frames/s × 2 bytes = 48000 bytes/s
        output_tokens = (len(audio_bytes) / 48000) * 1000 / CHARS_PER_TOKEN
        line_usage.append({
            "id": item["id"],
            "speaker": item["type"],
            "voice": voice,
            "input_chars": chars,
            "input_tokens_est": round(input_tokens, 1),
            "audio_duration_s": round(audio_duration, 2),
            "input_cost_usd": round(input_tokens * INPUT_COST_PER_TOKEN, 6),
            "output_cost_usd": round(output_tokens * OUTPUT_COST_PER_TOKEN, 6),
        })

    audio = _concat_wavs(segments)
    out_path = out_dir / f"{spec['id']}.wav"
    out_path.write_bytes(audio)

    total_chars        = sum(u["input_chars"]      for u in line_usage)
    total_input_cost   = sum(u["input_cost_usd"]   for u in line_usage)
    total_output_cost  = sum(u["output_cost_usd"]  for u in line_usage)
    total_duration     = sum(u["audio_duration_s"] for u in line_usage)

    usage_summary = {
        "spec_id": spec["id"],
        "model": model,
        "lines": len(line_usage),
        "total_input_chars": total_chars,
        "total_audio_duration_s": round(total_duration, 1),
        "total_input_cost_usd":  round(total_input_cost,  6),
        "total_output_cost_usd": round(total_output_cost, 6),
        "total_cost_usd":        round(total_input_cost + total_output_cost, 6),
        "pricing": {
            "input_cost_per_token":  INPUT_COST_PER_TOKEN,
            "output_cost_per_token": OUTPUT_COST_PER_TOKEN,
            "chars_per_token":       CHARS_PER_TOKEN,
            "note": "Output tokens estimated from audio byte length at 24kHz 16-bit mono",
        },
        "line_breakdown": line_usage,
    }

    return out_path, usage_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a podcast delivery spec to WAV.")
    parser.add_argument("--spec", required=True, help="Path to podcast spec JSON file.")
    parser.add_argument("--out", default=None, help="Output directory (default: /generated/podcast/<spec-id>).")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"Error: spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    spec_id = json.loads(spec_path.read_text())["id"]
    out_dir = Path(args.out).resolve() if args.out else Path("/generated/podcast") / spec_id

    connection = load_lite_llm_settings()
    client = make_openai_client(
        base_url=connection.base_url,
        api_key=connection.api_key,
    )

    print(f"\n[podcast_renderer] Spec:  {spec_path}")
    print(f"[podcast_renderer] Model: {ModelAlias.PODCAST_SPEECH_SYNTHESIS}")
    print(f"[podcast_renderer] Out:   {out_dir}")
    print(f"[podcast_renderer] Voices: Host={VOICE_MAP['Host']}  Expert={VOICE_MAP['Expert']}\n")

    out_path, usage = render(
        spec_path, out_dir, ModelAlias.PODCAST_SPEECH_SYNTHESIS, client
    )

    costs_path = out_dir / f"{spec_id}.costs.json"
    costs_path.write_text(json.dumps(usage, indent=2), encoding="utf-8")

    print(f"\n✓ Done — {out_path}  ({usage['total_audio_duration_s']/60:.1f} min)")
    print(f"  Input:  {usage['total_input_chars']:,} chars  ${usage['total_input_cost_usd']:.4f}")
    print(f"  Output: {usage['total_audio_duration_s']:.0f}s audio  ${usage['total_output_cost_usd']:.4f}")
    print(f"  Total:  ${usage['total_cost_usd']:.4f}")
    print(f"  Usage → {costs_path}")


if __name__ == "__main__":
    main()
