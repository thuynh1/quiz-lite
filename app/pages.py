from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import answered_question_ids, create_attempt, get_answer, get_attempt, insert_answer
from app.grading import grade
from app.player import current_player
from app.quizzes import Question, Quiz

router = APIRouter(dependencies=[Depends(current_player)])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
PlayerId = Annotated[UUID, Depends(current_player)]


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    rows = [
        {"quiz": quiz, "best": None, "last_attempted": None}
        for quiz in request.app.state.quizzes.values()
    ]
    return templates.TemplateResponse(request, "home.html", {"total_points": 0, "rows": rows})


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
    if status == "completed" or next_id is None:
        return RedirectResponse(f"/attempts/{attempt_uuid}/result", 303)
    return RedirectResponse(f"/attempts/{attempt_uuid}/questions/{next_id}", 303)


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
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/attempts/{attempt_id}/questions/{qid}", response_class=HTMLResponse)
def show_question(request: Request, attempt_id: str, qid: str, player_id: PlayerId):
    attempt_uuid, quiz, _ = owned_attempt(request, attempt_id, player_id)
    return render_question(request, attempt_uuid, quiz, qid)


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
    attempt_uuid, quiz, _ = owned_attempt(request, attempt_id, player_id)
    _, question = find_question(quiz, qid)
    if error := selection_error(question, selected):
        return render_question(request, attempt_uuid, quiz, qid, error, 422)
    pool = request.app.state.pool
    if not insert_answer(pool, attempt_uuid, qid, selected, grade(question, selected)):
        return render_question(request, attempt_uuid, quiz, qid, status_code=409)
    return RedirectResponse(f"/attempts/{attempt_uuid}/questions/{qid}", 303)
