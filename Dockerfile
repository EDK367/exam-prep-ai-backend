# Root Dockerfile for API deployment
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc build-essential \
    poppler-utils tesseract-ocr \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for dependency management
RUN pip install --no-cache-dir uv

# Copy package metadata first for dependency caching
COPY pyproject.toml .

# Create minimal package structure
RUN mkdir -p app && touch app/__init__.py

# Install python dependencies
RUN uv pip install --system -e .

# Pre-download tiktoken encoding (requires internet at build time)
RUN python -c "import tiktoken; tiktoken.encoding_for_model('gpt-4o')"

# Copy application source code
COPY . .

# Re-sync package installation with full source
RUN uv pip install --system -e .

# Non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
