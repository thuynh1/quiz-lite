from fastapi import FastAPI

app = FastAPI(title="Quiz-lite")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
