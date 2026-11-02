"""
Métricas de qualidade e operação para o resumo do painel (/admin).

Junta, por dia e no período escolhido:
- latência p50/p95 das respostas (`access_log.duration_ms`, evento `answered`);
- taxa de erro (`failed` / (`answered` + `failed`));
- bloqueios de guardrail (eventos `guardrail_input` e `guardrail_output`);
- usuários ativos (chat_ids distintos atendidos);
- satisfação (👍 / (👍 + 👎)) e taxa de "sem resposta" (`qa_case`);
- tokens e custo estimado por modelo (reaproveita `usage_service.report`).
LGPD: só agrega contagens; nenhum conteúdo ou identificador sai daqui.
"""

from datetime import timedelta

from sqlalchemy import func, select

from models.database import AccessLog, AsyncSessionLocal, QaCase
from services.shared import usage_service

EVENTS = ("answered", "failed", "guardrail_input", "guardrail_output")
QA_KINDS = ("up", "down", "no_answer")


def _day(col):
    return func.date(func.timezone("America/Fortaleza", col))


# ── Acesso ao banco (isolado para facilitar testes) ──────────────────────────

async def _db_latency(since) -> list[tuple]:
    """(dia, p50, p95) das respostas com duração registrada."""
    day = _day(AccessLog.created_at)
    stmt = (select(day,
                   func.percentile_cont(0.5).within_group(AccessLog.duration_ms),
                   func.percentile_cont(0.95).within_group(AccessLog.duration_ms))
            .where(AccessLog.event == "answered", AccessLog.duration_ms.is_not(None),
                   AccessLog.created_at >= since)
            .group_by(day))
    async with AsyncSessionLocal() as s:
        return [tuple(r) for r in (await s.execute(stmt)).all()]


async def _db_events(since) -> list[tuple]:
    """(dia, evento, quantidade) dos eventos de EVENTS."""
    day = _day(AccessLog.created_at)
    stmt = (select(day, AccessLog.event, func.count())
            .where(AccessLog.event.in_(EVENTS), AccessLog.created_at >= since)
            .group_by(day, AccessLog.event))
    async with AsyncSessionLocal() as s:
        return [tuple(r) for r in (await s.execute(stmt)).all()]


async def _db_active_users(since) -> int:
    stmt = (select(func.count(func.distinct(AccessLog.chat_id)))
            .where(AccessLog.event == "answered", AccessLog.created_at >= since))
    async with AsyncSessionLocal() as s:
        return int((await s.execute(stmt)).scalar_one() or 0)


async def _db_qa(since) -> list[tuple]:
    """(dia, kind, quantidade) dos casos de qualidade."""
    day = _day(QaCase.created_at)
    stmt = (select(day, QaCase.kind, func.count())
            .where(QaCase.created_at >= since)
            .group_by(day, QaCase.kind))
    async with AsyncSessionLocal() as s:
        return [tuple(r) for r in (await s.execute(stmt)).all()]


# ── API pública ──────────────────────────────────────────────────────────────

def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


async def report(days: int = 7) -> dict:
    """
    Métricas dos últimos `days` dias. `daily` tem uma linha por dia (sem buracos)
    com p50, p95, answered, failed, error_rate, guardrail, up, down, no_answer,
    tokens e users; `totals` traz os agregados do período e o custo estimado.
    """
    usage = await usage_service.report(days)
    days = usage["days"]
    since = usage_service.period_start(days)
    latency = {d: (p50, p95) for d, p50, p95 in await _db_latency(since)}
    events = await _db_events(since)
    qa = await _db_qa(since)
    active_users = await _db_active_users(since)

    first = since.date()
    daily = {}
    for i in range(days):
        d = first + timedelta(days=i)
        p50, p95 = latency.get(d, (None, None))
        u = usage["daily"][i]
        daily[d] = {"date": d.isoformat(),
                    "p50": None if p50 is None else int(p50),
                    "p95": None if p95 is None else int(p95),
                    "answered": 0, "failed": 0, "guardrail": 0,
                    "up": 0, "down": 0, "no_answer": 0,
                    "tokens": u["total"], "users": u["users"]}
    for d, event, n in events:
        if d not in daily:
            continue
        key = "guardrail" if event.startswith("guardrail") else event
        daily[d][key] += int(n)
    for d, kind, n in qa:
        if d in daily and kind in QA_KINDS:
            daily[d][kind] += int(n)
    for r in daily.values():
        r["error_rate"] = _ratio(r["failed"], r["answered"] + r["failed"])

    rows = list(daily.values())
    totals = {k: sum(r[k] for r in rows) for k in ("answered", "failed", "guardrail", "up", "down", "no_answer")}
    totals.update(
        error_rate=_ratio(totals["failed"], totals["answered"] + totals["failed"]),
        satisfaction=_ratio(totals["up"], totals["up"] + totals["down"]),
        no_answer_rate=_ratio(totals["no_answer"], totals["answered"]),
        active_users=active_users,
        tokens=usage["totals"]["total"],
        cost=usage["totals"]["cost"],
    )
    p95s = [r["p95"] for r in rows if r["p95"] is not None]
    totals["p95_max"] = max(p95s) if p95s else None
    return {"days": days, "daily": rows, "by_model": usage["by_model"], "totals": totals}
