# Quiz-lite build plan

How the app in `docs/spec.md` gets built. The spec wins on any conflict.

## Project layout

```
quiz-lite/
  app/
    main.py         # FastAPI app; lifespan loads quizzes and opens the DB pool
    config.py       # reads env vars (DATABASE_URL, QUIZ_DIR, COOKIE_SECURE, PORT)
    quizzes.py      # Pydantic quiz models, YAML loader, semantic checks; CLI: check, schema
    grading.py      # pure grade(question, selected) -> bool
    db.py           # connection pool and every SQL query
    migrate.py      # forward-only migration runner; `python -m app.migrate`
    player.py       # player-cookie dependency
    pages.py        # all routes (HTML pages and form posts)
    templates/      # base, home, question, result, error
    static/         # app.css
  migrations/
    0001_init.sql
  quizzes/
    http-basics.yaml
    quiz.schema.json  # generated from app/quizzes.py, do not edit
  tests/
    conftest.py       # test DB, migrations, per-test truncate, client factory
    fixtures/quizzes/ # valid and invalid YAML fixtures
    test_*.py
  docker/initdb/01-test-db.sql  # creates quiz_test in the compose db
  Dockerfile
  compose.yaml
  pyproject.toml, uv.lock
  .github/workflows/ci.yml
```

## Postgres schema

`migrations/0001_init.sql`:

```sql
CREATE TABLE player (
  id         uuid PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attempt (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id    uuid NOT NULL REFERENCES player(id) ON DELETE CASCADE,
  quiz_slug    text NOT NULL,
  status       text NOT NULL DEFAULT 'in_progress'
               CHECK (status IN ('in_progress', 'completed')),
  score        integer CHECK (score >= 0),
  started_at   timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CHECK (
    (status = 'in_progress' AND score IS NULL AND completed_at IS NULL) OR
    (status = 'completed' AND score IS NOT NULL AND completed_at IS NOT NULL)
  )
);
-- Serves best score, last attempted and ownership lookups for one player.
CREATE INDEX attempt_player_quiz_idx ON attempt (player_id, quiz_slug, started_at DESC);

CREATE TABLE answer (
  attempt_id  uuid NOT NULL REFERENCES attempt(id) ON DELETE CASCADE,
  question_id text NOT NULL,
  selected    text[] NOT NULL CHECK (cardinality(selected) >= 1),
  is_correct  boolean NOT NULL,
  PRIMARY KEY (attempt_id, question_id)  -- one answer per question per attempt
);
```

Notes:
- `quiz_slug` and `question_id` are plain text, not foreign keys, because quizzes live in YAML.
- Attempt IDs are UUIDs, so URLs cannot be enumerated. Ownership is still checked on every request.
- The first answer stands: `INSERT ... ON CONFLICT DO NOTHING RETURNING`. No row back means 409. The insert is race-safe without app-level locking.
- An answer that completes the attempt runs in one transaction with `SELECT ... FOR UPDATE` on the attempt row. That transaction inserts the answer and, when every current question is answered, sets `status`, `score` and `completed_at`.
- Derived values come from one query per page and are never stored:
  ```sql
  SELECT quiz_slug,
         max(score) FILTER (WHERE status = 'completed') AS best,
         max(started_at)                               AS last_started
  FROM attempt WHERE player_id = %s GROUP BY quiz_slug;
  ```
  Total points is the sum of `best` across slugs.

### Migration tool: in-repo runner (`app/migrate.py`)

The runner applies `migrations/NNNN_*.sql` in order, each file in its own transaction. It records each file in a `schema_migrations(version text PRIMARY KEY, applied_at timestamptz)` table and holds `pg_advisory_lock` during the run. It is forward-only: a mistake gets fixed with a new migration.

Why this instead of a library:
- The app has one schema, a single instance and plain SQL. The runner is about 30 lines on the psycopg driver we already have.
- It reads `DATABASE_URL` exactly as hosts provide it. yoyo-migrations would need the scheme rewritten to `postgresql+psycopg://`.
- Alembic would need SQLAlchemy, and this app uses no ORM.
- If down-migrations or branching ever matter, swap in yoyo-migrations. It reads the same `.sql` files.

The container runs `python -m app.migrate` before uvicorn starts. Tests run the same function once per session.

## Routes and pages

Every route is server-rendered HTML via Jinja2, and the form endpoints are the API. All input goes through Pydantic or explicit checks, and any request that fails them is rejected. The player dependency (`player.py`) runs on every route except `/healthz` and `/static`. When the `player_id` cookie is missing, malformed or unknown, it inserts a Player row. It then sets or refreshes the cookie: `HttpOnly; SameSite=Lax; Path=/; Max-Age=34560000` (400 days, the browser cap), plus `Secure` when `COOKIE_SECURE=true`. An attempt owned by another player returns 404, never 403, so attempt IDs don't leak.

| Method | Path | Request | Response | Status codes |
|---|---|---|---|---|
| GET | `/` | cookies: `player_id`, `tz` | Home: total points; per quiz: title, question count, best (`3 / 5 \| 60%` or `—`), Last Attempted (`YYYY-MM-DD HH:mm` in `tz`, or `None`), Start button | 200 |
| POST | `/quizzes/{slug}/attempts` | empty form | Creates an attempt. Redirects to the first question | 303, 404 unknown slug |
| GET | `/attempts/{id}` | none | Redirects to the first unanswered question, or to `/result` if completed | 303, 404 |
| GET | `/attempts/{id}/questions/{qid}` | none | Unanswered: prompt, options (radio for `single`, checkbox for `multi`), progress `2 of 5`. Contains no correctness data. Answered: `Correct` or `Wrong`, your selection, the correct set when wrong, the explanation, and a Next or See score link | 200, 404 |
| POST | `/attempts/{id}/questions/{qid}` | form `selected` (repeatable option IDs) | Grades and stores the answer. On the last question, completes the attempt. Redirects to the GET above (post/redirect/get) | 303; 409 already answered (shows the first answer); 409 attempt completed; 422 empty selection, unknown or duplicate option ID, or more than one ID for `single` (form re-rendered with an error); 404 |
| GET | `/attempts/{id}/result` | none | `3 / 5` and a link home | 200; 303 to `/attempts/{id}` if in progress; 404 |
| GET | `/healthz` | none | `{"status": "ok"}` after `SELECT 1` | 200, 503 if DB unreachable |
| GET | `/static/*` | none | CSS | 200 |

Local time (US1.4): `base.html` contains one inline line that sets `tz=<Intl IANA zone>` (`SameSite=Lax`, not HttpOnly). The server formats times with `zoneinfo` from the standard library. It validates the zone and falls back to UTC, labelled `UTC`. This keeps the formatting server-side and testable.

CSRF: the `SameSite=Lax` cookie means cross-site form posts carry no player, so they 404 on someone else's attempt. That is enough for a no-auth, no-money app.

## Quiz YAML

Files live in `QUIZ_DIR` (default `./quizzes`), one quiz per `<slug>.yaml`.

```yaml
# yaml-language-server: $schema=quiz.schema.json
slug: http-basics
title: HTTP Basics
questions:
  - id: q1
    prompt: Which status code means "Not Found"?
    type: single
    options:
      - {id: a, text: "200"}
      - {id: b, text: "301"}
      - {id: c, text: "404"}
      - {id: d, text: "500"}
    correct: [c]
    explanation: 404 means the server could not find the requested resource.
  - id: q2
    prompt: Which methods are idempotent by definition?
    type: multi
    options:
      - {id: a, text: GET}
      - {id: b, text: POST}
      - {id: c, text: PUT}
      - {id: d, text: DELETE}
    correct: [a, c, d]
    explanation: Repeating GET, PUT or DELETE has the same effect as sending it once. POST does not.
  - id: q3
    prompt: Which header tells the client the format of the response body?
    type: single
    options:
      - {id: a, text: Accept}
      - {id: b, text: Content-Type}
      - {id: c, text: Host}
    correct: [b]
    explanation: Content-Type describes the body being sent. Accept is what the client asks for.
```

### JSON Schema (`quizzes/quiz.schema.json`)

This file is generated from the Pydantic models with `uv run python -m app.quizzes schema > quizzes/quiz.schema.json`. A test fails when the committed file differs from the generated one. Editors pick it up through the `yaml-language-server` comment. Expected output:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Quiz",
  "type": "object",
  "additionalProperties": false,
  "required": ["slug", "title", "questions"],
  "properties": {
    "slug": {"type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"},
    "title": {"type": "string", "minLength": 1},
    "questions": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/Question"}}
  },
  "$defs": {
    "Option": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "text"],
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9_-]+$"},
        "text": {"type": "string", "minLength": 1}
      }
    },
    "Question": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "prompt", "type", "options", "correct", "explanation"],
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9_-]+$"},
        "prompt": {"type": "string", "minLength": 1},
        "type": {"enum": ["single", "multi"]},
        "options": {"type": "array", "minItems": 2, "items": {"$ref": "#/$defs/Option"}},
        "correct": {"type": "array", "minItems": 1, "uniqueItems": true, "items": {"type": "string"}},
        "explanation": {"type": "string", "minLength": 1}
      },
      "if": {"properties": {"type": {"const": "single"}}},
      "then": {"properties": {"correct": {"maxItems": 1}}}
    }
  }
}
```

JSON Schema cannot express some rules, so the loader checks them after Pydantic:
- Question IDs are unique within a quiz.
- Option IDs are unique within a question.
- Every `correct` ID is one of the question's option IDs.
- `slug` equals the file name stem, which also makes slugs unique.

All strings are strict, so `id: no` (a YAML boolean) is rejected rather than coerced. Files are parsed with `yaml.safe_load`.

Errors name the file and field, for example `quizzes/http-basics.yaml: questions[1].correct: Field required`.

Validation runs in three places:
- **Startup:** the FastAPI lifespan loads every file and the process exits non-zero on the first invalid one.
- **CI:** `uv run python -m app.quizzes check quizzes` runs as its own step before the tests.
- **Tests:** they cover the loader with valid and invalid fixtures.

## Local development

`compose.yaml` defines two services:
- **`db`**: `postgres:17-alpine`; user, password and database all `quiz`; port 5432 published to the host; volume `pgdata`; `./docker/initdb` mounted at `/docker-entrypoint-initdb.d` to create `quiz_test`; healthcheck `pg_isready`.
- **`app`**: `build: .`; `depends_on: db (service_healthy)`; port 8000; `./app` and `./quizzes` mounted for live reload. Command: `python -m app.migrate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.

`docker compose up` starts both. The local password `quiz` is a dev-only value in compose, not a secret.

| Env var | Used by | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | app, migrate | none (required) | Set by compose locally and by the host in prod |
| `QUIZ_DIR` | app | `./quizzes` | Tests point it at `tests/fixtures/quizzes` |
| `COOKIE_SECURE` | app | `true` | Compose sets `false` for plain-http localhost |
| `PORT` | container CMD | `8000` | Some hosts inject it |
| `TEST_DATABASE_URL` | tests | `postgresql://quiz:quiz@localhost:5432/quiz_test` | CI sets it to the service container |

How tests get a real Postgres: `docker compose up -d db`, then `uv run pytest -q`.
- `conftest.py` runs `app.migrate` against `TEST_DATABASE_URL` once per session.
- An autouse fixture runs `TRUNCATE player CASCADE` after each test.
- A client-factory fixture builds a fresh app (new pool) per call. That simulates a restart for US4.3.
- There is no transaction-rollback trick, because the app opens its own pooled connections.

## CI (GitHub Actions)

`.github/workflows/ci.yml` runs on `push` and `pull_request`. It is one job on `ubuntu-latest` with a `postgres:17` service: env `POSTGRES_USER/PASSWORD/DB=quiz/quiz/quiz_test`, port 5432, `pg_isready` health options. Steps:

1. `actions/checkout`, `astral-sh/setup-uv` (pin current majors in task 1)
2. `uv sync --locked`
3. `uv run ruff check --quiet` and `uv run ruff format --check`
4. `uv run python -m app.quizzes check quizzes` (YAML validation; added in task 2)
5. `uv run pytest -q` with `TEST_DATABASE_URL=postgresql://quiz:quiz@localhost:5432/quiz_test`
6. `docker build .` (added in task 10, to catch Dockerfile breakage)

## Deploy

The app ships as one container image built from the `Dockerfile`:
- base `python:3.12-slim`, with `uv` copied from its pinned official image
- `uv sync --locked --no-dev`
- non-root user
- `CMD sh -c "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"`

Managed Postgres is reached via `DATABASE_URL`, set as a host secret. Run one instance in the same region as the database; that's the main lever for staying under 200 ms. Migrations run on boot, which is safe with a single instance and the advisory lock.

**Chosen host: Render, free tier** (owner decision, 2026-10-22). The app and Postgres are defined in `render.yaml` as a Blueprint. The owner accepts the free-tier limits: the web service spins down after 15 minutes idle and takes about a minute to wake, and the free database expires after 30 days. The 200 ms target applies to a warm server (spec Clarification 15). The comparison below is kept as the record of the choice.

**CD gate** (owner decision, 2026-10-22): `autoDeployTrigger: checksPass` in `render.yaml` deploys `main` only after its CI checks pass. There is no deploy workflow in GitHub Actions. The post-deploy smoke check stays manual: run `scripts/smoke.sh <service URL>` after a deploy. An automated post-deploy smoke job is in `docs/backlog.md`.

| | Render | Fly.io |
|---|---|---|
| App | Web Service from the repo's Dockerfile | Machine from the Docker image via `fly deploy` |
| Postgres | Render Postgres in the same dashboard and region; internal URL injected | Fly Managed Postgres, or any external provider (Neon, Supabase) via `DATABASE_URL` |
| CD | Built-in auto-deploy on push, with an "after CI checks pass" option. Almost no workflow code | A `flyctl deploy` job in GitHub Actions with a `FLY_API_TOKEN` secret |
| Pros | Fewest moving parts; dashboard-driven; DB and app managed together | More control (regions, machine size, auto-stop); deploys are just "ship an image"; DB vendor is swappable |
| Cons | Free web tier sleeps (cold starts break "feel instant"), so it needs a paid instance; free Postgres is time-limited; less control | More CLI setup; auto-stop also gives cold starts unless a minimum of one machine is kept running; external DB adds a vendor |

## Dependencies

Givens: `fastapi`, `jinja2`, `psycopg[binary]`.

| Dependency | Kind | Why it is needed |
|---|---|---|
| `uvicorn` | runtime | FastAPI ships no server. The plain package, not `fastapi[standard]`, which pulls in many extras |
| `psycopg_pool` | runtime | Same project as psycopg. Reusing connections avoids a TLS handshake per request to managed Postgres, which would eat into the 200 ms budget |
| `pyyaml` | runtime | The standard library has no YAML parser. Used only through `safe_load` |
| `python-multipart` | runtime | FastAPI needs it to parse form posts, which carry every answer |
| `pytest` | dev | Test runner (CLAUDE.md) |
| `httpx` | dev | Required by FastAPI's `TestClient` |
| `ruff` | dev | Lint and format (CLAUDE.md) |

Considered and not added:
- `jsonschema`: Pydantic validates and generates the schema.
- `pydantic-settings`: four env vars, read with `os.environ`.
- `alembic` / SQLAlchemy and `yoyo-migrations`: see Migration tool.
- `testcontainers`: compose and CI already provide Postgres.
- `htmx` / JS frameworks: forms are enough.

## Spec gaps and questions (resolved)

Resolved 2026-10-21: the owner accepted every proposed answer, and question 12 uses the UTC fallback, labelled UTC. The answers are recorded in the Clarifications section of `docs/spec.md`.

1. **API shape.** The spec says "the API returns 409" and "the response contains no `correct` field". The plan treats the HTML form endpoints as the API, and US2.4 is tested by checking that the question page has no correctness data. Is a separate JSON API wanted? *Proposed: no.*
2. **Finishing.** Can a player finish with unanswered questions, or skip any? *Proposed: no skipping. The attempt completes automatically when the last question is answered.*
3. **Resuming.** If a player leaves mid-quiz and comes back, do they resume or start over? *Proposed: Start always creates a new attempt. Abandoned attempts stay `in_progress` forever, never count toward points, and still update Last Attempted.*
4. **Best score with no completed attempt.** US1.2 covers only completed quizzes. What shows otherwise? *Proposed: `—`.*
5. **Wrong single-select.** US2.2 shows the correct set for multi-select. Should a wrong single-select answer show the correct option too? *Proposed: yes, always show the correct set on Wrong.*
6. **Percent rounding.** *Proposed: round to the nearest whole percent, so 2/3 shows 67%.*
7. **Quiz edited after attempts exist.** If questions are added or removed, completion and the denominator use the current YAML, and answers to removed IDs are ignored. Stored best scores from the old version stay as they were. Can a best score exceed the new question count? *Proposed: show it as stored, without capping.*
8. **Quiz deleted.** Does its best score still count toward total points? *Proposed: yes, points are durable. The quiz just leaves the list.*
9. **Where total points appear.** The spec never says. *Proposed: in the home page header.*
10. **Player rows for cookieless traffic.** Every crawler hit creates a Player row. Acceptable at this scale? *Proposed: yes. `/healthz` and `/static` are exempt.*
11. **Cookie lifetime.** Browsers cap cookies at 400 days, so the cookie is refreshed on every visit. Clearing cookies loses points for good. Is that accepted? *Proposed: yes; it follows from "no login".*
12. **Local time zone.** The browser zone is sent in a JS-set `tz` cookie. Without JS, times show in UTC, labelled. Is that OK?
13. **Slug and filename.** Must `slug` equal the file name stem? *Proposed: yes, enforced at load.*
14. **The 200 ms target.** Is it server time or measured from the browser? *Proposed: server-side p95, checked by the post-deploy smoke test.*
