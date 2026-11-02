import asyncio
import csv
import io
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from routes.admin import auth as admin_auth, exports as admin_exports
from routes.admin.common import require_admin, verify_csrf
from services.admin import export_service
from services.shared import access_log_service, audit_service, dashboard_service, usage_service


# ── export_service ───────────────────────────────────────────────────────────

def _parse(lines) -> list[list[str]]:
    return list(csv.reader(io.StringIO("".join(lines))))


def test_csv_neutralizes_formulas():
    rows = [{"a": "=HYPERLINK(\"x\")", "b": "+1", "c": "-2", "d": "@SUM(A1)"},
            {"a": "\tcmd", "b": "normal", "c": -5, "d": None}]
    out = _parse(export_service.csv_lines(rows, ["a", "b", "c", "d"]))
    assert out[0] == ["a", "b", "c", "d"]
    assert out[1] == ["'=HYPERLINK(\"x\")", "'+1", "'-2", "'@SUM(A1)"]
    assert out[2] == ["'\tcmd", "normal", "-5", ""]  # número não é texto: fica como está


def test_csv_serializes_dates_and_json():
    when = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
    out = _parse(export_service.csv_lines([{"t": when, "j": {"k": "=x"}}], ["t", "j"]))
    assert out[1][0] == when.isoformat()
    assert json.loads(out[1][1]) == {"k": "=x"}


def test_mask_chat_id_and_drop_name():
    assert export_service.mask_chat_id("558699998888@c.us") == "•••8888"
    assert export_service.mask_chat_id("123456789") == "•••6789"
    assert export_service.mask_chat_id("admin:ana") == "admin:ana"
    rows = export_service.mask_rows([{"chat_id": "558699998888@c.us", "nome": "Ana", "event": "x"}])
    assert rows == [{"chat_id": "•••8888", "event": "x"}]


# ── custo e dashboard_service ────────────────────────────────────────────────

def test_estimate_cost(monkeypatch):
    monkeypatch.setattr(config, "MODEL_PRICES", {"m": [2.0, 10.0]})
    assert usage_service.estimate_cost("m", 1_000_000, 500_000) == 7.0
    assert usage_service.estimate_cost("desconhecido", 10, 10) is None


def _usage(days):
    start = usage_service.period_start(days).date()
    daily = [{"date": (start + timedelta(days=i)).isoformat(), "messages": 0, "users": 1, "calls": 0,
              "prompt": 0, "completion": 0, "total": 100} for i in range(days)]
    return {"days": days, "daily": daily,
            "by_model": [{"name": "gpt-4o", "calls": 1, "prompt": 1, "completion": 1, "total": 100 * days,
                          "cost": 0.5}],
            "by_source": [], "totals": {"total": 100 * days, "cost": 0.5}}


def test_dashboard_report(monkeypatch):
    days = 7
    today = usage_service.period_start(1).date()

    async def usage(d):
        return _usage(d)

    async def latency(since):
        return [(today, 1200.0, 4800.0)]

    async def events(since):
        return [(today, "answered", 8), (today, "failed", 2), (today, "guardrail_input", 1),
                (today, "guardrail_output", 2), (date(2000, 1, 1), "failed", 99)]

    async def qa(since):
        return [(today, "up", 3), (today, "down", 1), (today, "no_answer", 2)]

    async def active(since):
        return 5

    monkeypatch.setattr(usage_service, "report", usage)
    monkeypatch.setattr(dashboard_service, "_db_latency", latency)
    monkeypatch.setattr(dashboard_service, "_db_events", events)
    monkeypatch.setattr(dashboard_service, "_db_qa", qa)
    monkeypatch.setattr(dashboard_service, "_db_active_users", active)

    rep = asyncio.run(dashboard_service.report(days))
    assert len(rep["daily"]) == days
    last = rep["daily"][-1]
    assert last["p50"] == 1200 and last["p95"] == 4800 and last["guardrail"] == 3
    assert last["error_rate"] == 0.2 and rep["daily"][0]["error_rate"] is None
    t = rep["totals"]
    assert t["failed"] == 2  # evento fora do período é ignorado
    assert t["satisfaction"] == 0.75 and t["no_answer_rate"] == 0.25
    assert t["active_users"] == 5 and t["cost"] == 0.5 and t["p95_max"] == 4800


# ── rotas ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    logged = []
    monkeypatch.setattr(access_log_service, "log_admin", lambda *a, **k: logged.append(a))
    app = FastAPI()
    app.include_router(admin_exports.router)
    app.include_router(admin_auth.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.logged = logged
    return c


def test_logs_csv_masks_and_neutralizes(client, monkeypatch):
    seen = {}

    async def rows(**kw):
        seen.update(kw)
        return [{"id": 1, "chat_id": "558699998888@c.us", "provider": "waha", "event": "answered",
                 "detail": "=cmd", "duration_ms": 12, "created_at": None, "matricula": "2024", "nome": "Ana"}]

    monkeypatch.setattr(access_log_service, "list_logs", rows)
    r = client.get("/admin/logs/export.csv?event=answered&chat_id=5586")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    out = _parse([r.text])
    assert out[0] == export_service.LOG_COLUMNS
    assert out[1][1] == "•••8888" and out[1][5] == "'=cmd" and "Ana" not in r.text
    assert seen["event"] == "answered" and seen["chat_id"] == "5586"
    assert client.logged == [("tester", "export", "kind=logs")]


def test_usage_quality_audit_csv(client, monkeypatch):
    async def usage(days):
        return _usage(days)

    async def qa(kind, limit):
        return [{"id": 1, "created_at": None, "kind": "down", "status": "new", "chat_id": "558699998888@c.us",
                 "question": "@pergunta", "answer": "resp", "note": None}]

    async def audit(**kw):
        return [{"id": 1, "created_at": None, "admin": "ana", "entity": "skill", "action": "update",
                 "entity_id": "s1", "reverted_by": None, "before": {"name": "A"}, "after": {"name": "B"}}]

    monkeypatch.setattr(usage_service, "report", usage)
    monkeypatch.setattr(export_service, "_db_qa_cases", qa)
    monkeypatch.setattr(audit_service, "list_entries", audit)

    u = _parse([client.get("/admin/usage/export.csv?days=7").text])
    assert u[0] == export_service.USAGE_COLUMNS and len(u) == 8
    q = _parse([client.get("/admin/export/quality.csv?kind=down").text])
    assert q[1][4] == "•••8888" and q[1][5] == "'@pergunta"
    a = _parse([client.get("/admin/export/audit.csv").text])
    assert json.loads(a[1][7]) == {"name": "A"}


def test_knowledge_json(client, monkeypatch):
    doc = {"id": "d1", "title": "T", "content": "C", "created_at": None, "updated_at": None}

    async def docs():
        return [doc]

    monkeypatch.setattr(export_service, "_db_knowledge", docs)
    r = client.get("/admin/api/knowledge/export.json")
    assert r.status_code == 200 and r.json() == {"documents": [doc]}
    assert ("tester", "export", "kind=knowledge") in client.logged


def test_dashboard_renders_metrics(client, monkeypatch):
    async def metrics(days):
        rep = _usage(days)
        return {"days": days, "by_model": rep["by_model"],
                "daily": [{"date": d["date"], "p50": None, "p95": None, "answered": 0, "failed": 0,
                           "guardrail": 0, "up": 0, "down": 0, "no_answer": 0, "error_rate": None,
                           "tokens": 0, "users": 0} for d in rep["daily"]],
                "totals": {"p95_max": 4800, "error_rate": 0.1, "guardrail": 4, "active_users": 9,
                           "satisfaction": None, "no_answer_rate": 0.05, "cost": 1.234}}

    seen = []

    async def track(days):
        seen.append(days)
        return await metrics(days)

    monkeypatch.setattr(admin_auth, "_queue_stats", lambda: {"pending": 0, "processing": 0, "failed": 0})
    monkeypatch.setattr(access_log_service, "count_today", lambda e: 0)
    monkeypatch.setattr(dashboard_service, "report", track)
    r = client.get("/admin?days=30")
    assert r.status_code == 200 and "chLatency" in r.text
    assert "4.8 s" in r.text and "10.0%" in r.text and "US$ 1.23" in r.text
    client.get("/admin?days=999")
    assert seen == [30, 7]
