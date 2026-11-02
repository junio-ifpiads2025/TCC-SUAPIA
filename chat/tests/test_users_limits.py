import asyncio
import json

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from routes.admin import users as admin_users
from routes.admin.common import require_admin, verify_csrf
from services.admin import alert_service, audit_revert, user_admin_service, user_data_service
from services.chat import feedback_service, queue_service as qs, thread_service
from services.shared import acl_service as acl, audit_service, session_service, usage_service


class _Usage:
    prompt_tokens, completion_tokens, total_tokens = 10, 5, 15


@pytest.fixture
def redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    for mod in (qs, session_service, feedback_service, thread_service):
        if hasattr(mod, "get_redis"):
            monkeypatch.setattr(mod, "get_redis", lambda: r)
    events, sent = [], []

    async def noop(*a, **k):
        return None

    async def send(chat_id, texto):
        sent.append((chat_id, texto))

    monkeypatch.setattr(qs.access_log_service, "log_event",
                        lambda chat_id, event, **kw: events.append((chat_id, event, kw)))
    monkeypatch.setattr(qs, "marcar_lida_async", noop)
    monkeypatch.setattr(qs, "iniciar_digitacao_async", noop)
    monkeypatch.setattr(qs, "enviar_texto_async", send)
    monkeypatch.setattr(qs, "get_profile", noop)
    r.events, r.sent = events, sent
    return r


@pytest.fixture
def limits(monkeypatch):
    """Cache de limites do ACL isolado do banco."""
    monkeypatch.setattr(acl, "_limits", {})
    monkeypatch.setattr(acl, "_default_limit", None)
    store = {}

    async def set_setting(key, value):
        store[key] = value

    async def set_limit(chat_id, limit, by):
        store[chat_id] = limit

    monkeypatch.setattr(acl, "_db_set_setting", set_setting)
    monkeypatch.setattr(acl, "_db_set_limit", set_limit)
    return store


def _authenticated(monkeypatch):
    async def yes(c):
        return True
    monkeypatch.setattr(qs, "is_authenticated", yes)


# ── ContextVar e contador de tokens ──────────────────────────────────────────

def test_chat_id_reaches_record_in_thread(redis, monkeypatch):
    rows = []

    async def insert(row):
        rows.append(row)

    async def fake_route(chat_id, content):
        await asyncio.to_thread(usage_service.record, "agent", "gpt-4o", _Usage())
        return "ok", {}

    monkeypatch.setattr(usage_service, "_db_insert", insert)
    monkeypatch.setattr(qs, "route", fake_route)

    async def run():
        usage_service.set_loop(asyncio.get_running_loop())
        item = {"id": "a1", "chat_id": "u1", "provider": "waha", "content": "oi",
                "enqueued_at": "2026-01-01T00:00:00+00:00", "attempts": 0}
        raw = json.dumps(item)
        await redis.lpush(qs.PROCESSING, raw)
        await qs._process_item(raw)
        await asyncio.sleep(0.05)  # gravação agendada da thread no loop
        assert usage_service.current_chat_id.get() is None  # restaurado após o atendimento
        assert await session_service.get_tokens("u1") == 15
    asyncio.run(run())
    assert rows and rows[0]["chat_id"] == "u1" and rows[0]["total_tokens"] == 15


# ── Recusas por limite ───────────────────────────────────────────────────────

def test_token_budget_refuses_and_signals(redis, monkeypatch, limits):
    _authenticated(monkeypatch)
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", 100)

    async def run():
        await session_service.add_tokens("u1", 100)
        await qs.enqueue("u1", "pergunta")
        assert (await qs.stats())["pending"] == 0
        assert redis.sent[-1] == ("u1", qs.TOKEN_BUDGET_TEXT)
        assert redis.events[-1][1] == "rate_limited"
        assert await session_service.pop_limit_exceeded("token_budget") == 1
        await qs.enqueue("u2", "pergunta")  # outro usuário, sem consumo: passa
        assert (await qs.stats())["pending"] == 1
    asyncio.run(run())


def test_user_limit_overrides_default(redis, monkeypatch, limits):
    _authenticated(monkeypatch)
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", 0)

    async def run():
        await acl.set_user_limit("u1", "2")
        for _ in range(3):
            await qs.enqueue("u1", "x")
        assert (await qs.stats())["pending"] == 2
        assert redis.sent[-1] == ("u1", qs.daily_limit_text(2))
        await qs.enqueue("u2", "x")  # segue o padrão global
        assert (await qs.stats())["pending"] == 3
    asyncio.run(run())


def test_limit_alert_rule(monkeypatch, redis):
    sent = []

    async def notify(rule, message):
        sent.append((rule, message))
        return True

    monkeypatch.setattr(alert_service, "notify", notify)

    async def run():
        await session_service.signal_limit_exceeded("token_budget")
        await alert_service._check_limits()
        await alert_service._check_limits()  # contador zerado: não repete
    asyncio.run(run())
    assert [r for r, _ in sent] == ["limit:token_budget"]
    assert "u1" not in sent[0][1]


# ── Limites: validação, auditoria e reversão ─────────────────────────────────

def test_limits_validation_audit_and_revert(limits, audit_rows, monkeypatch):
    async def get(entry_id):
        return {"id": entry_id, "reverted_by": None, **audit_rows[entry_id - 1]}

    async def mark(entry_id, admin):
        audit_rows[entry_id - 1]["reverted_by"] = admin

    monkeypatch.setattr(audit_service, "_db_get", get)
    monkeypatch.setattr(audit_service, "_db_mark_reverted", mark)

    async def run():
        with pytest.raises(ValueError):
            await acl.set_user_limit("u1", "-1")
        with pytest.raises(ValueError):
            await acl.set_default_limit("abc")
        await acl.set_default_limit("40")                     # entrada 1
        await acl.set_user_limit("u1", "5")                   # entrada 2
        assert acl.daily_limit("u1") == 5 and acl.daily_limit("u2") == 40
        await audit_revert.revert(2, "bia")
        assert acl.daily_limit("u1") == 40 and acl.user_limit("u1") is None
        await audit_revert.revert(1, "bia")
        assert acl.default_limit() == config.MAX_DAILY_MESSAGES
    asyncio.run(run())
    assert audit_rows[0]["entity"] == "setting" and audit_rows[0]["after"] == {"value": 40}
    assert audit_rows[1]["entity"] == "daily_limit" and audit_rows[1]["before"] == {"daily_limit": None}


# ── Exclusão LGPD ────────────────────────────────────────────────────────────

def test_erase_clears_postgres_redis_and_queue(redis, monkeypatch, audit_rows):
    erased = []

    async def db_erase(chat_id):
        erased.append(chat_id)
        return {"user_auth": 1, "access_log": 3, "access_rule": 0, "qa_case": 1,
                "llm_usage_anonimizados": 2}

    async def no_reload():
        return None

    monkeypatch.setattr(user_data_service, "_db_erase", db_erase)
    monkeypatch.setattr(acl, "load", no_reload)

    async def run():
        cid, other = "5586999990001@c.us", "5586999990002@c.us"
        await session_service.set_token(cid, "tok")
        await session_service.set_profile(cid, "Ana", None, 60)
        await session_service.increment_rate(cid)
        await session_service.add_tokens(cid, 50)
        await session_service.set_onboarding_link("uuid-1", cid)
        await session_service.increment_rate(other)
        await redis.set(f"suap:thread:{cid}", "[]")
        await redis.set(f"suap:fb:pending:{cid}", "{}")
        for i, c in enumerate((cid, other, cid)):
            await redis.lpush(qs.PENDING if i < 2 else qs.DONE,
                              json.dumps({"id": f"i{i}", "chat_id": c}))

        counts = await user_data_service.erase(cid, user_id=7)

        assert erased == [cid] and counts["fila"] == 2
        assert [k for k in await redis.keys("*") if cid in k] == []
        assert await session_service.get_onboarding_link("uuid-1") is None
        assert await session_service.get_rate(other) == 1
        assert [json.loads(x)["chat_id"] for x in await redis.lrange(qs.PENDING, 0, -1)] == [other]
    asyncio.run(run())
    row = audit_rows[-1]
    assert row["action"] == "erase" and row["entity_id"] == "7"
    assert "5586" not in json.dumps(row)


# ── Rotas ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    calls = []
    user = {"id": 7, "chat_id": "5586999991234@c.us", "matricula": "2026X",
            "terms_accepted_at": None, "created_at": None}

    async def db_search(q, limit):
        calls.append(("search", q))
        return [user]

    async def db_get(user_id):
        return user if user_id == 7 else None

    async def db_events(chat_id, limit):
        return [{"event": "answered", "provider": "waha", "detail": None,
                 "duration_ms": 10, "created_at": None}]

    async def erase(chat_id, user_id=None):
        calls.append(("erase", chat_id, user_id))

    async def set_user_limit(chat_id, value, created_by=None):
        calls.append(("limit", chat_id, value))

    async def zero(c):
        return 0

    monkeypatch.setattr(user_admin_service, "_db_search", db_search)
    monkeypatch.setattr(user_admin_service, "_db_get", db_get)
    monkeypatch.setattr(user_admin_service, "_db_events", db_events)
    monkeypatch.setattr(session_service, "get_rate", zero)
    monkeypatch.setattr(session_service, "get_tokens", zero)
    monkeypatch.setattr(user_data_service, "erase", erase)
    monkeypatch.setattr(acl, "set_user_limit", set_user_limit)
    app = FastAPI()
    app.include_router(admin_users.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.calls = calls
    return c


def test_users_pages_mask_chat_id_and_audit_view(client, audit_rows):
    r = client.get("/admin/users?q=2026")
    assert r.status_code == 200 and "2026X" in r.text and "•••1234" in r.text
    assert "5586999991234" not in r.text and ("search", "2026") in client.calls
    r = client.get("/admin/users/7")
    assert r.status_code == 200 and "5586999991234" not in r.text and "answered" in r.text
    assert audit_rows[-1]["action"] == "view" and audit_rows[-1]["entity_id"] == "7"
    assert client.get("/admin/users/99").status_code == 404


def test_erase_requires_confirmation(client):
    r = client.post("/admin/users/7/erase", data={"confirm": "sim"}, follow_redirects=True)
    assert "digite APAGAR" in r.text and not [c for c in client.calls if c[0] == "erase"]
    r = client.post("/admin/users/7/erase", data={"confirm": "APAGAR"}, follow_redirects=False)
    assert r.status_code == 303 and ("erase", "5586999991234@c.us", 7) in client.calls


def test_user_limit_route(client):
    r = client.post("/admin/users/7/limit", data={"daily_limit": "3"}, follow_redirects=False)
    assert r.status_code == 303 and ("limit", "5586999991234@c.us", "3") in client.calls
