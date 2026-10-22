from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.player import current_player

router = APIRouter(dependencies=[Depends(current_player)])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    rows = [
        {"quiz": quiz, "best": None, "last_attempted": None}
        for quiz in request.app.state.quizzes.values()
    ]
    return templates.TemplateResponse(request, "home.html", {"total_points": 0, "rows": rows})
