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
    # Return a str, not a TemplateResponse: FastAPI drops the player cookie set by the
    # router dependency when an endpoint returns its own Response object.
    return templates.get_template("home.html").render(total_points=0, rows=rows)
