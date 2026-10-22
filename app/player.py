import os
from uuid import UUID

from fastapi import Request, Response

from app.db import create_player, player_exists

COOKIE_NAME = "player_id"
# 400 days: browsers cap cookie lifetime there, so the cookie is refreshed on every visit.
COOKIE_MAX_AGE = 34_560_000


def current_player(request: Request, response: Response) -> UUID:
    pool = request.app.state.pool
    try:
        player_id = UUID(request.cookies[COOKIE_NAME])
    except (KeyError, ValueError):
        player_id = None
    if player_id is None or not player_exists(pool, player_id):
        player_id = create_player(pool)
    response.set_cookie(
        COOKIE_NAME,
        str(player_id),
        max_age=COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "true").lower() not in ("false", "0"),
    )
    return player_id
