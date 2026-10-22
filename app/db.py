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
