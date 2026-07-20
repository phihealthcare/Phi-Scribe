# syntax=docker/dockerfile:1.7
# Backend (Flask + ML pipeline: Whisper, Sortformer diarization, LLM post-edit).
#
# GPU: no CUDA base image is needed — the `torch` wheel pulled in by
# requirements.txt already bundles its own CUDA runtime. On the host (or cloud
# GPU node) install the NVIDIA Container Toolkit and run with `--gpus all`
# (docker-compose.yml already requests it); the container then sees the GPU
# via nvidia-container-toolkit without any CUDA toolkit baked into the image.
# Set WHISPER_FASTER_DEVICE=cpu / SORTFORMER_DEVICE=cpu in .env to run
# CPU-only instead — same image, no rebuild needed.
#
# Python 3.12, not the local .venv's 3.14: nemo_toolkit[asr]'s dependency
# constraints force pip to resolve an older numba that has no prebuilt wheel
# for 3.14 and refuses to build from source on it ("Cannot install on Python
# version 3.14; only versions >=3.10,<3.14 are supported"). Must be >=3.12,
# though — app/services/soap_draft.py uses a multi-line f-string expression
# (PEP 701 grammar), a SyntaxError on 3.11 and earlier.
FROM python:3.12-slim

# ffmpeg: audio normalize/loudness (app/services/normalize.py, loudness.py)
# libsndfile1: required by soundfile (noisereduce)
# sox/libsox-dev: audio I/O used by nemo_toolkit[asr] (Sortformer diarization)
# build-essential/git: some of nemo_toolkit's dependency tree builds from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    sox \
    libsox-dev \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# torch + nemo_toolkit[asr] pull several GB of wheels — a BuildKit cache mount
# keeps downloaded wheels across builds (survives a flaky-network retry
# without re-fetching everything) without baking pip's cache into the image
# layer itself.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 100 -r requirements.txt gunicorn

COPY . .

RUN mkdir -p uploads/processed \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p /home/appuser/.cache \
    && chown -R appuser:appuser /app /home/appuser/.cache
USER appuser

ENV FLASK_ENV=production \
    PORT=5000 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import os,socket; socket.create_connection(('localhost', int(os.environ.get('PORT', 5000))), timeout=3).close()"

# Long timeout: SOAP/ASR-fix LLM calls and diarization can run for minutes on
# a single request (see LLM_TIMEOUT_SECONDS in .env.example).
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS:-2} --timeout ${GUNICORN_TIMEOUT:-1800} run:app"]
