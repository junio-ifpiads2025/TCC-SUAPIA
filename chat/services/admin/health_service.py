"""
Saúde do sistema: sondas das dependências e reconexão dos providers.

Cada sonda devolve (ok, detalhe). O detalhe é curto e nunca traz segredo nem dado
pessoal: erros viram só o nome do tipo da exceção. Sondas que excedem
PROBE_TIMEOUT_S contam como falha. A OpenAI não é chamada (custaria tokens):
vale a chave configurada mais a data do último consumo registrado.
"""

import asyncio
import time

import httpx
from sqlalchemy import func, select, text

import config
from models.database import AccessLog, AsyncSessionLocal, LlmUsage
from services.chat import providers
from services.shared import audit_service, session_service

PROBE_TIMEOUT_S = 6.0
_OPENAI_PLACEHOLDER = "sua-chave-openai"


# ── Sondas ───────────────────────────────────────────────────────────────────

async def _postgres() -> tuple[bool, str]:
    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT 1"))
    return True, "conectado"


async def _redis() -> tuple[bool, str]:
    await session_service.get_redis().ping()
    return True, "conectado"


async def _vector_store() -> tuple[bool, str]:
    """As coleções dos manuais e da base de conhecimento existem no pgvector."""
    wanted = [config.PGVECTOR_COLLECTION, config.KNOWLEDGE_COLLECTION]
    async with AsyncSessionLocal() as s:
        rows = await s.execute(text("SELECT name FROM langchain_pg_collection WHERE name = ANY(:n)"),
                               {"n": wanted})
        found = {r[0] for r in rows}
    missing = [c for c in wanted if c not in found]
    return (False, f"coleção ausente: {', '.join(missing)}") if missing else (True, "coleções presentes")


async def _suap() -> tuple[bool, str]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{config.SUAP_BASE_URL.rstrip('/')}/api/")
    return resp.status_code < 500, f"HTTP {resp.status_code}"


async def _db_last_llm_usage():
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(func.max(LlmUsage.created_at)))).scalar_one_or_none()


async def _openai() -> tuple[bool, str]:
    if not config.OPENAI_API_KEY or config.OPENAI_API_KEY == _OPENAI_PLACEHOLDER:
        return False, "OPENAI_API_KEY não configurada"
    last = await _db_last_llm_usage()
    when = last.strftime("%d/%m/%Y %H:%M") if last else "nenhum registrado"
    return True, f"chave configurada; último uso: {when}"


def _provider_probe(name: str):
    async def probe() -> tuple[bool, str]:
        return await providers.get_provider(name).health()
    return probe


def probes() -> dict:
    """Nome exibido → sonda. Providers entram conforme MESSAGING_PROVIDERS."""
    out = {"Postgres": _postgres, "Redis": _redis, "Vector store": _vector_store,
           "SUAP": _suap, "OpenAI": _openai}
    for name in config.MESSAGING_PROVIDERS:
        out[name] = _provider_probe(name)
    return out


async def _run(name: str, probe) -> dict:
    t0 = time.perf_counter()
    try:
        ok, detail = await asyncio.wait_for(probe(), PROBE_TIMEOUT_S)
    except asyncio.TimeoutError:
        ok, detail = False, "tempo esgotado"
    except Exception as e:
        ok, detail = False, f"erro: {type(e).__name__}"
    return {"name": name, "ok": bool(ok), "detail": detail,
            "ms": int((time.perf_counter() - t0) * 1000),
            "provider": name in config.MESSAGING_PROVIDERS}


async def check_all() -> list[dict]:
    """Roda todas as sondas em paralelo."""
    return list(await asyncio.gather(*(_run(n, p) for n, p in probes().items())))


async def check_core() -> bool:
    """Checagem mínima e barata para o /health público: Postgres e Redis."""
    results = await asyncio.gather(_run("Postgres", _postgres), _run("Redis", _redis))
    return all(r["ok"] for r in results)


async def _db_last_failure():
    async with AsyncSessionLocal() as s:
        return (await s.execute(
            select(func.max(AccessLog.created_at)).where(AccessLog.event == "failed"))).scalar_one_or_none()


async def last_failure():
    """Data do último atendimento com falha no log de acesso (None se nenhum ou erro)."""
    try:
        return await _db_last_failure()
    except Exception:
        return None


async def reconnect(name: str) -> bool:
    """Reconecta o provider habilitado `name` e audita. KeyError se não habilitado."""
    if name not in config.MESSAGING_PROVIDERS:
        raise KeyError(name)
    ok = await providers.get_provider(name).reconnect()
    await audit_service.record("reconnect", "provider", name, None, {"ok": ok})
    return ok
