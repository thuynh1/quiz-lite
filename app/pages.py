from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import (
    answered_question_ids,
    complete_attempt,
    create_attempt,
    derived_values,
    get_answer,
    get_attempt,
    get_score,
    record_answer,
)
from app.grading import grade
from app.player import current_player
from app.quizzes import Question, Quiz

router = APIRouter(dependencies=[Depends(current_player)])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
PlayerId = Annotated[UUID, Depends(current_player)]


def format_best(best: int | None, total: int) -> str | None:
    if best is None:
        return None
    percent = (200 * best + total) // (2 * total)
    return f"{best} / {total} | {percent}%"


def format_local(moment: datetime | None, tz: str | None) -> str | None:
    if moment is None:
        return None
    try:
        return moment.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, LookupError, OSError):
        return moment.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC")


@router.get("/", response_class=HTMLResponse)
def home(request: Request, player_id: PlayerId):
    derived = derived_values(request.app.state.pool, player_id)
    tz = request.cookies.get("tz")
    rows = []
    for quiz in request.app.state.quizzes.values():
        best, last_started = derived.get(quiz.slug, (None, None))
        rows.append(
            {
                "quiz": quiz,
                "best": format_best(best, len(quiz.questions)),
                "last_attempted": format_local(last_started, tz),
            }
        )
    total_points = sum(best or 0 for best, _ in derived.values())
    return templates.TemplateResponse(
        request, "home.html", {"total_points": total_points, "rows": rows}
    )


@router.post("/quizzes/{slug}/attempts")
def start_attempt(request: Request, slug: str, player_id: PlayerId):
    quiz = request.app.state.quizzes.get(slug)
    if quiz is None:
        raise HTTPException(404)
    attempt_id = create_attempt(request.app.state.pool, player_id, slug)
    return RedirectResponse(f"/attempts/{attempt_id}/questions/{quiz.questions[0].id}", 303)


def owned_attempt(request: Request, attempt_id: str, player_id: UUID) -> tuple[UUID, Quiz, str]:
    try:
        attempt_uuid = UUID(attempt_id)
    except ValueError:
        raise HTTPException(404) from None
    attempt = get_attempt(request.app.state.pool, attempt_uuid, player_id)
    if attempt is None or attempt[0] not in request.app.state.quizzes:
        raise HTTPException(404)
    quiz_slug, status = attempt
    return attempt_uuid, request.app.state.quizzes[quiz_slug], status


@router.get("/attempts/{attempt_id}")
def resume_attempt(request: Request, attempt_id: str, player_id: PlayerId):
    attempt_uuid, quiz, status = owned_attempt(request, attempt_id, player_id)
    answered = answered_question_ids(request.app.state.pool, attempt_uuid)
    next_id = next((q.id for q in quiz.questions if q.id not in answered), None)
    if status == "in_progress" and next_id is None:
        complete_attempt(request.app.state.pool, attempt_uuid, question_ids(quiz))
        status = "completed"
    if status == "completed":
        return RedirectResponse(f"/attempts/{attempt_uuid}/result", 303)
    return RedirectResponse(f"/attempts/{attempt_uuid}/questions/{next_id}", 303)


@router.get("/attempts/{attempt_id}/result", response_class=HTMLResponse)
def show_result(request: Request, attempt_id: str, player_id: PlayerId):
    attempt_uuid, quiz, status = owned_attempt(request, attempt_id, player_id)
    if status != "completed":
        return RedirectResponse(f"/attempts/{attempt_uuid}", 303)
    score = get_score(request.app.state.pool, attempt_uuid)
    return templates.TemplateResponse(
        request, "result.html", {"quiz": quiz, "score": score, "total": len(quiz.questions)}
    )


def question_ids(quiz: Quiz) -> list[str]:
    return [question.id for question in quiz.questions]


def find_question(quiz: Quiz, qid: str) -> tuple[int, Question]:
    for number, question in enumerate(quiz.questions, 1):
        if question.id == qid:
            return number, question
    raise HTTPException(404)


def render_question(
    request: Request,
    attempt_id: UUID,
    quiz: Quiz,
    qid: str,
    completed: bool,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    number, question = find_question(quiz, qid)
    answer = get_answer(request.app.state.pool, attempt_id, qid)
    return templates.TemplateResponse(
        request,
        "question.html",
        {
            "attempt_id": attempt_id,
            "quiz": quiz,
            "question": question,
            "number": number,
            "total": len(quiz.questions),
            "answer": answer,
            "completed": completed,
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/attempts/{attempt_id}/questions/{qid}", response_class=HTMLResponse)
def show_question(request: Request, attempt_id: str, qid: str, player_id: PlayerId):
    attempt_uuid, quiz, status = owned_attempt(request, attempt_id, player_id)
    return render_question(request, attempt_uuid, quiz, qid, status == "completed")


def selection_error(question: Question, selected: list[str]) -> str | None:
    if not selected:
        return "Pick an option."
    if not set(selected) <= {option.id for option in question.options}:
        return "Pick from the listed options."
    if len(set(selected)) != len(selected):
        return "Pick each option at most once."
    if question.type == "single" and len(selected) > 1:
        return "Pick only one option."
    return None


@router.post("/attempts/{attempt_id}/questions/{qid}", response_class=HTMLResponse)
def submit_answer(
    request: Request,
    attempt_id: str,
    qid: str,
    player_id: PlayerId,
    selected: Annotated[list[str], Form(default_factory=list)],
):
    attempt_uuid, quiz, status = owned_attempt(request, attempt_id, player_id)
    _, question = find_question(quiz, qid)
    if error := selection_error(question, selected):
        return render_question(request, attempt_uuid, quiz, qid, False, error, 422)
    is_correct = grade(question, selected)
    pool = request.app.state.pool
    if not record_answer(pool, attempt_uuid, question_ids(quiz), qid, selected, is_correct):
        return render_question(
            request, attempt_uuid, quiz, qid, status == "completed", status_code=409
        )
    return RedirectResponse(f"/attempts/{attempt_uuid}/questions/{qid}", 303)
