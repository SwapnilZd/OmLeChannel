# learning_pipeline — deterministic workflow execution layer
#
# Targets:
#   base    — runtime package only (pydantic); no test tools
#   test    — extends base with pytest + pytest-asyncio; copies tests and examples
#   runtime — same as base; explicit alias used in compose for one-shot CLI runs

FROM docker:cli AS docker-cli

FROM python:3.12-slim AS base

WORKDIR /app

COPY source_content/certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Docker CLI — needed by ContainerManimRenderRunner to launch isolated render containers
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

# Install the package in editable mode so src/ is the live source
COPY pyproject.toml ./
COPY src/ ./src/
COPY rlo_schema/ ./rlo_schema/
COPY llm_gateway/ ./llm_gateway/
COPY poc_auth/ ./poc_auth/

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1

# ── test target ───────────────────────────────────────────────────────────────
FROM base AS test

RUN pip install --no-cache-dir -e '.[test]'

COPY tests/ ./tests/
COPY examples/ ./examples/
COPY course-definitions/ ./course-definitions/
# Compatibility tests exercise the existing feasibility renderer's CLI without
# making a TTS request. Keep its OpenAI-compatible client factory beside it so
# Python resolves the local import when the script is invoked by path.
COPY pipeline/src/podcast_renderer.py pipeline/src/model_gateway.py pipeline/src/renderer.py pipeline/src/schema.py ./pipeline/src/
COPY pipeline/components/ ./pipeline/components/
COPY brand/ ./brand/
COPY manim/ ./manim/

# ── runtime target ────────────────────────────────────────────────────────────
FROM base AS runtime

COPY examples/ ./examples/
# The e-learning bundle assembler bridges to the established renderer, which
# is intentionally not an installed package. Keep its runtime files at the
# repository-relative paths expected by _pipeline_bridge.py.
COPY pipeline/src/renderer.py pipeline/src/schema.py ./pipeline/src/
COPY pipeline/components/ ./pipeline/components/
COPY brand/ ./brand/
# ManimGenerationController resolves templates through _manim_bridge.py, which
# expects manim/ at the repository root — required by workflow-worker-real-manim.
COPY manim/ ./manim/
