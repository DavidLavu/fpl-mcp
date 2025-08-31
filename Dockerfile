# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# System deps
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

# Copy only dependency metadata first (leverage Docker cache)
COPY pyproject.toml README.md openapi.json ./

# Install runtime deps
RUN pip install --upgrade pip \
    && pip install . \
    && pip install 'uvicorn[standard]>=0.30.0,<1'

# Copy the rest of the app
COPY app ./app

EXPOSE 8000

# Use shell form to allow $PORT expansion with a default
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
