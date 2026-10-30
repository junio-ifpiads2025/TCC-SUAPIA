import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import admin_access, admin_logs
from routes.admin_common import require_admin, verify_csrf
from services import acl_service as acl, access_log_service as als


@pytest.fixture
def client(monkeypatch):
    calls = []

    async def list_rules(kind=None, q=None):
        return [{"chat_id": "<script>x</script>", "kind": kind, "reason": "<b>r</b>",
                 "created_by": "admin", "created_at": None}] if kind == "block" else []

    async def add_rule(chat_id, kind, reason=None, created_by=None, clear_session=False):
        if kind not in ("allow", "block"):
            raise ValueError("kind inválido")
        calls.append(("add", chat_id, kind, reason, created_by, clear_session))

    async def remove_rule(chat_id):
        calls.append(("rm", chat_id))

    async def list_logs(**kw):
        calls.append(("logs", kw))
        return [{"id": 1, "chat_id": "c", "provider": "waha", "event": "blocked",
                 "detail": None, "duration_ms": None, "created_at": None}]

    monkeypatch.setattr(acl, "list_rules", list_rules)
    monkeypatch.setattr(acl, "add_rule", add_rule)
    monkeypatch.setattr(acl, "remove_rule", remove_rule)
    monkeypatch.setattr(als, "list_logs", list_logs)
    app = FastAPI()
    app.include_router(admin_access.router)
    app.include_router(admin_logs.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.calls = calls
    return c


def test_access_page_escapes_html(client):
    r = client.get("/admin/access")
    assert r.status_code == 200
    assert "<script>x</script>" not in r.text and "&lt;script&gt;" in r.text


def test_add_and_remove(client):
    r = client.post("/admin/access", data={"chat_id": "n1", "kind": "block", "reason": "spam",
                                            "clear_session": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert ("add", "n1", "block", "spam", "tester", True) in client.calls
    client.post("/admin/access/remove", data={"chat_id": "n1"})
    assert ("rm", "n1") in client.calls


def test_add_invalid_kind_shows_error(client):
    r = client.post("/admin/access", data={"chat_id": "n1", "kind": "x"}, follow_redirects=True)
    assert "Erro" in r.text


def test_logs_filters_and_pagination(client):
    r = client.get("/admin/logs?chat_id=c&event=blocked&date_from=2026-01-02&page=2")
    assert r.status_code == 200 and "blocked" in r.text
    kw = client.calls[-1][1]
    assert kw["chat_id"] == "c" and kw["event"] == "blocked" and kw["offset"] == 50
    assert kw["date_from"].year == 2026 and kw["date_to"] is None
