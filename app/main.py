import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.quizzes import load_quizzes


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.quizzes = load_quizzes(os.environ.get("QUIZ_DIR", "quizzes"))
    yield


app = FastAPI(title="Quiz-lite", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
