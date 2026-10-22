# CLAUDE.md

Quiz-lite: a small quiz app. Players take multiple-choice quizzes loaded from YAML files and keep points across visits without logging in.

## Docs
- `docs/spec.md`: what the app does. Source of truth for behavior. Read it before any task.
- `docs/plan.md`: how it is built (stack, schema, routes, CI, deploy). Drafted by Claude, approved by the owner.
- `docs/tasks.md`: ordered task checklist. Work from the first unchecked task.
- `docs/backlog.md`: post-MVP ideas. Do not build anything from it unless asked.

## Stack
- Python 3.12+, FastAPI, Jinja2 server-rendered HTML, PostgreSQL
- uv for dependencies, ruff for lint, pytest for tests
- One Docker container for the app. `docker compose up` starts the app and Postgres locally.

## Commands
From docs/plan.md. Available once tasks 1 to 3 land.
- Install: `uv sync`
- Run locally: `docker compose up`
- Lint: `uv run ruff check --quiet` and `uv run ruff format --check`
- Test: `docker compose up -d db`, then `uv run pytest -q`
- Validate quizzes: `uv run python -m app.quizzes check quizzes`
- Regenerate quiz schema: `uv run python -m app.quizzes schema > quizzes/quiz.schema.json`
- Migrate: `python -m app.migrate` (also runs on container start)

## Invariants that are easy to break
Full details are in the spec. These apply to every task.
- The server grades answers. The client sends selections only, never a score.
- `correct` is never in a response before that question is answered in the attempt.
- One Answer per (attempt, question). A second submit returns 409 and the first answer stands.
- Quiz YAML is read-only at runtime and validated at startup. Invalid files fail fast, naming the file and field.
- No auth. The player is an anonymous UUID in an HttpOnly cookie. Config and secrets come from env vars only.

## Workflow
- One task from docs/tasks.md per session. Use `/pstack:poteto-mode` for each task.
- Write the failing test first. Tests map to the acceptance criteria (US1 to US5) in the spec.
- Run lint and the full test suite before every commit. Never commit on red.
- Check off the task in docs/tasks.md in the same commit that completes it.
- If a task conflicts with the spec, stop and ask. Update the spec before the code.

## Token budget
- Skip arena, swarm, and interrogate unless asked. Use one code-writing subagent per task.
- Expect /clear between tasks, so keep docs/tasks.md current.
- Read only the files the current task needs.
- Keep command output short. Show full output only for failures.
- If a fix fails 3 times, stop and report what you tried instead of looping.
