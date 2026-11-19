# Podcast Renderer Migration Plan

This document maps the existing feasibility renderer at
`pipeline/src/podcast_renderer.py` to the target executor architecture and
records why the real integration is deferred until after Phase 4.

---

## Current responsibilities of `podcast_renderer.py`

The script does the following in one monolithic pass:

| Step | Code location |
|---|---|
| Read and parse the podcast delivery spec | `render()` |
| Collect all spoken lines (script, assessment, outro) | `_collect_lines()` |
| Select speaker voice from `VOICE_MAP` | `render()` |
| Make one TTS call per line via the OpenAI client | `render()` |
| Insert configurable pause between lines | `render()` (uses `_make_silence`) |
| Concatenate all WAV segments into one file | `render()` (uses `_concat_wavs`) |
| Calculate usage and estimated cost per line | `render()` |
| Write the final WAV and a `costs.json` summary | `render()` / `main()` |

The `main()` entry point reads CLI arguments, validates the spec path, constructs
an OpenAI-compatible client using the shared LiteLLM settings loader, and calls
`render()`.

---

## Mapping to the target executor architecture

The `BuildPlan` separates these responsibilities across two executor types.

### `SpeechExecutor` (maps to `speech.synthesize` tasks)

One executor call per scene.  Replaces the per-line TTS loop inside `render()`.

**Reusable from the renderer:**
- None directly — the real executor will call the same `client.audio.speech.create`
  endpoint, but the multi-line loop becomes the caller's responsibility (either
  by batching lines before calling the executor, or by running one speech task
  per line).

**Code to adapt:**
```python
# From podcast_renderer.render()
response = client.audio.speech.create(
    model=model,
    voice=voice,
    input=text,
    response_format="wav",
)
audio_bytes = response.content
```

The `OpenAI` client must be injected into `RealSpeechExecutor` rather than
constructed from environment variables inside the executor.  The executor must
not read `os.environ` directly.

**Inputs the real executor will accept (from TaskSpec inputs):**
```
scene_id    — which scene's narration to synthesise
script_text — pre-rendered narration text (or resolved from scene_id)
voice       — TTS voice name
speaker     — Host / Expert discriminator
```

**Outputs the real executor will return:**
```
audio_file        — URI of the stored WAV segment
duration_seconds  — audio length (from _wav_duration_seconds)
usage             — input chars, audio duration, cost estimate
```

---

### `AudioAssemblyExecutor` (maps to `audio.assemble` tasks)

One executor call per podcast.  Replaces the concatenation, pause-insertion,
and cost-aggregation logic inside `render()`.

**Directly reusable from the renderer (pure functions, no I/O):**

| Function | Description |
|---|---|
| `_make_silence(seconds, ...)` | Generates PCM silence as a WAV bytes object |
| `_concat_wavs(segments)` | Concatenates a list of WAV bytes objects into one |
| `_wav_duration_seconds(wav_bytes)` | Returns the duration of a WAV in seconds |

These three functions have no external dependencies and can be moved into a
shared `learning_pipeline.audio_utils` module or imported directly from a
`RealAudioAssemblyExecutor`.

**Inputs the real executor will accept:**
```
segment_1     — audio_file URI from speech-segment-1 TaskResult
segment_2     — audio_file URI from speech-segment-2 TaskResult
pause_seconds — silence duration between segments (optional, with default)
```

**Outputs the real executor will return:**
```
podcast_file   — URI of the assembled WAV or MP3
costs_uri      — URI of the aggregated costs JSON
duration_seconds
total_cost_usd
```

---

## Why `podcast_renderer.py` must not be called by `WorkflowRunner`

1. **The CLI is an integration boundary, not a library.**  `main()` reads
   environment variables, validates file paths, constructs an `OpenAI` client,
   writes files to fixed paths, and prints human-readable output.  None of
   these are appropriate inside a deterministic runner.

2. **The monolithic script cannot be partially invoked.**  There is no way to
   call only the TTS step or only the concatenation step without executing the
   whole pipeline.

3. **Credential management differs.** The CLI reads the shared LiteLLM settings
   at its composition root. Real executors should receive a pre-constructed
   client via dependency injection so the runner can remain credential-free.

4. **Output paths are hard-coded.**  The script writes to
   `/generated/podcast/<spec_id>/` by default.  Real executors should return
   URIs and let a storage adapter handle writing.

---

## Difference between the podcast delivery spec and the build-plan fixture

The existing delivery spec (`spec.json`) used by `podcast_renderer.py` contains
fully rendered narration (the actual text of each spoken line).

The Phase 4 `BuildPlan` fixture at `examples/reference/podcast/build_plan.json`
uses `scene_id` as the speech task input — a reference to a modality scene
rather than pre-rendered text.

The future `RealSpeechExecutor` must either:
- Accept a `script_text` input (pre-rendered by a content generation step), or
- Look up the scene from a `ModalityPlan` to extract narration text.

The cleaner long-term design is to add a content-generation task to the DAG
that produces a `script_text` output consumed by each speech task.  This keeps
the speech executor responsible only for TTS and not for content extraction.

---

## Why real integration is deferred

Phase 4 establishes the deterministic execution spine — scheduling, retry,
state persistence, and the executor protocol — without any external calls.

The fake executors prove the DAG wiring, concurrency behaviour, and output
resolution.  They can be replaced by real executors without changing:

- `WorkflowRunner`
- `ExecutorRegistry`
- `BuildPlan` structure
- `TaskResult` structure
- Input resolution
- Dependency scheduling

Real TTS integration requires:
- A running LiteLLM proxy and the shared gateway API key
- Configurable client injection
- Audio storage (local path, S3 URI, or equivalent)
- A content-generation step that produces `script_text` from `scene_id`

These are planned for the next tool-integration phase.
