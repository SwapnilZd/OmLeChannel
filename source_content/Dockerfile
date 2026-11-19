FROM python:3.12-slim AS base

WORKDIR /app

COPY source_content/certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

RUN apt-get update \
    && apt-get install --no-install-recommends -y fonts-liberation libgl1 libreoffice-impress tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY source_content/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN mkdir -p "$TIKTOKEN_CACHE_DIR"
COPY source_content/tiktoken-cache/o200k_base.tiktoken /opt/tiktoken-cache/fb374d419588a4632f3f557e76b4b70aebbca790
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

RUN docling-tools models download --output-dir /opt/docling-models layout tableformer

ENV DOCLING_SERVE_ARTIFACTS_PATH=/opt/docling-models
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV PYTHONUNBUFFERED=1

COPY api/src/ ./src/
COPY llm_gateway/ ./llm_gateway/

FROM base AS test

COPY source_content/test-requirements.txt ./test-requirements.txt
RUN pip install --no-cache-dir -r test-requirements.txt
COPY tests/ ./tests/
COPY examples/poc2_samples/ ./examples/poc2_samples/
RUN python tests/source_content/fixtures/generate_fixtures.py \
    --output-dir tests/source_content/fixtures/generated

FROM base AS runtime

CMD ["python", "-m", "src.source_ingestion.worker"]
