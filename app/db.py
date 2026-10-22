from datetime import datetime
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


def get_score(pool: ConnectionPool, attempt_id: UUID) -> int:
    with pool.connection() as conn:
        return conn.execute("SELECT score FROM attempt WHERE id = %s", (attempt_id,)).fetchone()[0]


def lock_in_progress(conn: psycopg.Connection, attempt_id: UUID) -> bool:
    status = conn.execute(
        "SELECT status FROM attempt WHERE id = %s FOR UPDATE", (attempt_id,)
    ).fetchone()[0]
    return status == "in_progress"


def complete_if_all_answered(
    conn: psycopg.Connection, attempt_id: UUID, question_ids: list[str]
) -> None:
    conn.execute(
        "UPDATE attempt SET status = 'completed', completed_at = now(), score = ("
        "  SELECT count(*) FILTER (WHERE is_correct) FROM answer"
        "  WHERE attempt_id = %(id)s AND question_id = ANY(%(qids)s))"
        " WHERE id = %(id)s AND status = 'in_progress' AND cardinality(%(qids)s::text[]) = ("
        "  SELECT count(*) FROM answer WHERE attempt_id = %(id)s AND question_id = ANY(%(qids)s))",
        {"id": attempt_id, "qids": question_ids},
    )


def complete_attempt(pool: ConnectionPool, attempt_id: UUID, question_ids: list[str]) -> None:
    with pool.connection() as conn:
        if lock_in_progress(conn, attempt_id):
            complete_if_all_answered(conn, attempt_id, question_ids)


def record_answer(
    pool: ConnectionPool,
    attempt_id: UUID,
    question_ids: list[str],
    question_id: str,
    selected: list[str],
    is_correct: bool,
) -> bool:
    with pool.connection() as conn:
        if not lock_in_progress(conn, attempt_id):
            return False
        inserted = conn.execute(
            "INSERT INTO answer (attempt_id, question_id, selected, is_correct)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING 1",
            (attempt_id, question_id, selected, is_correct),
        ).fetchone()
        if inserted is None:
            return False
        complete_if_all_answered(conn, attempt_id, question_ids)
        return True


def get_answer(
    pool: ConnectionPool, attempt_id: UUID, question_id: str
) -> tuple[list[str], bool] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT selected, is_correct FROM answer WHERE attempt_id = %s AND question_id = %s",
            (attempt_id, question_id),
        ).fetchone()


def derived_values(pool: ConnectionPool, player_id: UUID) -> dict[str, tuple[int | None, datetime]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT quiz_slug, max(score) FILTER (WHERE status = 'completed'), max(started_at)"
            " FROM attempt WHERE player_id = %s GROUP BY quiz_slug",
            (player_id,),
        )
        return {slug: (best, last_started) for slug, best, last_started in rows}
