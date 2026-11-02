"""
Consumo de tokens da API do LLM (tabela `llm_usage`) e agregações para o painel.

- `record` é chamado de código síncrono (threads do agente/RAG): agenda a gravação
  no event loop principal e nunca levanta exceção.
- O `chat_id` vem do ContextVar `current_chat_id` (definido pela fila ao atender
  uma mensagem; `asyncio.to_thread` copia o contexto para a thread). Serve ao
  orçamento diário de tokens por usuário (contador no Redis) e à exclusão dos
  dados do titular.
- LGPD: só tokens, modelo, origem e chat_id são gravados — nenhum conteúdo.
  O chat_id é anonimizado (NULL) após ACCESS_LOG_RETENTION_DAYS (`anonymize`).
"""

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

import config
from models.database import AccessLog, AsyncSessionLocal, LlmUsage
from services.shared import logger, session_service

current_chat_id: ContextVar[str | None] = ContextVar("current_chat_id", default=None)

BRT = timezone(timedelta(hours=-3))
_loop: asyncio.AbstractEventLoop | None = None
_tasks: set = set()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Guarda o loop principal (chamado no lifespan) para gravar a partir de threads."""
    global _loop
    _loop = loop


async def _db_insert(row: dict) -> None:
    async with AsyncSessionLocal() as s:
        s.add(LlmUsage(**row))
        await s.commit()


async def _insert(row: dict) -> None:
    try:
        await _db_insert(row)
    except Exception as e:
        logger.warn("USAGE", f"Falha ao gravar consumo de tokens: {e}")
    if row.get("chat_id") and row["total_tokens"]:
        try:
            await session_service.add_tokens(row["chat_id"], row["total_tokens"])
        except Exception as e:
            logger.warn("USAGE", f"Falha ao somar tokens do dia: {type(e).__name__}")


def record(source: str, model: str, usage) -> None:
    """Registra o `usage` de uma resposta OpenAI (objeto ou None). Nunca levanta."""
    try:
        if usage is None:
            return
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or 0) or prompt + completion
        row = {"source": source, "model": model, "chat_id": current_chat_id.get(), "prompt_tokens": prompt,
               "completion_tokens": completion, "total_tokens": total}
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            task = running.create_task(_insert(row))
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
        elif _loop is not None and _loop.is_running():
            asyncio.run_coroutine_threadsafe(_insert(row), _loop)
    except Exception:
        pass


async def _db_anonymize(before: datetime) -> int:
    async with AsyncSessionLocal() as s:
        res = await s.execute(update(LlmUsage).where(
            LlmUsage.created_at < before, LlmUsage.chat_id.is_not(None)).values(chat_id=None))
        await s.commit()
        return res.rowcount or 0


async def anonymize() -> int:
    """Tira o chat_id dos registros mais antigos que ACCESS_LOG_RETENTION_DAYS (LGPD)."""
    before = datetime.now(timezone.utc) - timedelta(days=config.ACCESS_LOG_RETENTION_DAYS)
    n = await _db_anonymize(before)
    if n:
        logger.info("USAGE", f"Anonimizados {n} registro(s) de consumo")
    return n


# ── Agregações ───────────────────────────────────────────────────────────────

def period_start(days: int) -> datetime:
    """Início (00:00 BRT) do primeiro dia de uma janela de `days` dias terminando hoje."""
    today = datetime.now(BRT).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days - 1)


def _day(col):
    return func.date(func.timezone("America/Fortaleza", col))


async def _rows_tokens(since: datetime) -> list[tuple]:
    day = _day(LlmUsage.created_at)
    stmt = (select(day, LlmUsage.model, LlmUsage.source,
                   func.count(), func.sum(LlmUsage.prompt_tokens),
                   func.sum(LlmUsage.completion_tokens), func.sum(LlmUsage.total_tokens))
            .where(LlmUsage.created_at >= since)
            .group_by(day, LlmUsage.model, LlmUsage.source))
    async with AsyncSessionLocal() as s:
        return [tuple(r) for r in (await s.execute(stmt)).all()]


async def _rows_messages(since: datetime) -> list[tuple]:
    day = _day(AccessLog.created_at)
    stmt = (select(day, func.count())
            .where(AccessLog.event == "answered", AccessLog.created_at >= since)
            .group_by(day))
    async with AsyncSessionLocal() as s:
        return [tuple(r) for r in (await s.execute(stmt)).all()]


async def _rows_users(since: datetime) -> list[tuple]:
    day = _day(AccessLog.created_at)
    stmt = (select(day, func.count(func.distinct(AccessLog.chat_id)))
            .where(AccessLog.event == "answered", AccessLog.created_at >= since)
            .group_by(day))
    async with AsyncSessionLocal() as s:
        return [tuple(r) for r in (await s.execute(stmt)).all()]


def estimate_cost(model: str, prompt: int, completion: int) -> float | None:
    """Custo estimado em USD pela tabela MODEL_PRICES; None se o modelo não tem preço."""
    price = config.MODEL_PRICES.get(model)
    if not price:
        return None
    return round((prompt * price[0] + completion * price[1]) / 1_000_000, 4)


async def report(days: int = 30) -> dict:
    """
    Dados do painel de uso para os últimos `days` dias (incluindo hoje).

    Retorna `daily` (uma linha por dia, sem buracos), `by_model`, `by_source`
    e `totals`. Cada linha diária: date, messages, users, calls, prompt,
    completion, total.
    """
    days = max(1, min(days, 365))
    since = period_start(days)
    tokens = await _rows_tokens(since)
    messages = dict(await _rows_messages(since))
    users = dict(await _rows_users(since))

    first = since.date()
    daily = {}
    for i in range(days):
        d = first + timedelta(days=i)
        daily[d] = {"date": d.isoformat(), "messages": int(messages.get(d, 0)),
                    "users": int(users.get(d, 0)), "calls": 0,
                    "prompt": 0, "completion": 0, "total": 0}
    by_model: dict[str, dict] = {}
    by_source: dict[str, dict] = {}
    for d, model, source, calls, prompt, completion, total in tokens:
        vals = {"calls": int(calls), "prompt": int(prompt or 0),
                "completion": int(completion or 0), "total": int(total or 0)}
        if d in daily:
            for k, v in vals.items():
                daily[d][k] += v
        for bucket, key in ((by_model, model), (by_source, source)):
            agg = bucket.setdefault(key, {"name": key, "calls": 0, "prompt": 0, "completion": 0, "total": 0})
            for k, v in vals.items():
                agg[k] += v

    for m in by_model.values():
        m["cost"] = estimate_cost(m["name"], m["prompt"], m["completion"])

    rows = list(daily.values())
    totals = {k: sum(r[k] for r in rows) for k in ("messages", "calls", "prompt", "completion", "total")}
    totals["avg_tokens_per_message"] = round(totals["total"] / totals["messages"]) if totals["messages"] else 0
    # modelos sem preço configurado ficam de fora da soma (cost=None na linha do modelo)
    totals["cost"] = round(sum(m["cost"] or 0 for m in by_model.values()), 4)
    return {
        "days": days,
        "daily": rows,
        "by_model": sorted(by_model.values(), key=lambda r: -r["total"]),
        "by_source": sorted(by_source.values(), key=lambda r: -r["total"]),
        "totals": totals,
    }
