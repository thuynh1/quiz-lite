from app.quizzes import Question


def grade(question: Question, selected: list[str]) -> bool:
    return set(selected) == set(question.correct)
