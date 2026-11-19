# Build context is the repo root (see docker-compose.yml) so the shared
# rlo_schema package and brand tokens can be copied into the image.
FROM python:3.12-slim

WORKDIR /app

COPY pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rlo_schema/ ./rlo_schema/
COPY llm_gateway/ ./llm_gateway/
COPY brand/ ./brand/
COPY pipeline/src/ ./src/
COPY pipeline/components/ ./components/
COPY pipeline/tests/ ./tests/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/src

ENTRYPOINT ["python", "src/generate.py"]
