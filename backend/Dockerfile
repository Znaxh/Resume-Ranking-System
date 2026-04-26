FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
RUN uv run python -m spacy download en_core_web_sm

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV FLASK_ENV=production

EXPOSE 5000

CMD ["uv", "run", "gunicorn", "app:app", "--workers", "2", "--bind", "0.0.0.0:5000"]
