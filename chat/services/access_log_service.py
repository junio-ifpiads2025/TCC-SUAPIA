"""
Log de acesso (tabela `access_log`).

- `log_event` é fire-and-forget (asyncio.create_task) e nunca levanta exceção.
- LGPD: o texto da mensagem nunca é gravado por padrão. `detail` só é mantido
  quando tem formato `chave=valor` (tamanho/hash/motivo curto); texto livre é
  trocado por `len=N sha=...`, a menos que ACCESS_LOG_STORE_CONTENT=true.
"""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select

import config
from models.database import AccessLog, AsyncSessionLocal, UserAuth
from services import logger, session_service

_SAFE_DETAIL = re.compile(r"^[a-z_]+=[\w.\-:@]{0,64}( [a-z_]+=[\w.\-:@]{0,64})*$")
_tasks: set = set()


def describe_content(text: str) -> str:
    """Resumo seguro de um texto: tamanho + hash curto (sem o conteúdo)."""
    digest = hashlib.sha256((text or "").encode()).hexdigest()[:12]
    return f"len={len(text or '')} sha={digest}"


def _sanitize(detail: str | None) -> str | None:
    if detail is None:
        return None
    if config.ACCESS_LOG_STORE_CONTENT:
        return detail[:2000]
    if _SAFE_DETAIL.match(detail):
        return detail
    return describe_content(detail)


# ── Acesso ao banco (isolado para facilitar testes) ──────────────────────────

async def _db_insert(row: dict) -> None:
    async with AsyncSessionLocal() as s:
        s.add(AccessLog(**row))
        await s.commit()


def _filters(stmt, chat_id, event, date_from, date_to):
    if chat_id:
        termo = f"%{chat_id.strip()}%"
        stmt = stmt.where(or_(AccessLog.chat_id.ilike(termo), UserAuth.matricula.ilike(termo)))
    if event:
        stmt = stmt.where(AccessLog.event == event)
    if date_from:
        stmt = stmt.where(AccessLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AccessLog.created_at < date_to + timedelta(days=1))
    return stmt


async def _db_query(chat_id, event, date_from, date_to, limit, offset) -> list[dict]:
    stmt = select(AccessLog, UserAuth.matricula).outerjoin(UserAuth, UserAuth.chat_id == AccessLog.chat_id)
    stmt = _filters(stmt, chat_id, event, date_from, date_to)
    stmt = stmt.order_by(AccessLog.created_at.desc(), AccessLog.id.desc()).limit(limit).offset(offset)
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(stmt)).all()
    return [
        {"id": r.id, "chat_id": r.chat_id, "provider": r.provider, "event": r.event,
         "detail": r.detail, "duration_ms": r.duration_ms, "created_at": r.created_at,
         "matricula": matricula}
        for r, matricula in rows
    ]


async def _nomes(chat_ids: set[str]) -> dict[str, str]:
    """Nome/curso vêm do perfil no Redis (só existe com sessão ativa); falha vira vazio."""
    out = {}
    for cid in chat_ids:
        try:
            perfil = await session_service.get_profile(cid)
        except Exception:
            perfil = None
        if perfil:
            out[cid] = perfil.get("nome") or ""
    return out


async def _db_count_since(event: str, since: datetime) -> int:
    stmt = select(func.count()).select_from(AccessLog).where(
        AccessLog.event == event, AccessLog.created_at >= since)
    async with AsyncSessionLocal() as s:
        return (await s.execute(stmt)).scalar_one()


async def _db_purge(before: datetime) -> int:
    async with AsyncSessionLocal() as s:
        res = await s.execute(delete(AccessLog).where(AccessLog.created_at < before))
        await s.commit()
        return res.rowcount or 0


# ── API pública ──────────────────────────────────────────────────────────────

async def _write(row: dict) -> None:
    try:
        await _db_insert(row)
    except Exception as e:
        logger.warn("ACCESS_LOG", f"Falha ao gravar log: {e}")


def log_event(chat_id: str, event: str, provider: str | None = None,
              detail: str | None = None, duration_ms: int | None = None) -> None:
    """Fire-and-forget (agenda task asyncio); nunca levanta exceção."""
    try:
        row = {"chat_id": chat_id, "event": event, "provider": provider,
               "detail": _sanitize(detail), "duration_ms": duration_ms}
        task = asyncio.get_running_loop().create_task(_write(row))
        _tasks.add(task)  # mantém referência até terminar
        task.add_done_callback(_tasks.discard)
    except Exception:
        pass  # sem event loop ou qualquer outro erro: log nunca derruba o fluxo


def log_admin(admin: str, action: str, detail: str | None = None) -> None:
    """Registra ação do painel: chat_id=`admin:<usuário>`, event=`admin_<action>`."""
    log_event(f"admin:{admin}", f"admin_{action}", provider="admin", detail=detail)


def _today_start() -> datetime:
    brt = timezone(timedelta(hours=-3))
    return datetime.now(brt).replace(hour=0, minute=0, second=0, microsecond=0)


async def count_today(event: str) -> int:
    try:
        return await _db_count_since(event, _today_start())
    except Exception as e:
        logger.warn("ACCESS_LOG", f"Falha ao contar eventos: {e}")
        return 0


async def list_logs(chat_id: str | None = None, event: str | None = None,
                    date_from: datetime | None = None, date_to: datetime | None = None,
                    limit: int = 100, offset: int = 0) -> list[dict]:
    rows = await _db_query(chat_id, event, date_from, date_to, limit, offset)
    nomes = await _nomes({r["chat_id"] for r in rows})
    for r in rows:
        r["nome"] = nomes.get(r["chat_id"])
    return rows


async def purge() -> int:
    """Remove logs mais antigos que ACCESS_LOG_RETENTION_DAYS. Retorna quantos."""
    before = datetime.now(timezone.utc) - timedelta(days=config.ACCESS_LOG_RETENTION_DAYS)
    n = await _db_purge(before)
    if n:
        logger.info("ACCESS_LOG", f"Purga: {n} registro(s) removidos")
    return n


async def retention_loop(interval_seconds: int = 86400) -> None:
    """Task de fundo (lifespan): purga diária. Erros não encerram o loop."""
    while True:
        try:
            await purge()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warn("ACCESS_LOG", f"Falha na purga: {e}")
        await asyncio.sleep(interval_seconds)
