FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /bin/uv

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --locked

COPY app app
COPY migrations migrations
COPY quizzes quizzes

CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
