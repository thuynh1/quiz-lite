import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.migrate import migrate
from tests.conftest import TEST_DATABASE_URL


def make_attempt(db) -> uuid.UUID:
    player_id = uuid.uuid4()
    db.execute("INSERT INTO player (id) VALUES (%s)", (player_id,))
    return db.execute(
        "INSERT INTO attempt (player_id, quiz_slug) VALUES (%s, 'alpha') RETURNING id",
        (player_id,),
    ).fetchone()[0]


def test_migrate_second_run_applies_nothing(db):
    assert migrate(TEST_DATABASE_URL) == []
    versions = [row[0] for row in db.execute("SELECT version FROM schema_migrations")]
    assert versions == ["0001_init"]


def test_duplicate_answer_is_rejected(db):
    attempt_id = make_attempt(db)
    insert = (
        "INSERT INTO answer (attempt_id, question_id, selected, is_correct) "
        "VALUES (%s, 'q1', ARRAY['a'], true)"
    )
    db.execute(insert, (attempt_id,))

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, (attempt_id,))


def test_completed_attempt_without_score_is_rejected(db):
    attempt_id = make_attempt(db)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "UPDATE attempt SET status = 'completed', completed_at = now() WHERE id = %s",
            (attempt_id,),
        )


def test_healthz_returns_503_when_db_is_down(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://quiz:quiz@localhost:1/quiz")

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 503
