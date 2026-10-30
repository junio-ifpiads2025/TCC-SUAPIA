import json
import time

import fakeredis.aioredis
import pytest

from services import queue_service as qs

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(qs, "get_redis", lambda: r)
    events = []
    monkeypatch.setattr(qs.access_log_service, "log_event",
                        lambda chat_id, event, **kw: events.append((chat_id, event, kw)))
    sent = []

    async def noop(*a, **k):
        return None

    async def send(chat_id, texto):
        sent.append((chat_id, texto))

    monkeypatch.setattr(qs, "marcar_lida_async", noop)
    monkeypatch.setattr(qs, "iniciar_digitacao_async", noop)
    monkeypatch.setattr(qs, "enviar_texto_async", send)
    monkeypatch.setattr(qs, "get_profile", lambda c: noop())
    r.events, r.sent = events, sent
    return r


def _auth(monkeypatch, ok=True, rate=1):
    async def is_auth(c):
        return ok

    async def inc(c):
        return rate

    monkeypatch.setattr(qs, "is_authenticated", is_auth)
    monkeypatch.setattr(qs, "increment_rate", inc)


async def _items(r, key):
    return [json.loads(x) for x in await r.lrange(key, 0, -1)]


async def test_enqueue_and_fifo(redis, monkeypatch):
    _auth(monkeypatch)
    order = []

    async def fake_route(chat_id, content):
        order.append(content)
        return "ok", None

    monkeypatch.setattr(qs, "route", fake_route)
    for c in ("a", "b", "c"):
        await qs.enqueue("u1", c)
    assert (await qs.stats())["pending"] == 3
    for _ in range(3):
        await qs.process_next(timeout=1)
    assert order == ["a", "b", "c"]
    assert await qs.stats() == {"pending": 0, "processing": 0, "failed": 0, "done": 3}
    assert [e[1] for e in redis.events] == ["answered"] * 3
    assert redis.sent[0] == ("u1", "ok")


async def test_enqueue_unauthenticated_and_rate_limit(redis, monkeypatch):
    async def link(c):
        return "http://x"

    monkeypatch.setattr(qs, "generate_onboarding_link", link)
    _auth(monkeypatch, ok=False)
    await qs.enqueue("telegram:9", "oi")
    assert (await qs.stats())["pending"] == 0
    assert redis.events[0][1] == "denied" and redis.events[0][2]["provider"] == "telegram"

    _auth(monkeypatch, ok=True, rate=10**6)
    await qs.enqueue("u1", "oi")
    assert (await qs.stats())["pending"] == 0
    assert redis.events[-1][1] == "rate_limited"


async def test_error_goes_to_failed(redis, monkeypatch):
    _auth(monkeypatch)

    async def boom(c, t):
        raise RuntimeError("falhou")

    monkeypatch.setattr(qs, "route", boom)
    await qs.enqueue("u1", "x")
    await qs.process_next(timeout=1)
    failed = await _items(redis, qs.FAILED)
    assert len(failed) == 1 and "falhou" in failed[0]["error"]
    assert (await qs.stats())["processing"] == 0
    assert redis.events[-1][1] == "failed"


async def test_recover_processing(redis):
    for i in range(2):
        await redis.lpush(qs.PROCESSING, json.dumps({"id": str(i), "chat_id": "u", "content": "x",
                                                      "enqueued_at": "2020-01-01T00:00:00+00:00", "attempts": 0}))
    assert await qs.recover_processing() == 2
    assert await redis.llen(qs.PROCESSING) == 0
    assert await redis.llen(qs.PENDING) == 2


async def _stuck(redis, attempts=0, age_min=10):
    item = {"id": "z", "chat_id": "u", "provider": "waha", "content": "x",
            "enqueued_at": "2020-01-01T00:00:00+00:00", "attempts": attempts}
    await redis.lpush(qs.PROCESSING, json.dumps(item))
    await redis.hset(qs.STARTED, "z", str(time.time() - age_min * 60))


async def test_timeout_returns_to_pending(redis, monkeypatch):
    monkeypatch.setattr(qs, "QUEUE_TIMEOUT_MINUTES", 5)
    monkeypatch.setattr(qs, "QUEUE_MAX_ATTEMPTS", 2)
    await _stuck(redis)
    await qs.cleanup_stale()
    pend = await _items(redis, qs.PENDING)
    assert len(pend) == 1 and pend[0]["attempts"] == 1
    assert await redis.llen(qs.PROCESSING) == 0 and await redis.hlen(qs.STARTED) == 0


async def test_fresh_item_not_touched(redis, monkeypatch):
    monkeypatch.setattr(qs, "QUEUE_TIMEOUT_MINUTES", 5)
    await _stuck(redis, age_min=1)
    await qs.cleanup_stale()
    assert await redis.llen(qs.PROCESSING) == 1


async def test_max_attempts_goes_to_failed(redis, monkeypatch):
    monkeypatch.setattr(qs, "QUEUE_TIMEOUT_MINUTES", 5)
    monkeypatch.setattr(qs, "QUEUE_MAX_ATTEMPTS", 2)
    await _stuck(redis, attempts=1)
    await qs.cleanup_stale()
    failed = await _items(redis, qs.FAILED)
    assert len(failed) == 1 and failed[0]["error"] == "timeout"
    assert await redis.llen(qs.PENDING) == 0


async def test_cancel_and_requeue(redis, monkeypatch):
    _auth(monkeypatch)
    await qs.enqueue("u1", "a")
    item = (await qs.list_items("pending"))[0]
    assert await qs.cancel(item["id"]) is True
    assert await qs.cancel(item["id"]) is False
    assert (await qs.stats())["pending"] == 0

    item["attempts"], item["error"] = 2, "timeout"
    await redis.lpush(qs.FAILED, json.dumps(item))
    assert await qs.requeue(item["id"]) is True
    assert await qs.requeue(item["id"]) is False
    pend = await qs.list_items("pending")
    assert pend[0]["attempts"] == 0 and "error" not in pend[0]
    assert (await qs.stats())["failed"] == 0


async def test_cancel_only_pending(redis):
    await redis.lpush(qs.PROCESSING, json.dumps({"id": "p", "chat_id": "u", "content": "x"}))
    assert await qs.cancel("p") is False


async def test_list_items_pending_oldest_first(redis, monkeypatch):
    _auth(monkeypatch)
    for c in ("a", "b"):
        await qs.enqueue("u1", c)
    assert [i["content"] for i in await qs.list_items("pending")] == ["a", "b"]
    with pytest.raises(ValueError):
        await qs.list_items("x")
