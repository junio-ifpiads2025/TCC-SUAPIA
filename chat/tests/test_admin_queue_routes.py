import json

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import admin_queue
from routes.admin_common import require_admin, verify_csrf
from services import queue_service as qs



@pytest.fixture
def client(monkeypatch):
    # Cada TestClient roda num loop próprio: cliente fakeredis novo por chamada
    # compartilhando o mesmo servidor.
    server = fakeredis.FakeServer()
    monkeypatch.setattr(qs, "get_redis",
                        lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    app = FastAPI()
    app.include_router(admin_queue.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.server = server
    return c


def _seed(client, key, **kw):
    r = fakeredis.FakeRedis(server=client.server, decode_responses=True)
    item = {"id": "i1", "chat_id": "u1", "provider": "waha", "content": "oi",
            "enqueued_at": "2026-01-01T00:00:00+00:00", "attempts": 0, **kw}
    r.lpush(key, json.dumps(item))
    return r


def test_requires_auth(client):
    # sem override: sem sessão/credenciais nenhuma rota responde 2xx
    # (303 -> /admin/login, 401, 403 (CSRF) ou 503 se o painel estiver desabilitado)
    client.app.dependency_overrides.clear()
    for method, url in [("get", "/admin/queue"), ("get", "/admin/queue/table?which=pending"),
                        ("post", "/admin/queue/i1/cancel"), ("post", "/admin/queue/i1/requeue")]:
        r = getattr(client, method)(url, follow_redirects=False)
        assert r.status_code in (303, 401, 403, 503), url


def test_page_and_tabs(client):
    _seed(client, qs.PENDING)
    r = client.get("/admin/queue")
    assert r.status_code == 200 and "u1" in r.text and "every 5s" in r.text
    assert client.get("/admin/queue/table?which=failed").status_code == 200
    assert client.get("/admin/queue?which=bogus").status_code == 400


def test_xss_escaped(client):
    _seed(client, qs.PENDING, content="<script>alert(1)</script>")
    html = client.get("/admin/queue/table?which=pending").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_cancel(client):
    r = _seed(client, qs.PENDING)
    resp = client.post("/admin/queue/i1/cancel")
    assert resp.status_code == 200
    assert r.llen(qs.PENDING) == 0


def test_requeue(client):
    r = _seed(client, qs.FAILED, attempts=2, error="timeout")
    resp = client.post("/admin/queue/i1/requeue")
    assert resp.status_code == 200
    assert r.llen(qs.FAILED) == 0 and r.llen(qs.PENDING) == 1
    assert json.loads(r.lindex(qs.PENDING, 0))["attempts"] == 0
