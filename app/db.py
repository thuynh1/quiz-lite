from uuid import UUID, uuid4

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout


def open_pool(url: str) -> ConnectionPool:
    # wait=False: startup must not hang when Postgres is down; /healthz reports it instead.
    pool = ConnectionPool(url, min_size=1, max_size=10, timeout=2, open=False)
    pool.open(wait=False)
    return pool


def is_healthy(pool: ConnectionPool) -> bool:
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return True
    except (PoolTimeout, psycopg.OperationalError):
        return False


def player_exists(pool: ConnectionPool, player_id: UUID) -> bool:
    with pool.connection() as conn:
        return (
            conn.execute("SELECT 1 FROM player WHERE id = %s", (player_id,)).fetchone() is not None
        )


def create_player(pool: ConnectionPool) -> UUID:
    player_id = uuid4()
    with pool.connection() as conn:
        conn.execute("INSERT INTO player (id) VALUES (%s)", (player_id,))
    return player_id


def create_attempt(pool: ConnectionPool, player_id: UUID, quiz_slug: str) -> UUID:
    with pool.connection() as conn:
        return conn.execute(
            "INSERT INTO attempt (player_id, quiz_slug) VALUES (%s, %s) RETURNING id",
            (player_id, quiz_slug),
        ).fetchone()[0]


def get_attempt(pool: ConnectionPool, attempt_id: UUID, player_id: UUID) -> tuple[str, str] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT quiz_slug, status FROM attempt WHERE id = %s AND player_id = %s",
            (attempt_id, player_id),
        ).fetchone()


def answered_question_ids(pool: ConnectionPool, attempt_id: UUID) -> set[str]:
    with pool.connection() as conn:
        rows = conn.execute("SELECT question_id FROM answer WHERE attempt_id = %s", (attempt_id,))
        return {question_id for (question_id,) in rows}
