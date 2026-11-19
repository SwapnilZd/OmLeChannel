# Build context MUST be the repository root — this image copies llm_gateway/,
# which lives outside manim/ and is unreachable from a ./manim context.
#
#   docker build -f manim/Dockerfile -t manim-renderer:latest .
#   docker compose --profile real-manim build manim-renderer-image
FROM python:3.12-slim

# Manim needs Cairo (text/vector rendering), Pango (font layout),
# and FFmpeg (video encoding). Sox is used by manim-voiceover for
# audio processing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libcairo2-dev \
    libpango1.0-dev \
    ffmpeg \
    sox \
    fonts-open-sans \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY manim/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manim/generate_course_video.py .
COPY manim/tts_service.py .
COPY manim/voiceover_prefetch.py .
COPY llm_gateway/ llm_gateway/
COPY manim/templates/ templates/
# Approved Deloitte tagline outro, appended after successful renders
# unless MANIM_BRAND_OUTRO=off (see _append_brand_outro).
COPY ["brand/outro/StaticOutro-TMP-External-Black-4K-Short.mp4", "brand/outro.mp4"]

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "generate_course_video.py"]
