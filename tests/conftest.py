import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.migrate import migrate

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://quiz:quiz@localhost:5432/quiz_test"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    migrate(TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def truncate_players():
    yield
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE player CASCADE")


@pytest.fixture
def db():
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        yield conn


@pytest.fixture
def make_client(monkeypatch):
    """Each client runs the app lifespan on enter, so each gets a new pool, like a restart."""
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    return lambda: TestClient(app)
