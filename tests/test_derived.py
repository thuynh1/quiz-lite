import uuid

import pytest

from tests.test_home import visible_text


def quiz_yaml(slug: str, title: str, count: int) -> str:
    question = """\
  - id: q{n}
    prompt: Pick a.
    type: single
    options:
      - {{id: a, text: A}}
      - {{id: b, text: B}}
    correct: [a]
    explanation: Because a.
"""
    questions = "".join(question.format(n=n) for n in range(1, count + 1))
    return f"slug: {slug}\ntitle: {title}\nquestions:\n{questions}"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    (tmp_path / "five.yaml").write_text(quiz_yaml("five", "Five Quiz", 5))
    monkeypatch.setenv("QUIZ_DIR", str(tmp_path))
    monkeypatch.setenv("COOKIE_SECURE", "false")


def new_player(client) -> uuid.UUID:
    client.get("/")
    return uuid.UUID(client.cookies["player_id"])


def add_attempt(db, player_id, score=None, started_at="2026-10-21T17:05:00Z", slug="five"):
    if score is None:
        db.execute(
            "INSERT INTO attempt (player_id, quiz_slug, started_at) VALUES (%s, %s, %s)",
            (player_id, slug, started_at),
        )
    else:
        db.execute(
            "INSERT INTO attempt (player_id, quiz_slug, started_at, status, score, completed_at)"
            " VALUES (%s, %s, %s, 'completed', %s, now())",
            (player_id, slug, started_at, score),
        )


def home_text(client) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return visible_text(response.text)


def test_completed_attempt_shows_best_as_fraction_and_percent(make_client, db):
    with make_client() as client:
        add_attempt(db, new_player(client), score=3)
        text = home_text(client)

    assert "Five Quiz 5 3 / 5 | 60%" in text
    assert "Total points: 3" in text


def test_percent_rounds_half_up(make_client, db, tmp_path):
    (tmp_path / "eight.yaml").write_text(quiz_yaml("eight", "Eight Quiz", 8))
    with make_client() as client:
        add_attempt(db, new_player(client), score=1, slug="eight")
        text = home_text(client)

    assert "Eight Quiz 8 1 / 8 | 13%" in text


def test_retake_only_raises_total_when_it_beats_best(make_client, db):
    with make_client() as client:
        player_id = new_player(client)
        add_attempt(db, player_id, score=3)
        assert "Total points: 3" in home_text(client)

        add_attempt(db, player_id, score=2)
        assert "Total points: 3" in home_text(client)

        add_attempt(db, player_id, score=4)
        text = home_text(client)

    assert "Total points: 4" in text
    assert "4 / 5 | 80%" in text


def test_deleted_quiz_best_still_counts_toward_total(make_client, db):
    with make_client() as client:
        player_id = new_player(client)
        add_attempt(db, player_id, score=3)
        add_attempt(db, player_id, score=2, slug="gone")
        text = home_text(client)

    assert "Total points: 5" in text


def test_last_attempted_uses_tz_cookie(make_client, db):
    with make_client() as client:
        add_attempt(db, new_player(client), started_at="2026-10-21T17:05:00Z")
        client.cookies.set("tz", "America/Los_Angeles")
        text = home_text(client)

    assert "Five Quiz 5 — 2026-10-21 10:05 Start" in text


@pytest.mark.parametrize("tz", [None, "Not/AZone", "../etc/passwd", ""])
def test_last_attempted_falls_back_to_labelled_utc(make_client, db, tz):
    with make_client() as client:
        add_attempt(db, new_player(client), started_at="2026-10-21T17:05:00Z")
        if tz is not None:
            client.cookies.set("tz", tz)
        text = home_text(client)

    assert "Five Quiz 5 — 2026-10-21 17:05 UTC Start" in text


def test_unfinished_latest_attempt_sets_last_attempted(make_client, db):
    with make_client() as client:
        player_id = new_player(client)
        add_attempt(db, player_id, score=3, started_at="2026-10-20T08:00:00Z")
        add_attempt(db, player_id, started_at="2026-10-21T09:30:00Z")
        text = home_text(client)

    assert "Five Quiz 5 3 / 5 | 60% 2026-10-21 09:30 UTC" in text
    assert "Total points: 3" in text


def test_points_survive_a_fresh_app_with_same_cookie(make_client, db):
    with make_client() as client:
        player_id = new_player(client)
        add_attempt(db, player_id, score=4)

    with make_client() as client:
        client.cookies.set("player_id", str(player_id))
        text = home_text(client)

    assert "Total points: 4" in text
    assert "4 / 5 | 80%" in text
