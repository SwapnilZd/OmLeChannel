# Build context is the repo root (see docker-compose.yml) so the shared
# rlo_schema package can be copied into the image.
FROM python:3.12-slim AS base
WORKDIR /app
COPY source_content/certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN mkdir -p "$TIKTOKEN_CACHE_DIR"
COPY source_content/tiktoken-cache/o200k_base.tiktoken /opt/tiktoken-cache/fb374d419588a4632f3f557e76b4b70aebbca790
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"
COPY rlo_schema/ ./rlo_schema/
COPY llm_gateway/ ./llm_gateway/
COPY poc_auth/ ./poc_auth/
COPY api/src/ ./src/
COPY api/templates/ ./templates/
COPY api/static/ ./static/
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

FROM base AS test
COPY api/test-requirements.txt ./test-requirements.txt
RUN pip install --no-cache-dir -r test-requirements.txt
COPY litellm/ ./litellm/
COPY tests/ ./tests/
COPY api/tests/ ./api/tests/
COPY examples/poc2_samples/ ./examples/poc2_samples/
RUN python tests/source_content/fixtures/generate_fixtures.py \
    --output-dir tests/source_content/fixtures/generated

FROM base AS runtime
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
