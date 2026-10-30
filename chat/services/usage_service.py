"""
Consumo de tokens da API do LLM (tabela `llm_usage`) e agregações para o painel.

- `record` é chamado de código síncrono (threads do agente/RAG): agenda a gravação
  no event loop principal e nunca levanta exceção.
- LGPD: só tokens, modelo e origem são gravados — nenhum conteúdo nem identificador.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.database import AccessLog, AsyncSessionLocal, LlmUsage
from services import logger

BRT = timezone(timedelta(hours=-3))
_loop: asyncio.AbstractEventLoop | None = None
_tasks: set = set()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Guarda o loop principal (chamado no lifespan) para gravar a partir de threads."""
    global _loop
    _loop = loop


async def _insert(row: dict) -> None:
    try:
        async with AsyncSessionLocal() as s:
            s.add(LlmUsage(**row))
            await s.commit()
    except Exception as e:
        logger.warn("USAGE", f"Falha ao gravar consumo de tokens: {e}")


def record(source: str, model: str, usage) -> None:
    """Registra o `usage` de uma resposta OpenAI (objeto ou None). Nunca levanta."""
    try:
        if usage is None:
            return
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or 0) or prompt + completion
        row = {"source": source, "model": model, "prompt_tokens": prompt,
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

    rows = list(daily.values())
    totals = {k: sum(r[k] for r in rows) for k in ("messages", "calls", "prompt", "completion", "total")}
    totals["avg_tokens_per_message"] = round(totals["total"] / totals["messages"]) if totals["messages"] else 0
    return {
        "days": days,
        "daily": rows,
        "by_model": sorted(by_model.values(), key=lambda r: -r["total"]),
        "by_source": sorted(by_source.values(), key=lambda r: -r["total"]),
        "totals": totals,
    }
