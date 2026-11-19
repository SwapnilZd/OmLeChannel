# Tool Abstraction Architecture — Phase 7

## Layers

```
Planner  →  ToolManifest        (no executor, no credentials, no provider detail)
Compiler →  ProductionToolCatalog  (maps capability → task_type)
Worker   →  ExecutorRegistry    (maps task_type → concrete executor)
Provider →  SpeechClient        (provider-specific, injected at startup)
Storage  →  ArtifactStore       (bytes out of the workflow state channel)
```

Each layer is separated by a typed boundary. Nothing crosses without an explicit conversion step.

---

## Capability vs task type vs executor

| Term | What it names | Who uses it |
|---|---|---|
| **capability** | A named tool function (`speech.synthesize`) | Planner in `ProductionJob.capability` |
| **task_type** | The execution slot a worker handles | Worker `ExecutorRegistry`, `BuildTask.task_type` |
| **executor** | The concrete object that implements the slot | Worker process only |

Currently capability == task_type for all registered tools. They are stored separately so future versions can split or alias them without changing the planner contract.

---

## Why podcast is a workflow, not one tool

A podcast episode requires two conceptually separate task types:

1. **speech.synthesize** — one spoken segment → one WAV file (parallelisable)
2. **audio.assemble** — N WAV files → one assembled deliverable (sequential, depends on all speech tasks)

A `BuildPlan` is a DAG. The planner emits one `speech.synthesize` task per line and one `audio.assemble` task that depends on all of them. This makes the dependency graph explicit and the two tasks independently testable.

---

## Manifest — what the planner sees

```python
ToolManifest(
    capability="speech.synthesize",
    contract_version="1.0",
    task_type="speech.synthesize",
    description="...",
    supported_modalities=(Modality.PODCAST, Modality.VIDEO, Modality.ELEARNING),
    input_schema=SpeechSynthesisInput.model_json_schema(),   # derived from Pydantic
    output_schema=SpeechSynthesisOutput.model_json_schema(), # derived from Pydantic
    constraints={"max_text_length_chars": 5_000, ...},
)
```

The manifest is a frozen Pydantic model. It serialises cleanly to JSON and contains no executors, no credentials, no provider URLs, and no implementation detail the planner does not need.

`ProductionToolCatalog.planner_view(modality)` returns a sorted tuple of manifests for the requested modality. The sorted order is deterministic so planners produce stable plans across restarts.

---

## Compiler mapping

`ProductionCompiler` calls `catalog.task_type_for(capability)` for each `ProductionJob`. This is the only place capability names are converted to task types. The compiler accepts any object with that method, so tests can pass a simple `CapabilityCatalog` dict-wrapper or a full `ProductionToolCatalog` without changing the compiler.

---

## Fake vs real executor selection

`EXECUTOR_MODE` environment variable controls which registry the worker builds at startup.

```
EXECUTOR_MODE=fake  →  build_fake_registry()
                        FakeSpeechExecutor      (validates input contract, returns fake:// URI)
                        FakeAudioAssemblyExecutor

EXECUTOR_MODE=real  →  build_real_registry(settings)
                        RealSpeechExecutor      (calls OpenAISpeechClient, stores real WAV)
                        FakeAudioAssemblyExecutor   (Phase 8 stub)
```

`FakeSpeechExecutor` validates `SpeechSynthesisInput` and returns a `SpeechSynthesisOutput`-conformant dict with a `fake://` URI. This ensures the same `BuildPlan` runs in both modes without modification.

The API process never reads `EXECUTOR_MODE`. Only the worker that handles execution receives it. API never receives TTS credentials.

---

## Artifact storage

Raw audio bytes never enter PostgreSQL, `BuildPlan`, `TaskResult`, or API responses.

```
RealSpeechExecutor
  → calls SpeechClient.synthesize() → bytes
  → calls ArtifactStore.put_bytes(namespace, name, data, media_type) → ArtifactRef
  → stores ArtifactRef.uri ("artifact://speech/wf-id/task-id.wav") in task output
```

`FileArtifactStore` writes atomically (`.tmp` then `os.replace`), prevents path traversal by resolving the full path and asserting it stays under the root, and returns the SHA-256 and size with the reference.

The `artifact://` URI scheme is internal. A future Phase can replace `FileArtifactStore` with a cloud-backed implementation without changing executors or the workflow state model.

---

## Real-mode credential isolation

Only the `workflow-worker-real` Docker service (started with `--profile real-tools`) receives:

```
LITE_LLM_BASE_URL / LITE_LLM_API_KEY  — shared model-gateway connection
PODCAST_HOST_VOICE / PODCAST_EXPERT_VOICE
TTS_INPUT_COST_PER_TOKEN / TTS_OUTPUT_COST_PER_TOKEN
ARTIFACT_STORE_ROOT
```

The default `workflow-worker` and `workflow-api` services have none of these variables.

---

## Test isolation

All tests run with fake executors. No test makes a live TTS call.

- `FakeSpeechClient` (in `test_executor.py`) injects pre-built WAV bytes.
- `_make_wav()` generates a minimal valid WAV in memory using the `wave` stdlib module.
- `FileArtifactStore` is tested with `tmp_path` (pytest fixture).
- Real-mode path is tested only up to registry construction; `OpenAISpeechClient` is never instantiated in tests.

---

## Phase 8 remaining work

- `FakeAudioAssemblyExecutor` is a stub — it returns a `podcast_file` URI but does no WAV concatenation.
- `audio_utils.make_silence()` and `concat_wavs()` are implemented but not wired to any executor.
- A real `audio.assemble` executor needs to: retrieve segment WAVs from `ArtifactStore`, concatenate with silence padding, and store the result as a new artifact.
- Cloud `ArtifactStore` implementations (GCS, S3) are not yet written.
