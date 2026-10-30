import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from routes import admin_auth, admin_common
from routes.admin import router
from services import access_log_service


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(admin_common, "ADMIN_PASSWORD", "pw")
    monkeypatch.setattr(admin_common, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(admin_common, "ADMIN_SESSION_SECRET", "segredo")
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(admin_auth, "get_redis", lambda: fake)
    monkeypatch.setattr(admin_auth, "_queue_stats", lambda: {"pending": 1, "processing": 0, "failed": 0})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, follow_redirects=False)


def login(client, password="pw"):
    return client.post("/admin/login", data={"username": "admin", "password": password})


def test_login_ok_sets_cookie_and_dashboard(client, monkeypatch):
    async def answered(event):
        return 7

    monkeypatch.setattr(access_log_service, "count_today", answered)
    r = login(client)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    page = client.get("/admin")
    assert page.status_code == 200 and 'name="csrf-token"' in page.text


def test_dashboard_tolerates_failures(client, monkeypatch):
    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(admin_auth, "_queue_stats", boom)
    login(client)
    assert client.get("/admin").status_code == 200


def test_login_fail(client):
    r = login(client, "errada")
    assert r.status_code == 401 and "set-cookie" not in r.headers


def test_throttle(client):
    for _ in range(5):
        assert login(client, "x").status_code == 401
    assert login(client, "x").status_code == 429
    assert login(client, "pw").status_code == 429


def test_redirect_and_api_401(client):
    r = client.get("/admin")
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"
    assert client.get("/admin/api/knowledge").status_code == 401


def test_csrf_required_on_logout(client):
    login(client)
    assert client.post("/admin/logout").status_code == 403
    token = client.get("/admin").text.split('name="csrf-token" content="')[1].split('"')[0]
    r = client.post("/admin/logout", data={"csrf_token": token})
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"
    # após logout o cookie some: nova tentativa não autenticada
    assert client.get("/admin").status_code == 303


def test_tampered_cookie(client):
    login(client)
    bad = client.cookies.get("admin_session") + "x"
    client.cookies.clear()
    client.cookies.set("admin_session", bad, path="/admin")
    assert client.get("/admin").status_code == 303


def test_expired_cookie(client, monkeypatch):
    login(client)
    monkeypatch.setattr(admin_common, "ADMIN_SESSION_TTL_SECONDS", -1)
    assert client.get("/admin").status_code == 303


def test_foreign_secret_rejected(client):
    value = URLSafeTimedSerializer("outro", salt="admin-session").dumps({"u": "admin", "csrf": "t"})
    client.cookies.set("admin_session", value, path="/admin")
    assert client.get("/admin").status_code == 303


def test_disabled_without_password_or_secret(client, monkeypatch):
    monkeypatch.setattr(admin_common, "ADMIN_PASSWORD", "")
    assert client.get("/admin").status_code == 503
    assert client.get("/admin/login").status_code == 503
    monkeypatch.setattr(admin_common, "ADMIN_PASSWORD", "pw")
    monkeypatch.setattr(admin_common, "ADMIN_SESSION_SECRET", "")
    assert client.get("/admin").status_code == 503
