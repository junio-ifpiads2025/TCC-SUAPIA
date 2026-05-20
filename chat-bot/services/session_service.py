"""
Gerenciamento de sessões e rate limiting via Redis.

Todas as chaves Redis seguem o padrão 'suap:<tipo>:<identificador>'
para evitar colisão com outras aplicações que possam usar o mesmo Redis.

Responsabilidades:
- Token de acesso ao SUAP: armazenado com TTL igual ao tempo de expiração
  retornado pelo SUAP (RN02). Nunca persiste no banco de dados (RN01, RN03).
- Rate limit diário (RN06): contador por chat_id com TTL até meia-noite BRT.
- Link de onboarding: UUID temporário (15min) que associa token ao chat_id.
"""

from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis

from config import REDIS_URL, SESSION_TTL_SECONDS

# Instância Redis lazy-initialized para reutilizar a conexão em toda a aplicação
_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Retorna a instância Redis, criando-a na primeira chamada (singleton)."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


# ── Helpers de chave ─────────────────────────────────────────────────────────

def _token_key(chat_id: str) -> str:
    """Chave Redis para o token SUAP de um usuário."""
    return f"suap:token:{chat_id}"


def _rate_key(chat_id: str) -> str:
    """
    Chave Redis para o contador de mensagens diário.
    Inclui a data atual em BRT para garantir reset automático à meia-noite.
    """
    brt = timezone(timedelta(hours=-3))
    date_str = datetime.now(brt).strftime("%Y%m%d")
    return f"suap:rate:{chat_id}:{date_str}"


def _onboarding_key(uuid_str: str) -> str:
    """Chave Redis para o link de onboarding temporário."""
    return f"suap:onboarding:{uuid_str}"


def _seconds_until_midnight_brt() -> int:
    """
    Calcula os segundos restantes até a meia-noite no fuso BRT (UTC-3).
    Usado para definir o TTL do contador de rate limit, garantindo reset
    exato à meia-noite local (RN06).
    """
    brt = timezone(timedelta(hours=-3))
    now = datetime.now(brt)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds())


# ── Token SUAP ───────────────────────────────────────────────────────────────

async def get_token(chat_id: str) -> str | None:
    """Retorna o token SUAP do usuário, ou None se não autenticado/expirado."""
    return await get_redis().get(_token_key(chat_id))


async def set_token(chat_id: str, token: str, ttl_seconds: int | None = None) -> None:
    """Armazena o token SUAP com TTL. Usa SESSION_TTL_SECONDS como fallback."""
    ttl = ttl_seconds or SESSION_TTL_SECONDS
    await get_redis().setex(_token_key(chat_id), ttl, token)


async def delete_token(chat_id: str) -> None:
    """Remove o token do Redis, efetivamente encerrando a sessão do usuário."""
    await get_redis().delete(_token_key(chat_id))


async def is_authenticated(chat_id: str) -> bool:
    """Retorna True se o usuário possui token válido no Redis."""
    return await get_token(chat_id) is not None


# ── Rate limit diário (RN06) ─────────────────────────────────────────────────

async def increment_rate(chat_id: str) -> int:
    """
    Incrementa o contador de mensagens do dia e retorna o valor atualizado.
    Na primeira mensagem do dia, define o TTL até a meia-noite BRT para que
    o contador seja automaticamente removido pelo Redis sem necessidade de cron.
    """
    r = get_redis()
    key = _rate_key(chat_id)
    count = await r.incr(key)
    if count == 1:
        # Primeiro incremento do dia: define expiração até meia-noite BRT
        await r.expire(key, _seconds_until_midnight_brt())
    return count


# ── Link de onboarding ───────────────────────────────────────────────────────

async def set_onboarding_link(uuid_str: str, chat_id: str, ttl: int = 900) -> None:
    """
    Armazena a associação uuid → chat_id com TTL de 15 minutos (padrão).
    O UUID é gerado em auth_service e enviado ao usuário como link de login.
    """
    await get_redis().setex(_onboarding_key(uuid_str), ttl, chat_id)


async def get_onboarding_link(uuid_str: str) -> str | None:
    """Retorna o chat_id associado ao UUID de onboarding, ou None se expirado."""
    return await get_redis().get(_onboarding_key(uuid_str))


async def delete_onboarding_link(uuid_str: str) -> None:
    """Invalida o link de onboarding após uso para evitar reuso do mesmo link."""
    await get_redis().delete(_onboarding_key(uuid_str))
