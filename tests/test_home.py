import re
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "quizzes"

GAMMA_YAML = """\
slug: gamma
title: Gamma Quiz
questions:
  - id: q1
    prompt: Pick a.
    type: single
    options:
      - {id: a, text: A}
      - {id: b, text: B}
    correct: [a]
    explanation: Because a.
"""


def visible_text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def home_text(make_client) -> str:
    with make_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    return visible_text(response.text)


@pytest.fixture
def quiz_dir(monkeypatch, tmp_path):
    directory = tmp_path / "quizzes"
    shutil.copytree(FIXTURES, directory)
    monkeypatch.setenv("QUIZ_DIR", str(directory))
    return directory


def test_lists_each_quiz_title_and_question_count(make_client, quiz_dir):
    text = home_text(make_client)

    assert "Quiz Questions Best Last Attempted" in text
    assert "Alpha Quiz 2" in text
    assert "Beta Quiz 2" in text


def test_unattempted_quizzes_show_no_best_and_last_attempted_none(make_client, quiz_dir):
    text = home_text(make_client)

    assert "Total points: 0" in text
    assert "Alpha Quiz 2 — None" in text
    assert "Beta Quiz 2 — None" in text


def test_new_quiz_file_appears_after_restart(make_client, quiz_dir):
    assert "Gamma Quiz" not in home_text(make_client)

    (quiz_dir / "gamma.yaml").write_text(GAMMA_YAML)

    assert "Gamma Quiz 1 — None" in home_text(make_client)
