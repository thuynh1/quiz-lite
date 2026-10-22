import uuid


def player_count(db) -> int:
    return db.execute("SELECT count(*) FROM player").fetchone()[0]


def test_first_visit_sets_httponly_cookie_and_creates_player(make_client, db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with make_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    assert "Max-Age=34560000" in set_cookie
    assert "Secure" not in set_cookie
    player_id = uuid.UUID(response.cookies["player_id"])
    assert db.execute("SELECT 1 FROM player WHERE id = %s", (player_id,)).fetchone()


def test_returning_visit_creates_no_new_player_and_refreshes_cookie(make_client, db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with make_client() as client:
        first = client.get("/")
        second = client.get("/")

    assert player_count(db) == 1
    assert second.cookies["player_id"] == first.cookies["player_id"]
    assert "Max-Age=34560000" in second.headers["set-cookie"]


def test_garbage_cookie_gets_fresh_player(make_client, db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with make_client() as client:
        client.cookies.set("player_id", "not-a-uuid")
        response = client.get("/")

    player_id = uuid.UUID(response.cookies["player_id"])
    assert db.execute("SELECT 1 FROM player WHERE id = %s", (player_id,)).fetchone()


def test_unknown_uuid_cookie_gets_fresh_player(make_client, db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    unknown = str(uuid.uuid4())
    with make_client() as client:
        client.cookies.set("player_id", unknown)
        response = client.get("/")

    assert response.cookies["player_id"] != unknown
    assert player_count(db) == 1


def test_cookie_is_secure_by_default(make_client, monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    with make_client() as client:
        response = client.get("/")

    assert "Secure" in response.headers["set-cookie"]


def test_healthz_sets_no_cookie(make_client, db):
    with make_client() as client:
        response = client.get("/healthz")

    assert "set-cookie" not in response.headers
    assert player_count(db) == 0
