from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.player import current_player

router = APIRouter(dependencies=[Depends(current_player)])


@router.get("/", response_class=HTMLResponse)
def home():
    return "<!doctype html><title>Quiz-lite</title><h1>Quiz-lite</h1>"
