import asyncio

import pytest

import config
from services import access_log_service as als

pytestmark = pytest.mark.anyio


async def _capture(monkeypatch):
    rows = []

    async def insert(row):
        rows.append(row)

    monkeypatch.setattr(als, "_db_insert", insert)
    return rows


async def test_log_event_is_async_and_hides_content(monkeypatch):
    rows = await _capture(monkeypatch)
    monkeypatch.setattr(config, "ACCESS_LOG_STORE_CONTENT", False)
    als.log_event("c1", "received", provider="waha", detail="minha senha é 123")
    await asyncio.sleep(0.01)
    assert len(rows) == 1
    assert "senha" not in rows[0]["detail"] and rows[0]["detail"].startswith("len=")


async def test_structured_detail_kept_and_content_optional(monkeypatch):
    rows = await _capture(monkeypatch)
    monkeypatch.setattr(config, "ACCESS_LOG_STORE_CONTENT", False)
    als.log_event("c1", "failed", detail="reason=timeout")
    monkeypatch.setattr(config, "ACCESS_LOG_STORE_CONTENT", True)
    als.log_event("c1", "received", detail="texto livre")
    await asyncio.sleep(0.01)
    assert [r["detail"] for r in rows] == ["reason=timeout", "texto livre"]


def test_log_event_without_loop_does_not_raise():
    als.log_event("c1", "received")


async def test_log_event_swallows_db_errors(monkeypatch):
    async def boom(row):
        raise RuntimeError("db down")

    monkeypatch.setattr(als, "_db_insert", boom)
    als.log_event("c1", "received")
    await asyncio.sleep(0.01)


async def test_purge_uses_retention(monkeypatch):
    seen = {}

    async def purge(before):
        seen["before"] = before
        return 3

    monkeypatch.setattr(als, "_db_purge", purge)
    monkeypatch.setattr(config, "ACCESS_LOG_RETENTION_DAYS", 10)
    assert await als.purge() == 3
    from datetime import datetime, timezone
    delta = datetime.now(timezone.utc) - seen["before"]
    assert 9.9 < delta.total_seconds() / 86400 < 10.1


async def test_count_today_tolerates_failure(monkeypatch):
    async def boom(event, since):
        raise RuntimeError

    monkeypatch.setattr(als, "_db_count_since", boom)
    assert await als.count_today("blocked") == 0


async def test_log_admin_event_shape(monkeypatch):
    rows = []

    async def insert(row):
        rows.append(row)

    monkeypatch.setattr(als, "_db_insert", insert)
    als.log_admin("admin", "acl_add", "kind=allow alvo=5586999@c.us")
    await asyncio.gather(*list(als._tasks))
    assert rows == [{"chat_id": "admin:admin", "event": "admin_acl_add", "provider": "admin",
                     "detail": "kind=allow alvo=5586999@c.us", "duration_ms": None}]
