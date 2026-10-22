import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db import is_healthy, open_pool
from app.pages import router as pages_router
from app.quizzes import load_quizzes


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.quizzes = load_quizzes(os.environ.get("QUIZ_DIR", "quizzes"))
    with open_pool(os.environ["DATABASE_URL"]) as pool:
        app.state.pool = pool
        yield


app = FastAPI(title="Quiz-lite", lifespan=lifespan)
app.include_router(pages_router)


@app.get("/healthz")
def healthz(request: Request):
    if not is_healthy(request.app.state.pool):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}
