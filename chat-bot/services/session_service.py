from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis

from config import REDIS_URL, SESSION_TTL_SECONDS

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


# ── Key helpers ──────────────────────────────────────────────────────────────

def _token_key(chat_id: str) -> str:
    return f"suap:token:{chat_id}"


def _rate_key(chat_id: str) -> str:
    brt = timezone(timedelta(hours=-3))
    date_str = datetime.now(brt).strftime("%Y%m%d")
    return f"suap:rate:{chat_id}:{date_str}"


def _onboarding_key(uuid_str: str) -> str:
    return f"suap:onboarding:{uuid_str}"


def _seconds_until_midnight_brt() -> int:
    brt = timezone(timedelta(hours=-3))
    now = datetime.now(brt)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds())


# ── Token ────────────────────────────────────────────────────────────────────

async def get_token(chat_id: str) -> str | None:
    return await get_redis().get(_token_key(chat_id))


async def set_token(chat_id: str, token: str, ttl_seconds: int | None = None) -> None:
    ttl = ttl_seconds or SESSION_TTL_SECONDS
    await get_redis().setex(_token_key(chat_id), ttl, token)


async def delete_token(chat_id: str) -> None:
    await get_redis().delete(_token_key(chat_id))


async def is_authenticated(chat_id: str) -> bool:
    return await get_token(chat_id) is not None


# ── Rate limit (RN06) ────────────────────────────────────────────────────────

async def increment_rate(chat_id: str) -> int:
    r = get_redis()
    key = _rate_key(chat_id)
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, _seconds_until_midnight_brt())
    return count


# ── Onboarding link ──────────────────────────────────────────────────────────

async def set_onboarding_link(uuid_str: str, chat_id: str, ttl: int = 900) -> None:
    await get_redis().setex(_onboarding_key(uuid_str), ttl, chat_id)


async def get_onboarding_link(uuid_str: str) -> str | None:
    return await get_redis().get(_onboarding_key(uuid_str))


async def delete_onboarding_link(uuid_str: str) -> None:
    await get_redis().delete(_onboarding_key(uuid_str))
