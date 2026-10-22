# Quiz-lite spec

## Functional requirements

Users should be able to:
1. See a list of available quizzes.
2. Take a quiz one question at a time. Each question is multiple choice, either single-select or multi-select. After each answer, see whether it was right or wrong plus a short explanation. The explanation shows either way.
3. See their score at the end of a quiz.
4. Keep their total points across all quizzes between visits without logging in. Each visitor gets an auto-generated, unique, anonymous player ID, and points are stored server-side.

The author should be able to:

5. Add a new quiz by dropping a YAML file into a folder and redeploying.

### Scoring rules
- A question is correct only if the selected options exactly match the correct set. Multi-select is all-or-nothing, with no partial credit.
- Each correct question is worth 1 point. A quiz score is the number of correct questions.
- Retakes are allowed. Total points are the sum of each quiz's best score, so a retake only adds points if it beats the previous best.

## Non-functional requirements

The system should:
1. Grade answers on the server. The client sends its selections, never a score.
2. Keep points durable across restarts and redeploys. Points live in Postgres, never on the app container's disk.
3. Feel instant. Answer feedback returns in under 200 ms.
4. Be secure by default. No secrets in the repo (the database URL comes from an env var), all input is validated at the API, and the player cookie is HttpOnly.
5. Run locally with one command (`docker compose up` starts the app and Postgres).

Scale: a handful of users and about 1 request per second. One instance is enough, and brief downtime during deploys is acceptable.

## Constraints
- Database: PostgreSQL

## Core entities

Quiz content lives in YAML files in the repo and is read-only at runtime. Player progress lives in Postgres.

### In YAML (repo, read-only)

- Quiz
  - `slug`: unique string, for example `http-basics`
  - `title`: string
  - `questions`: list of Question, in display order
- Question (belongs to one Quiz)
  - `id`: string, unique within its quiz and stable over time, for example `q1`
  - `prompt`: string
  - `type`: `single` or `multi`
  - `options`: list of `{id, text}`
  - `correct`: list of option IDs. Exactly one for `single`, one or more for `multi`.
  - `explanation`: string

### In Postgres (written at runtime)

- Player
  - `id`: UUID, auto-generated, stored in the player cookie
  - `created_at`: timestamp
- Attempt (belongs to one Player; a Player has many Attempts)
  - `id`
  - `player_id`: references Player
  - `quiz_slug`: references a Quiz by slug
  - `status`: `in_progress` or `completed`
  - `score`: integer, null until completed
  - `started_at`: timestamp
  - `completed_at`: timestamp, null until completed
- Answer (belongs to one Attempt; an Attempt has many Answers)
  - `attempt_id`: references Attempt
  - `question_id`: references a Question by ID within the attempt's quiz
  - `selected`: list of option IDs
  - `is_correct`: boolean
  - Unique on (`attempt_id`, `question_id`)

### Derived values (computed by query, not stored)

- Best score per quiz: the highest `score` among a player's completed attempts for that quiz.
- Total points: the sum of the player's best scores across all quizzes.
- Last Attempted: the latest `started_at` among a player's attempts for that quiz, finished or not.

Rules:
- One Answer per question per attempt. The first answer stands, and later answers to the same question are rejected.
- The `correct` field is never sent to the client before the question is answered.
- Question IDs are stable. An edited quiz never reuses an ID for a different question.
- Attempts that are never completed do not count toward points.
- A Player row is created on the first visit, when the cookie is set.

## User stories and acceptance criteria

### US1: Browse quizzes
As a player, I want to see available quizzes so I can pick one.
- Given 2 YAML quizzes in the folder, when I open the home page, then I see both titles with their question counts.
- Given a quiz I have completed, then I see my best score next to it as a fraction and a percent (for example "3 / 5 | 60%").
- Given a quiz I have never attempted, then Last Attempted shows "None".
- Given a quiz I have attempted, then Last Attempted shows the start time of my most recent attempt, finished or not, as YYYY-MM-DD HH:mm in my local time zone.

### US2: Answer a question
As a player, I want feedback after each answer so I learn as I go.
- Given a single-select question, when I pick the correct option, then I see "Correct" plus the explanation.
- Given a multi-select question with answer [a, c, d], when I pick [a, c], then I see "Wrong", the correct set, and the explanation.
- Given I already answered q1 in this attempt, when I submit q1 again, then the API returns 409 and my first answer stands.
- Given a question I have not answered yet, when the page loads, then the response contains no `correct` field.

### US3: Finish a quiz
As a player, I want my score at the end so I know how I did.
- Given I answered all 5 questions with 3 correct, when I finish, then I see "3 / 5" and the attempt is marked completed.
- Given I leave mid-quiz, then that attempt never counts toward points.

### US4: Keep my points
As a player, I want my points saved without signing up.
- Given a first visit, then a player ID cookie (HttpOnly) is set and a Player row exists.
- Given my best on http-basics is 3, when I retake it and score 2, then my total stays the same. When I score 4, my total goes up by 1.
- Given the app restarts or redeploys, when I come back, then my total points are unchanged.

### US5: Add a quiz (author)
As the author, I want to add a quiz by adding one file.
- Given a valid new YAML file, when the app starts, then the quiz appears in the list.
- Given an invalid YAML file (missing `correct`, or a duplicate question ID), when the app starts, then it fails fast with an error naming the file and the field.

## Out of scope

Not in this MVP:
- Accounts, login, or any auth
- Quiz maker UI (quizzes are authored as YAML, later drafted by AI)
- Leaderboards, levels, badges, or streaks
- Partial credit, timed questions, or per-question point values
- Multiple app instances or horizontal scaling


## Clarifications

Resolved from the spec gaps in `docs/plan.md`.

1. The HTML form endpoints are the API; there is no separate JSON API, and "no `correct` field" means the unanswered question page contains no correctness data.
2. Questions cannot be skipped, and an attempt completes automatically when its last question is answered.
3. Start always creates a new attempt; abandoned attempts stay in progress forever, never count toward points, and still update Last Attempted.
4. A quiz with no completed attempt shows `—` as its best score.
5. A wrong answer always shows the correct set, for single-select as well as multi-select.
6. Percentages round to the nearest whole percent, so 2 / 3 shows 67%.
7. When a quiz is edited, completion and the question count use the current YAML, answers to removed question IDs are ignored, and stored best scores are shown as stored without capping.
8. A deleted quiz's best score still counts toward total points, though the quiz leaves the list.
9. Total points appear in the home page header.
10. Any cookieless request creates a Player row, except `/healthz` and `/static`.
11. The player cookie is refreshed on every visit because browsers cap cookie lifetime at 400 days, and clearing cookies loses points permanently.
12. Times use the browser's time zone from a JS-set `tz` cookie, and without it they show in UTC, labelled UTC.
13. A quiz's `slug` must equal its file name stem.
14. The 200 ms target is server-side p95 latency, checked by the post-deploy smoke test.
15. The app runs on Render's free tier. Cold starts are accepted: an idle service spins down after 15 minutes and takes about a minute to wake. The 200 ms target applies to a warm server. Free Postgres expires after 30 days, which is also accepted for now.
