# Langfuse observability

The local Langfuse deployment receives every model request routed through
LiteLLM. No application-level decorators are required for basic model, prompt,
response, token, cost, latency, and error visibility.

## Start

```bash
docker compose --profile observability up -d
```

Open <http://localhost:3000>. With the local development defaults, sign in as
`admin@local.invalid` using `local-langfuse-password`.

For shared or deployed environments, replace every `LANGFUSE_*` development
credential in `.env`. In particular, generate `LANGFUSE_ENCRYPTION_KEY` with:

```bash
openssl rand -hex 32
```

The `observability` profile runs Langfuse web, its ingestion worker, PostgreSQL,
Redis, and ClickHouse. It reuses the repository's existing MinIO service and
creates a dedicated `langfuse` bucket.

## Integration boundary

`litellm/config.yaml` enables the `langfuse_otel` callback. The LiteLLM service
receives the Langfuse public key, secret key, and OTLP host from Compose. This
captures all current model aliases, including authoring, planning, commissioning,
Manim generation, embeddings, and speech synthesis, as long as the provider call
passes through LiteLLM.

Application calls add LiteLLM metadata at the gateway boundary. Each UI job uses
one deterministic Langfuse `trace_id` and its visible job ID as the Langfuse
`session_id`; individual observations also carry `job_id`, `workflow_id`, and
`task_id`. Internal `planning-` and `workflow-` prefixes are removed so planning,
authoring, media generation, and speech costs group under the same UI job.

The functional model alias is recorded as `generation_name` and `model_alias`.
Langfuse's Model column may still show the underlying provider model; use the
generation name to distinguish functions such as `format-selection`,
`manim-scene-generation.repair`, and `elearning-course-authoring.review`.
