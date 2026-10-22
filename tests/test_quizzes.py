import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.quizzes import QuizError, load_quizzes, quiz_schema
from app.quizzes import main as quizzes_main

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "quizzes"
ALPHA = (FIXTURES / "alpha.yaml").read_text()


def test_valid_fixtures_load():
    quizzes = load_quizzes(FIXTURES)

    assert sorted(quizzes) == ["alpha", "beta"]
    assert quizzes["alpha"].title == "Alpha Quiz"
    assert [q.id for q in quizzes["alpha"].questions] == ["q1", "q2"]
    assert quizzes["alpha"].questions[1].correct == ["a", "c"]


def test_committed_quizzes_load():
    assert "http-basics" in load_quizzes(ROOT / "quizzes")


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("    correct: [b]\n", "", "questions[0].correct"),
        ("id: q2", "id: q1", "questions[1].id"),
        ("correct: [b]", "correct: [z]", "questions[0].correct"),
        ("correct: [b]", "correct: [a, b]", "questions[0].correct"),
        ("correct: [b]", "correct: [b, b]", "questions[0].correct"),
        (
            "{id: b, text: B}\n    correct",
            "{id: a, text: B}\n    correct",
            "questions[0].options[1].id",
        ),
        ("id: q1", "id: no", "questions[0].id"),
        ("slug: alpha", "slug: other", "slug"),
    ],
    ids=[
        "missing-correct",
        "duplicate-question-id",
        "correct-not-in-options",
        "two-correct-for-single",
        "duplicate-correct",
        "duplicate-option-id",
        "yaml-boolean-id",
        "slug-not-filename",
    ],
)
def test_invalid_quiz_names_file_and_field(tmp_path, old, new, field):
    assert old in ALPHA
    path = tmp_path / "alpha.yaml"
    path.write_text(ALPHA.replace(old, new, 1))

    with pytest.raises(QuizError) as exc:
        load_quizzes(tmp_path)

    assert f"{path}: {field}: " in str(exc.value)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(QuizError, match="not a directory"):
        load_quizzes(tmp_path / "nope")


def test_yml_file_fails_check_and_startup(tmp_path, monkeypatch):
    path = tmp_path / "alpha.yml"
    path.write_text(ALPHA)

    with pytest.raises(SystemExit) as exc:
        quizzes_main(["check", str(tmp_path)])
    assert f"{path}: rename it to alpha.yaml" in str(exc.value.code)

    monkeypatch.setenv("QUIZ_DIR", str(tmp_path))
    with pytest.raises(QuizError, match="rename it to alpha.yaml"), TestClient(app):
        pass


def test_app_startup_with_bad_directory_raises(tmp_path, monkeypatch):
    (tmp_path / "alpha.yaml").write_text(ALPHA.replace("    correct: [b]\n", ""))
    monkeypatch.setenv("QUIZ_DIR", str(tmp_path))

    with pytest.raises(QuizError), TestClient(app):
        pass


def test_app_startup_loads_quizzes(monkeypatch, make_client):
    monkeypatch.setenv("QUIZ_DIR", str(FIXTURES))

    with make_client():
        assert sorted(app.state.quizzes) == ["alpha", "beta"]


def test_committed_schema_matches_generated():
    committed = json.loads((ROOT / "quizzes" / "quiz.schema.json").read_text())

    assert committed == quiz_schema()
