FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /bin/uv

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" UV_NO_CACHE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app app
COPY migrations migrations
COPY quizzes quizzes

RUN useradd --system --uid 10001 app
USER app

CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
