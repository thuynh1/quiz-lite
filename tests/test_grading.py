import pytest

from app.grading import grade
from app.quizzes import Question

OPTIONS = [{"id": i, "text": i.upper()} for i in "abcd"]


def question(type_, correct):
    return Question(
        id="q1", prompt="?", type=type_, options=OPTIONS, correct=correct, explanation="."
    )


@pytest.mark.parametrize(
    ("type_", "correct", "selected", "expected"),
    [
        ("single", ["b"], ["b"], True),
        ("single", ["b"], ["a"], False),
        ("multi", ["a", "c", "d"], ["d", "a", "c"], True),
        ("multi", ["a", "c", "d"], ["a", "c"], False),
        ("multi", ["a", "c"], ["a", "b", "c"], False),
    ],
    ids=["single-correct", "single-wrong", "multi-exact", "multi-subset", "multi-superset"],
)
def test_grade_is_exact_set_match(type_, correct, selected, expected):
    assert grade(question(type_, correct), selected) is expected
