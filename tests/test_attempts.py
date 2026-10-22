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


def answer(client, location, *selected):
    return client.post(location, data={"selected": list(selected)}, follow_redirects=False)


def stored_answers(db):
    return db.execute("SELECT question_id, selected, is_correct FROM answer").fetchall()


def test_correct_single_redirects_to_feedback_with_correct_and_explanation(make_client, db):
    with make_client() as client:
        location = start(client)
        response = answer(client, location, "b")
        page = client.get(location)

    assert response.status_code == 303
    assert response.headers["location"] == location
    assert stored_answers(db) == [("q1", ["b"], True)]
    assert "Correct" in page.text
    assert "Wrong" not in page.text
    assert "B is right." in page.text
    assert f'href="{location.removesuffix("/questions/q1")}"' in page.text
    assert "<form" not in page.text


def test_wrong_multi_shows_wrong_correct_set_and_explanation(make_client, db):
    with make_client() as client:
        location = start(client, "beta").replace("/q1", "/q2")
        response = answer(client, location, "a", "c")
        page = client.get(location)

    assert response.status_code == 303
    assert stored_answers(db) == [("q2", ["a", "c"], False)]
    text = " ".join(re.sub(r"<[^>]+>", " ", page.text).split())
    assert "Wrong" in text
    assert "Your answer: A, C" in text
    assert "Correct answer: A, C, D" in text
    assert "A, C and D are right." in text


def test_wrong_single_shows_correct_answer(make_client):
    with make_client() as client:
        location = start(client)
        answer(client, location, "a")
        text = " ".join(re.sub(r"<[^>]+>", " ", client.get(location).text).split())

    assert "Wrong" in text
    assert "Correct answer: B" in text


def test_resubmit_is_409_and_first_answer_stands(make_client, db):
    with make_client() as client:
        location = start(client)
        answer(client, location, "a")
        response = answer(client, location, "b")

    assert response.status_code == 409
    assert "Wrong" in response.text
    assert "Your answer: A" in " ".join(re.sub(r"<[^>]+>", " ", response.text).split())
    assert stored_answers(db) == [("q1", ["a"], False)]


@pytest.mark.parametrize(
    ("slug", "qid", "selected"),
    [
        ("alpha", "q1", []),
        ("alpha", "q1", ["z"]),
        ("alpha", "q2", ["a", "a"]),
        ("alpha", "q1", ["a", "b"]),
    ],
    ids=["empty", "unknown", "duplicate", "two-on-single"],
)
def test_invalid_selection_is_422_with_form_and_stores_nothing(
    make_client, db, slug, qid, selected
):
    with make_client() as client:
        location = start(client, slug).replace("/q1", f"/{qid}")
        response = answer(client, location, *selected)

    assert response.status_code == 422
    assert '<form method="post">' in response.text
    assert 'role="alert"' in response.text
    assert "correct" not in response.text.lower()
    assert stored_answers(db) == []


def test_answer_unknown_question_or_other_players_attempt_is_404(make_client, db):
    with make_client() as owner:
        location = start(owner)
        unknown_qid = answer(owner, location.replace("/q1", "/q9"), "a")
    with make_client() as other:
        foreign = answer(other, location, "b")

    assert unknown_qid.status_code == 404
    assert foreign.status_code == 404
    assert stored_answers(db) == []


def write_quiz(directory, qids):
    questions = "".join(
        f"  - id: {qid}\n    prompt: Pick b.\n    type: single\n"
        "    options:\n      - {id: a, text: A}\n      - {id: b, text: B}\n"
        "    correct: [b]\n    explanation: B is right.\n"
        for qid in qids
    )
    (directory / "five.yaml").write_text(f"slug: five\ntitle: Five\nquestions:\n{questions}")


@pytest.fixture
def five(tmp_path, monkeypatch):
    write_quiz(tmp_path, ["q1", "q2", "q3", "q4", "q5"])
    monkeypatch.setenv("QUIZ_DIR", str(tmp_path))
    return tmp_path


def attempt_row(db, attempt_url):
    return db.execute(
        "SELECT status, score, completed_at IS NOT NULL FROM attempt WHERE id = %s",
        (attempt_url.removeprefix("/attempts/"),),
    ).fetchone()


def test_five_answers_three_correct_completes_with_score(make_client, db, five):
    with make_client() as client:
        attempt_url = start(client, "five").removesuffix("/questions/q1")
        for qid, choice in zip(["q1", "q2", "q3", "q4", "q5"], "bbbaa", strict=True):
            assert answer(client, f"{attempt_url}/questions/{qid}", choice).status_code == 303
        last = client.get(f"{attempt_url}/questions/q5")
        resume = client.get(attempt_url, follow_redirects=False)
        result = client.get(f"{attempt_url}/result")

    assert attempt_row(db, attempt_url) == ("completed", 3, True)
    assert f'<a href="{attempt_url}/result">See score</a>' in last.text
    assert resume.headers["location"] == f"{attempt_url}/result"
    assert result.status_code == 200
    assert "3 / 5" in result.text
    assert 'href="/"' in result.text


def test_left_after_two_answers_stays_in_progress(make_client, db, five):
    with make_client() as client:
        attempt_url = start(client, "five").removesuffix("/questions/q1")
        answer(client, f"{attempt_url}/questions/q1", "b")
        answer(client, f"{attempt_url}/questions/q2", "b")
        page = client.get(f"{attempt_url}/questions/q2")

    assert attempt_row(db, attempt_url) == ("in_progress", None, False)
    assert f'<a href="{attempt_url}">Next</a>' in page.text


def test_result_of_in_progress_attempt_redirects_and_foreign_is_404(make_client):
    with make_client() as owner:
        attempt_url = start(owner).removesuffix("/questions/q1")
        response = owner.get(f"{attempt_url}/result", follow_redirects=False)
        unknown = owner.get(f"/attempts/{uuid.uuid4()}/result")
    with make_client() as other:
        foreign = other.get(f"{attempt_url}/result")

    assert response.status_code == 303
    assert response.headers["location"] == attempt_url
    assert unknown.status_code == 404
    assert foreign.status_code == 404


def test_answering_completed_attempt_is_409_and_stores_nothing(make_client, db):
    with make_client() as client:
        location = start(client)
        attempt_url = location.removesuffix("/questions/q1")
        db.execute(
            "UPDATE attempt SET status = 'completed', score = 0, completed_at = now()"
            " WHERE id = %s",
            (attempt_url.removeprefix("/attempts/"),),
        )
        response = answer(client, location, "b")

    assert response.status_code == 409
    assert stored_answers(db) == []


def test_resume_completes_attempt_when_quiz_edit_leaves_nothing_unanswered(make_client, db, five):
    with make_client() as client:
        attempt_url = start(client, "five").removesuffix("/questions/q1")
        for qid, choice in zip(["q1", "q2", "q3", "q4"], "bbab", strict=True):
            answer(client, f"{attempt_url}/questions/{qid}", choice)
        player_id = client.cookies["player_id"]

    write_quiz(five, ["q2", "q3", "q4"])
    with make_client() as client:
        client.cookies.set("player_id", player_id)
        resume = client.get(attempt_url, follow_redirects=False)
        result = client.get(f"{attempt_url}/result", follow_redirects=False)

    assert resume.status_code == 303
    assert resume.headers["location"] == f"{attempt_url}/result"
    assert attempt_row(db, attempt_url) == ("completed", 2, True)
    assert result.status_code == 200
    assert "2 / 3" in result.text
