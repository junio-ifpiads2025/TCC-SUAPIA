import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from routes import webhook
from services import acl_service as acl, access_log_service as als


class FakeProvider:
    async def parse_webhook(self, request):
        return SimpleNamespace(chat_id="u1", text="segredo", message_id="m1")


@pytest.fixture
def env(monkeypatch):
    queue, logs = [], []

    async def enqueue(chat_id, text, mid):
        queue.append(chat_id)

    monkeypatch.setattr(webhook, "enqueue", enqueue)
    monkeypatch.setattr(webhook, "get_provider", lambda name: FakeProvider())
    monkeypatch.setattr(webhook, "qualify", lambda p, c: f"{p}:{c}")
    monkeypatch.setattr(als, "log_event", lambda chat_id, event, **kw: logs.append((chat_id, event, kw)))
    monkeypatch.setattr(config, "RESPONDER_QUALQUER_NUMERO", False)
    acl._allow.clear(); acl._block.clear()
    app = FastAPI()
    app.include_router(webhook.router)
    return TestClient(app), queue, logs


def test_blocked_not_queued_and_logged(env):
    client, queue, logs = env
    acl._allow.add("waha:u1"); acl._block.add("waha:u1")
    assert client.post("/webhook").json() == {"status": "ok"}
    assert queue == [] and logs[0][:2] == ("waha:u1", "blocked")


def test_denied(env):
    client, queue, logs = env
    assert client.post("/webhook").json() == {"status": "ok"}
    assert queue == [] and logs[0][1] == "denied"


def test_allowed_queued_without_message_text(env):
    client, queue, logs = env
    acl._allow.add("waha:u1")
    client.post("/webhook")
    assert queue == ["waha:u1"] and logs[0][1] == "received"
    assert "segredo" not in str(logs[0])


def test_any_number_mode_still_blocks(env, monkeypatch):
    client, queue, logs = env
    monkeypatch.setattr(config, "RESPONDER_QUALQUER_NUMERO", True)
    client.post("/webhook")
    assert queue == ["waha:u1"]
    acl._block.add("waha:u1")
    client.post("/webhook")
    assert queue == ["waha:u1"]
