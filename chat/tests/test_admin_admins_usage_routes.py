from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import admin_admins, admin_logs, admin_usage
from routes.admin_common import require_admin, verify_csrf
from services import access_log_service, admin_user_service, pdf_report, usage_service


def _report(days=3):
    daily = [{"date": f"2026-10-{28 + i}", "messages": i, "users": i, "calls": i * 2,
              "prompt": i * 100, "completion": i * 50, "total": i * 150} for i in range(days)]
    return {"days": days, "daily": daily,
            "by_model": [{"name": "gpt-4o", "calls": 6, "prompt": 300, "completion": 150, "total": 450}],
            "by_source": [{"name": "agent", "calls": 6, "prompt": 300, "completion": 150, "total": 450}],
            "totals": {"messages": 3, "calls": 6, "prompt": 300, "completion": 150, "total": 450,
                       "avg_tokens_per_message": 150}}


@pytest.fixture
def client():
    app = FastAPI()
    for m in (admin_admins, admin_usage, admin_logs):
        app.include_router(m.router)
    app.dependency_overrides[require_admin] = lambda: "2024001"
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app, follow_redirects=False)


def test_admins_page_and_add_remove(client, monkeypatch):
    calls = []

    async def lst():
        return [{"matricula": "2024001", "added_by": "admin",
                 "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
                {"matricula": "2024002", "added_by": "2024001", "created_at": None}]

    async def add(m, added_by):
        calls.append(("add", m, added_by))
        return m

    async def rem(m):
        calls.append(("rem", m))

    monkeypatch.setattr(admin_user_service, "list_admins", lst)
    monkeypatch.setattr(admin_user_service, "add_admin", add)
    monkeypatch.setattr(admin_user_service, "remove_admin", rem)
    monkeypatch.setattr(access_log_service, "log_admin", lambda *a, **k: None)

    page = client.get("/admin/admins")
    assert page.status_code == 200 and "2024002" in page.text
    assert client.post("/admin/admins", data={"matricula": "2024003"}).status_code == 303
    client.post("/admin/admins/remove", data={"matricula": "2024002"})
    assert calls == [("add", "2024003", "2024001"), ("rem", "2024002")]


def test_admin_cannot_remove_self(client, monkeypatch):
    async def rem(m):
        raise AssertionError("não pode remover a si mesmo")

    monkeypatch.setattr(admin_user_service, "remove_admin", rem)
    r = client.post("/admin/admins/remove", data={"matricula": "2024001"})
    assert r.status_code == 303 and "voc%C3%AA" in r.headers["location"] or "você" in r.headers["location"]


def test_add_invalid_matricula(client):
    r = client.post("/admin/admins", data={"matricula": "a b;"})
    assert r.status_code == 303 and "Erro" in r.headers["location"]


def test_usage_page_and_pdf(client, monkeypatch):
    seen = []

    async def rep(days):
        seen.append(days)
        return _report()

    monkeypatch.setattr(usage_service, "report", rep)
    page = client.get("/admin/usage?days=7")
    assert page.status_code == 200 and "chTokens" in page.text and "gpt-4o" in page.text
    pdf = client.get("/admin/usage/export.pdf?days=999")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]
    assert seen == [7, 30]  # período inválido cai no padrão


def test_logs_pdf(client, monkeypatch):
    async def rows(**kw):
        return [{"id": 1, "chat_id": "5586@c.us", "provider": "waha", "event": "answered", "detail": "len=3",
                 "duration_ms": 12, "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
                 "matricula": "2024001", "nome": "Ana"}]

    monkeypatch.setattr(access_log_service, "list_logs", rows)
    r = client.get("/admin/logs/export.pdf?event=answered")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_pdf_empty_data():
    rep = _report(1)
    rep["by_model"], rep["by_source"] = [], []
    assert pdf_report.usage_report_pdf(rep).startswith(b"%PDF")
    assert pdf_report.logs_pdf([], "").startswith(b"%PDF")


class _Usage:
    prompt_tokens, completion_tokens, total_tokens = 10, 5, 15


def test_record_inserts(monkeypatch):
    import asyncio
    rows = []

    async def ins(row):
        rows.append(row)

    async def run():
        usage_service.record("agent", "gpt-4o", _Usage())
        usage_service.record("agent", "gpt-4o", None)  # ignora sem usage
        await asyncio.sleep(0)

    monkeypatch.setattr(usage_service, "_insert", ins)
    asyncio.run(run())
    assert rows == [{"source": "agent", "model": "gpt-4o", "prompt_tokens": 10,
                     "completion_tokens": 5, "total_tokens": 15}]


def test_record_without_loop_is_silent(monkeypatch):
    monkeypatch.setattr(usage_service, "_loop", None)
    usage_service.record("rag", "gpt-4o-mini", _Usage())  # não levanta
