# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_OFFLINE=0

WORKDIR /app

# Zaleznosci systemowe (libpq dla asyncpg, gcc na czas budowy bcrypt)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
 && rm -rf /var/lib/apt/lists/*

# ---------- Warstwa pip ----------
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------- Pre-download modeli DLP ----------
# spaCy: polski model dla NER (imie, nazwisko, organizacja, lokalizacja)
RUN python -m spacy download pl_core_news_md

# Encoder embedding similarity (multilingual MiniLM, ~470 MB) - cache w obrazie
ARG DLP_CLASSIFIER_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
ENV DLP_CLASSIFIER_MODEL=${DLP_CLASSIFIER_MODEL}
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('${DLP_CLASSIFIER_MODEL}')"

# ---------- Kod ----------
COPY . .

# Nieuprzywilejowany uzytkownik
RUN useradd --create-home --shell /bin/bash appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck wbudowany w obraz
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Migracje + start
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
