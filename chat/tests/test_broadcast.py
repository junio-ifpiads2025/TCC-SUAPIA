import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from routes.admin import broadcast as admin_broadcast
from routes.admin.common import require_admin, verify_csrf
from services.admin import broadcast_service as bs
from services.shared import acl_service


@pytest.fixture
def store(monkeypatch):
    rows, sent = {}, []

    async def accepted():
        return ["5586911111111@c.us", "5586922222222@c.us", "5586933333333@c.us"]

    async def insert(admin, text):
        i = len(rows) + 1
        rows[i] = {"id": i, "admin": admin, "text": text, "status": "draft", "total": 0,
                   "sent": 0, "failed": 0, "created_at": None}
        return dict(rows[i])

    async def get(i):
        return dict(rows[i]) if i in rows else None

    async def upd(i, **v):
        rows[i].update(v)

    async def lst(limit):
        return list(rows.values())

    async def enviar(chat_id, text):
        if chat_id.startswith("5586922"):
            raise RuntimeError("provider fora")
        sent.append((chat_id, text))

    for n, f in (("_db_accepted_chat_ids", accepted), ("_db_insert", insert), ("_db_get", get),
                 ("_db_update", upd), ("_db_list", lst)):
        monkeypatch.setattr(bs, n, f)
    monkeypatch.setattr(bs.messaging_client, "enviar_texto_async", enviar)
    monkeypatch.setattr(config, "BROADCAST_DELAY_SECONDS", 0)
    monkeypatch.setattr(acl_service, "check",
                        lambda cid: "blocked" if cid.startswith("5586933") else "ok")
    return rows, sent


def test_mask_hides_number():
    assert bs.mask_chat_id("5586999991234@c.us") == "•••1234"
    assert bs.mask_chat_id("12") == "•••"


def test_preview_excludes_blocked_and_masks(store):
    p = asyncio.run(bs.preview())
    assert p == {"total": 2, "sample": ["•••1111", "•••2222"]}


def test_send_counts_and_audits(store, audit_rows):
    rows, sent = store

    async def run():
        b = await bs.create("  Aviso  ", "ana")
        await bs.send(b["id"])
        await bs._tasks[b["id"]]
        return b["id"]
    bid = asyncio.run(run())
    assert sent == [("5586911111111@c.us", "Aviso")]
    assert rows[bid]["status"] == "done"
    assert (rows[bid]["total"], rows[bid]["sent"], rows[bid]["failed"]) == (2, 1, 1)
    assert [r["action"] for r in audit_rows] == ["create", "send"]
    with pytest.raises(bs.BroadcastError):
        asyncio.run(bs.send(bid))


def test_cancel_running_stops_before_next(store, monkeypatch):
    rows, sent = store
    monkeypatch.setattr(config, "BROADCAST_DELAY_SECONDS", 0.05)

    async def run():
        b = await bs.create("Aviso", "ana")
        await bs.send(b["id"])
        await asyncio.sleep(0.01)          # primeiro envio feito, dormindo no intervalo
        await bs.cancel(b["id"])
        await bs._tasks[b["id"]]
        return b["id"]
    bid = asyncio.run(run())
    assert rows[bid]["status"] == "cancelled" and len(sent) == 1
    assert rows[bid]["sent"] + rows[bid]["failed"] == 1


def test_validation_and_cancel_draft(store):
    rows, _ = store
    with pytest.raises(bs.BroadcastError):
        asyncio.run(bs.create("   ", "ana"))
    with pytest.raises(bs.BroadcastError):
        asyncio.run(bs.create("x" * (bs.MAX_TEXT_LEN + 1), "ana"))
    b = asyncio.run(bs.create("Aviso", "ana"))
    asyncio.run(bs.cancel(b["id"]))
    assert rows[b["id"]]["status"] == "cancelled"
    with pytest.raises(bs.BroadcastError):
        asyncio.run(bs.cancel(b["id"]))


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(admin_broadcast.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


def test_routes_flow(client, store):
    rows, _ = store
    r = client.post("/admin/broadcast", data={"text": "<b>Oi</b>"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("id=1")
    page = client.get("/admin/broadcast?id=1")
    assert "&lt;b&gt;Oi&lt;/b&gt;" in page.text and "<b>Oi</b>" not in page.text
    assert "•••1111" in page.text and "5586911111111" not in page.text
    assert "Confirmar envio" in page.text
    r = client.post("/admin/broadcast/1/cancel", follow_redirects=True)
    assert "Envio cancelado" in r.text and rows[1]["status"] == "cancelled"
    r = client.post("/admin/broadcast/1/send", follow_redirects=True)
    assert "Só um rascunho" in r.text
    assert client.get("/admin/broadcast/1/progress").status_code == 200
    assert client.get("/admin/broadcast/99/progress").status_code == 404
    r = client.post("/admin/broadcast", data={"text": " "}, follow_redirects=True)
    assert "Erro" in r.text
