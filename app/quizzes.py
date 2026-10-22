import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

Id = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]+$")]
Text = Annotated[str, StringConstraints(min_length=1)]


class QuizError(Exception):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Option(StrictModel):
    id: Id
    text: Text


class Question(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"type": {"const": "single"}}},
            "then": {"properties": {"correct": {"maxItems": 1}}},
        }
    )

    id: Id
    prompt: Text
    type: Literal["single", "multi"]
    options: list[Option] = Field(min_length=2)
    correct: list[str] = Field(min_length=1, json_schema_extra={"uniqueItems": True})
    explanation: Text


class Quiz(StrictModel):
    slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
    title: Text
    questions: list[Question] = Field(min_length=1)


def _field_path(loc: tuple[str | int, ...]) -> str:
    path = "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in loc)
    return path.removeprefix(".") or "(root)"


def _semantic_errors(quiz: Quiz, stem: str) -> Iterator[tuple[str, str]]:
    if quiz.slug != stem:
        yield "slug", f"must equal the file name stem {stem!r}"
    question_ids = set()
    for i, question in enumerate(quiz.questions):
        if question.id in question_ids:
            yield f"questions[{i}].id", f"duplicate question id {question.id!r}"
        question_ids.add(question.id)
        option_ids = set()
        for j, option in enumerate(question.options):
            if option.id in option_ids:
                yield f"questions[{i}].options[{j}].id", f"duplicate option id {option.id!r}"
            option_ids.add(option.id)
        correct = f"questions[{i}].correct"
        if len(set(question.correct)) != len(question.correct):
            yield correct, "contains duplicate option ids"
        if question.type == "single" and len(question.correct) != 1:
            yield correct, "a single-select question needs exactly one correct option"
        for option_id in question.correct:
            if option_id not in option_ids:
                yield correct, f"{option_id!r} is not an option id of this question"


def _load_file(path: Path) -> Quiz:
    try:
        quiz = Quiz.model_validate(yaml.safe_load(path.read_text()))
    except yaml.YAMLError as e:
        raise QuizError(f"{path}: (root): invalid YAML: {e}") from e
    except ValidationError as e:
        errors = [(_field_path(err["loc"]), err["msg"]) for err in e.errors()]
    else:
        errors = list(_semantic_errors(quiz, path.stem))
    if errors:
        raise QuizError("\n".join(f"{path}: {field}: {msg}" for field, msg in errors))
    return quiz


def load_quizzes(directory: str | Path) -> dict[str, Quiz]:
    directory = Path(directory)
    if not directory.is_dir():
        raise QuizError(f"{directory}: not a directory")
    if misnamed := sorted(directory.glob("*.yml")):
        raise QuizError("\n".join(f"{path}: rename it to {path.stem}.yaml" for path in misnamed))
    quizzes = {}
    for path in sorted(directory.glob("*.yaml")):
        quiz = _load_file(path)
        quizzes[quiz.slug] = quiz
    return quizzes


def quiz_schema() -> dict:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **Quiz.model_json_schema()}


def main(argv: list[str]) -> None:
    match argv:
        case ["check", directory]:
            try:
                quizzes = load_quizzes(directory)
            except QuizError as e:
                sys.exit(str(e))
            print(f"{len(quizzes)} quizzes ok")
        case ["schema"]:
            print(json.dumps(quiz_schema(), indent=2))
        case _:
            sys.exit("usage: python -m app.quizzes check <dir> | schema")


if __name__ == "__main__":
    main(sys.argv[1:])
