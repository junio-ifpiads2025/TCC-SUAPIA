import asyncio
import functools


def arun(fn):
    """Roda teste async sem plugin (pytest-asyncio não instalado)."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))
    return wrapper


import pytest

from services import access_log_service, guardrail_service as gs, message_router as mr


@pytest.fixture
def env(monkeypatch):
    events, saved, calls = [], [], []

    async def token(chat_id):
        return "tok"

    async def thread(chat_id):
        return []

    async def append(chat_id, q, a):
        saved.append(a)

    monkeypatch.setattr(mr, "get_token", token)
    monkeypatch.setattr(mr.thread_service, "get_thread", thread)
    monkeypatch.setattr(mr.thread_service, "append_messages", append)
    monkeypatch.setattr(mr, "_call_agent", lambda m, t, h: (calls.append(m) or "CPF 123.456.789-00", []))
    monkeypatch.setattr(access_log_service, "log_event",
                        lambda chat_id, event, **kw: events.append((event, kw.get("detail"))))
    yield events, saved, calls
    gs._rules = []


def rule(**kw):
    base = {"id": 1, "name": "r", "description": None, "match_type": "keyword", "pattern": None,
            "response": None, "instruction": None, "priority": 1, "enabled": True}
    base.update(kw)
    return base


@arun
async def test_blocked_input_skips_agent(env, monkeypatch):
    events, saved, calls = env
    gs._rules = gs._build([rule(scope="input", action="block", pattern="proibido", response="Não.")])
    resp, meta = await mr.route("c1", "algo proibido aqui")
    assert resp == "Não." and calls == [] and saved == []
    assert events == [("guardrail_input", "r")]


@arun
async def test_output_masked_before_persist(env):
    events, saved, calls = env
    gs._rules = gs._build([rule(scope="output", action="mask", match_type="regex",
                                pattern=r"\d{3}\.\d{3}\.\d{3}-\d{2}")])
    resp, _ = await mr.route("c1", "oi")
    assert resp == "CPF ***" and saved == ["CPF ***"] and calls == ["oi"]
    assert events == [("guardrail_output", "r")]
