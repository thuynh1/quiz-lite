import re
import uuid
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "quizzes"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("QUIZ_DIR", str(FIXTURES))
    monkeypatch.setenv("COOKIE_SECURE", "false")


def start(client, slug="alpha") -> str:
    response = client.post(f"/quizzes/{slug}/attempts", follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def test_start_redirects_to_first_question_and_creates_in_progress_attempt(make_client, db):
    with make_client() as client:
        location = start(client)
        player_id = uuid.UUID(client.cookies["player_id"])

    match = re.fullmatch(r"/attempts/([0-9a-f-]{36})/questions/q1", location)
    assert match
    row = db.execute(
        "SELECT player_id, quiz_slug, status FROM attempt WHERE id = %s", (match[1],)
    ).fetchone()
    assert row == (player_id, "alpha", "in_progress")


def test_start_unknown_slug_is_404(make_client, db):
    with make_client() as client:
        response = client.post("/quizzes/nope/attempts", follow_redirects=False)

    assert response.status_code == 404
    assert db.execute("SELECT count(*) FROM attempt").fetchone()[0] == 0


def test_resume_redirects_to_first_unanswered_question(make_client):
    with make_client() as client:
        location = start(client)
        attempt_url = location.removesuffix("/questions/q1")
        response = client.get(attempt_url, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == location


def test_unanswered_question_page_has_no_correctness_data(make_client):
    with make_client() as client:
        q1 = client.get(start(client))
        q2 = client.get(start(client).replace("/q1", "/q2"))

    assert q1.status_code == 200
    assert "Pick b." in q1.text
    assert "1 of 2" in q1.text
    assert "B is right." not in q1.text
    assert "correct" not in q1.text.lower()
    radios = re.findall(r'<input type="radio" name="selected" value="(\w+)"[^>]*>', q1.text)
    assert radios == ["a", "b"]
    # alpha q1's correct option is b: its markup must match option a's exactly.
    a_input = re.search(r'<input[^>]*value="a"[^>]*>', q1.text)[0]
    b_input = re.search(r'<input[^>]*value="b"[^>]*>', q1.text)[0]
    assert b_input == a_input.replace('"a"', '"b"')

    assert q2.status_code == 200
    assert "2 of 2" in q2.text
    assert "A and C are right." not in q2.text
    assert "correct" not in q2.text.lower()
    checkboxes = re.findall(r'<input type="checkbox" name="selected" value="(\w+)"', q2.text)
    assert checkboxes == ["a", "b", "c"]


def test_unknown_question_or_attempt_is_404(make_client):
    with make_client() as client:
        location = start(client)
        unknown_qid = client.get(location.replace("/q1", "/q9"))
        unknown_attempt = client.get(f"/attempts/{uuid.uuid4()}/questions/q1")
        malformed = client.get("/attempts/not-a-uuid", follow_redirects=False)

    assert unknown_qid.status_code == 404
    assert unknown_attempt.status_code == 404
    assert malformed.status_code == 404


def test_another_players_attempt_is_404(make_client):
    with make_client() as owner:
        location = start(owner)
    attempt_url = location.removesuffix("/questions/q1")

    with make_client() as other:
        question = other.get(location)
        resume = other.get(attempt_url, follow_redirects=False)

    assert question.status_code == 404
    assert resume.status_code == 404
