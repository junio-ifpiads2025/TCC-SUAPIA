import asyncio

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from routes.admin import health as admin_health
from routes.admin.common import require_admin, verify_csrf
from services.admin import alert_service as al, health_service as hs
from services.chat import providers, waha_client
from services.chat.providers.telegram import TelegramProvider
from services.chat.providers.waha import WahaProvider


# ── Providers ────────────────────────────────────────────────────────────────

def test_waha_health_and_reconnect(monkeypatch):
    async def status():
        return "SCAN_QR_CODE"

    async def restart():
        return True

    monkeypatch.setattr(waha_client, "session_status_async", status)
    monkeypatch.setattr(waha_client, "restart_session_async", restart)
    p = WahaProvider()
    assert asyncio.run(p.health()) == (False, "sessão: SCAN_QR_CODE")
    assert asyncio.run(p.reconnect()) is True


def test_telegram_health_reports_webhook_error(monkeypatch):
    import services.chat.providers.telegram as tg
    monkeypatch.setattr(tg, "TELEGRAM_BOT_TOKEN", "t")

    async def call(self, method, **params):
        assert method == "getWebhookInfo"
        return {"ok": True, "result": {"url": "https://x/webhook/telegram", "last_error_message": "502"}}

    monkeypatch.setattr(TelegramProvider, "_call", call)
    ok, detail = asyncio.run(TelegramProvider().health())
    assert not ok and "502" in detail


# ── health_service ───────────────────────────────────────────────────────────

def test_check_all_hides_errors_and_times_out(monkeypatch):
    async def good():
        return True, "ok"

    async def boom():
        raise RuntimeError("senha=segredo")

    async def slow():
        await asyncio.sleep(1)
        return True, "tarde"

    monkeypatch.setattr(hs, "PROBE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(hs, "probes", lambda: {"A": good, "B": boom, "C": slow})
    res = {r["name"]: r for r in asyncio.run(hs.check_all())}
    assert res["A"]["ok"] and not res["B"]["ok"] and not res["C"]["ok"]
    assert res["B"]["detail"] == "erro: RuntimeError" and "segredo" not in res["B"]["detail"]
    assert res["C"]["detail"] == "tempo esgotado"


def test_reconnect_is_audited(monkeypatch, audit_rows):
    class P:
        async def reconnect(self):
            return True

    monkeypatch.setattr(config, "MESSAGING_PROVIDERS", ["waha"])
    monkeypatch.setattr(providers, "get_provider", lambda name: P())
    assert asyncio.run(hs.reconnect("waha")) is True
    assert audit_rows[-1]["entity"] == "provider" and audit_rows[-1]["after"] == {"ok": True}
    with pytest.raises(KeyError):
        asyncio.run(hs.reconnect("telegram"))


# ── alert_service ────────────────────────────────────────────────────────────

@pytest.fixture
def sent(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(al.session_service, "get_redis",
                        lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    monkeypatch.setattr(config, "ALERT_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(config, "ALERT_SMTP_HOST", "")
    out = []

    async def tg(message):
        out.append(message)

    monkeypatch.setattr(al, "_SENDERS", {"telegram": tg})
    al._probe_failures.clear()
    return out


def test_notify_cooldown_per_rule(sent):
    async def run():
        assert await al.notify("r1", "fila cheia") is True
        assert await al.notify("r1", "fila cheia") is False   # em silêncio
        assert await al.notify("r2", "outra") is True
    asyncio.run(run())
    assert len(sent) == 2 and "fila cheia" in sent[0]


def test_notify_without_channels(monkeypatch, sent):
    monkeypatch.setattr(config, "ALERT_TELEGRAM_CHAT_ID", "")
    assert asyncio.run(al.notify("r", "x")) is False and sent == []


def test_channel_failure_does_not_raise(monkeypatch, sent):
    async def broken(message):
        raise ConnectionError("smtp")

    monkeypatch.setattr(al, "_SENDERS", {"telegram": broken})
    assert asyncio.run(al.notify("r", "x")) is False


def test_queue_rules(monkeypatch, sent):
    async def stats():
        return {"pending": config.ALERT_QUEUE_MAX_PENDING + 1}

    async def oldest():
        return config.ALERT_PROCESSING_MAX_SECONDS + 10

    monkeypatch.setattr(al.queue_service, "stats", stats)
    monkeypatch.setattr(al.queue_service, "oldest_processing_seconds", oldest)
    asyncio.run(al._check_queue())
    assert len(sent) == 2 and "pendentes" in sent[0] and "em atendimento" in sent[1]


def test_error_rate_needs_min_samples(monkeypatch, sent):
    outcomes = iter([(1, 2), (2, 8)])

    async def db(since):
        return next(outcomes)

    monkeypatch.setattr(al, "_db_outcomes", db)
    asyncio.run(al._check_error_rate())   # 3 amostras: ignora
    assert sent == []
    asyncio.run(al._check_error_rate())   # 8/10 falharam
    assert len(sent) == 1 and "80%" in sent[0]


def test_probe_alerts_after_n_consecutive_failures(monkeypatch, sent):
    monkeypatch.setattr(config, "ALERT_PROBE_FAILURES", 2)
    results = iter([False, True, False, False])

    async def check_all():
        return [{"name": "Redis", "ok": next(results), "detail": "erro: ConnectionError"}]

    monkeypatch.setattr(al.health_service, "check_all", check_all)
    for _ in range(3):
        asyncio.run(al._check_health())
    assert sent == []                     # falha, ok (zera), falha
    asyncio.run(al._check_health())
    assert len(sent) == 1 and "Redis" in sent[0]


# ── Rotas ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    calls = []

    async def check_all():
        return [{"name": "Postgres", "ok": True, "detail": "conectado", "ms": 3, "provider": False},
                {"name": "waha", "ok": False, "detail": "<b>x</b>", "ms": 9, "provider": True}]

    async def last_failure():
        return None

    async def reconnect(name):
        if name != "waha":
            raise KeyError(name)
        calls.append(name)
        return True

    core = {"ok": True}

    async def check_core():
        return core["ok"]

    for n, f in (("check_all", check_all), ("last_failure", last_failure),
                 ("reconnect", reconnect), ("check_core", check_core)):
        monkeypatch.setattr(hs, n, f)
    app = FastAPI()
    app.include_router(admin_health.router)
    app.include_router(admin_health.public_router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.calls, c.core = calls, core
    return c


def test_health_page_and_partial(client):
    r = client.get("/admin/health")
    assert r.status_code == 200 and "Postgres" in r.text and "Reconectar" in r.text
    assert "<b>x</b>" not in r.text
    assert client.get("/admin/health/table").status_code == 200


def test_reconnect_route(client):
    r = client.post("/admin/health/waha/reconnect", follow_redirects=False)
    assert r.status_code == 303 and client.calls == ["waha"]
    r = client.post("/admin/health/foo/reconnect", follow_redirects=True)
    assert "não habilitado" in r.text


def test_public_health_minimal(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    client.core["ok"] = False
    r = client.get("/health")
    assert r.status_code == 503 and r.json() == {"status": "degraded"}
