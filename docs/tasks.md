# Quiz-lite tasks

Work from the first unchecked task. Each task is one session and one commit. It ends with lint and the full test suite passing, and it is checked off in the same commit. Criterion IDs are `US<story>.<n>`, numbered in the order the criteria appear in `docs/spec.md`.

- [x] **1. Skeleton, smoke test, CI**
  - `pyproject.toml` (uv, Python 3.12, ruff config, pytest config), `uv.lock`, `app/main.py` with `GET /healthz` returning `{"status": "ok"}` (no DB yet), `.gitignore`.
  - `.github/workflows/ci.yml` on push and PR: `uv sync --locked`, `ruff check`, `ruff format --check`, `pytest`.
  - Test: `tests/test_smoke.py`, where `GET /healthz` returns 200.
  - Covers: none (infrastructure).

- [x] **2. Quiz YAML loading and validation**
  - `app/quizzes.py`: Pydantic models, `load_quizzes(dir)`, semantic checks, errors formatted `<file>: <field path>: <message>`, CLI `check` and `schema`.
  - Lifespan loads quizzes from `QUIZ_DIR` and fails startup on error. `quizzes/http-basics.yaml` and the generated `quizzes/quiz.schema.json` are added. CI gains the `check` step.
  - Tests:
    - valid fixtures load
    - a missing `correct` reports the file and `correct`
    - a duplicate question ID reports the file and `id`
    - also: `correct` not in options, two IDs for `single`, slug ≠ filename, YAML boolean as an ID
    - app startup with a bad directory raises
    - the committed schema matches the generated one
  - Covers: US5.2.

- [x] **3. Postgres, migrations, compose**
  - `compose.yaml` (db and app), `Dockerfile` (dev-usable), `docker/initdb/01-test-db.sql`, `migrations/0001_init.sql`, `app/migrate.py`, `app/db.py` with the pool opened in the lifespan.
  - `/healthz` runs `SELECT 1` and returns 503 when the DB is down. `conftest.py` provides the test DB, migrations, truncation and a client factory. CI gains the Postgres service.
  - Tests:
    - migrate is idempotent (a second run applies nothing)
    - a duplicate `(attempt_id, question_id)` is rejected
    - a `completed` attempt with a null score is rejected by the CHECK
    - `/healthz` returns 200 against the DB
  - Covers: none (groundwork for US4.3).

- [x] **4. Anonymous player cookie**
  - `app/player.py` dependency: creates a Player when the cookie is missing, malformed or unknown, and sets or refreshes the `player_id` cookie (HttpOnly, SameSite=Lax, Secure when `COOKIE_SECURE`). `/healthz` and `/static` are exempt.
  - Tests:
    - the first `GET /` sets an HttpOnly cookie and the Player row exists
    - a second request with that cookie creates no new row
    - a garbage cookie gets a fresh ID
    - `/healthz` sets no cookie
  - Covers: US4.1.

- [x] **5. Home page: quiz list**
  - `templates/base.html` (with the `tz` cookie line), `home.html`, `GET /` listing title and question count, total points (0), best `—`, Last Attempted `None`.
  - Tests:
    - with 2 fixture quizzes, both titles and counts render
    - Last Attempted shows `None` for each
    - a new valid YAML file in the fixture directory appears after an app restart
  - Covers: US1.1, US1.3, US5.1.

- [x] **6. Start an attempt and show a question**
  - `POST /quizzes/{slug}/attempts`, `GET /attempts/{id}`, and `GET /attempts/{id}/questions/{qid}` in its unanswered state. The `question.html` template has radio inputs for single and checkboxes for multi. Another player's attempt returns 404.
  - Tests:
    - start returns 303 to q1 and an attempt row is `in_progress`
    - an unknown slug returns 404
    - the unanswered question page contains no correct option IDs or explanation
    - another player's cookie gets 404
  - Covers: US2.4.

- [ ] **7. Grade and store answers with feedback**
  - `app/grading.py` (exact set match). `POST /attempts/{id}/questions/{qid}` validates the selection (422), inserts with `ON CONFLICT DO NOTHING` (409 on duplicate) and redirects to feedback. The answered state of the question page shows Correct or Wrong, the correct set when wrong, and the explanation.
  - Tests:
    - unit: single correct, multi exact match, multi subset wrong, multi superset wrong
    - a correct single shows `Correct` and the explanation
    - multi `[a, c]` against `[a, c, d]` shows `Wrong`, the correct set and the explanation
    - a resubmit returns 409 and the stored answer is unchanged
    - an empty, unknown or duplicate ID, or two IDs on single, returns 422
  - Covers: US2.1, US2.2, US2.3.

- [ ] **8. Complete an attempt and show the score**
  - The final answer completes the attempt in the same transaction (row lock, score, `completed_at`). `GET /attempts/{id}/result` added. Answering a completed attempt returns 409.
  - Tests:
    - 5 answers with 3 correct gives `3 / 5` on the result page, and the row is `completed` with score 3
    - an attempt left after 2 answers stays `in_progress` with a null score and adds 0 to the total
    - the result page of an in-progress attempt redirects
  - Covers: US3.1, US3.2.

- [ ] **9. Best score, total points, Last Attempted**
  - The derived-values query in `db.py`. Home shows `3 / 5 | 60%`, the total in the header, and Last Attempted formatted in the `tz` cookie's zone (UTC fallback).
  - Tests:
    - a completed 3/5 shows `3 / 5 | 60%`
    - a 3/5 best followed by a 2/5 retake leaves the total unchanged; a 4/5 retake raises it by 1
    - an attempt started at a known UTC time with `tz=America/Los_Angeles` renders the local `YYYY-MM-DD HH:mm`
    - an unfinished latest attempt still sets Last Attempted
    - points survive a fresh app with a new pool and the same cookie
  - Covers: US1.2, US1.4, US4.2, US4.3.

- [ ] **10. Production container**
  - Harden the `Dockerfile`: `--no-dev`, non-root user, `PORT`, and a CMD that migrates then serves. Add a `.dockerignore`. CI builds the image and runs it against the service Postgres, then curls `/healthz`.
  - Test: the CI container smoke step passes, and the local `pytest` suite stays green.
  - Covers: US4.3 (migrate on boot against existing data is a no-op).

- [ ] **11. First deploy** (the owner picks Render or Fly.io first)
  - Provision managed Postgres and the app in the same region and set `DATABASE_URL` as a secret. Add `scripts/smoke.sh <url>`, which checks:
    - `/healthz` returns 200
    - `/` sets an HttpOnly, Secure `player_id` cookie
    - home lists the quizzes
    - server time is under 200 ms
  - Test: the smoke script passes against the deployed URL. Redeploy, and a pre-existing player's total is unchanged.
  - Covers: US4.1, US4.3 (production).

- [ ] **12. Continuous deploy**
  - Deploy `main` only after CI passes: Render auto-deploy with the CI gate, or a `flyctl deploy` job with `needs: check`. Run `scripts/smoke.sh` after each deploy.
  - Test: a trivial commit to main deploys and the post-deploy smoke step passes.
  - Covers: none (delivery).

## Criterion coverage

| Criterion | Task(s) |
|---|---|
| US1.1 two quizzes listed with counts | 5 |
| US1.2 best score as `3 / 5 \| 60%` | 9 |
| US1.3 never attempted shows `None` | 5 |
| US1.4 Last Attempted in local time | 9 |
| US2.1 correct single shows Correct and explanation | 7 |
| US2.2 wrong multi shows Wrong, correct set, explanation | 7 |
| US2.3 resubmit returns 409, first answer stands | 7 |
| US2.4 no `correct` before answering | 6 |
| US3.1 3 of 5 correct shows `3 / 5`, marked completed | 8 |
| US3.2 abandoned attempt never counts | 8 |
| US4.1 HttpOnly cookie and Player row on first visit | 4, 11 |
| US4.2 retake only adds when it beats the best | 9 |
| US4.3 points survive restart and redeploy | 9, 10, 11 |
| US5.1 new valid YAML appears in the list | 5 |
| US5.2 invalid YAML fails fast naming file and field | 2 |
