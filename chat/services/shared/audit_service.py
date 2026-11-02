"""
Auditoria das alterações feitas pelos administradores (tabela `admin_audit`).

Cada mutação do painel (prompt, skill, guardrail, regra de acesso, configuração,
documento, administrador) chama `record()` com o estado antes e depois.
O autor vem do ContextVar `current_admin`, definido por `require_admin` no
início de cada requisição do painel: os serviços não precisam receber o admin.
Falha ao gravar só gera aviso no log; a alteração já aplicada não é desfeita.
"""

import json
from contextvars import ContextVar
from datetime import datetime, timedelta

from sqlalchemy import select, update

from models.database import AdminAudit, AsyncSessionLocal
from services.shared import logger

UNKNOWN_ADMIN = "desconhecido"

current_admin: ContextVar[str | None] = ContextVar("current_admin", default=None)


def _jsonable(data: dict | None) -> dict | None:
    """Datas e outros tipos viram texto para caber numa coluna JSON."""
    return None if data is None else json.loads(json.dumps(data, default=str))


def _to_dict(a: AdminAudit) -> dict:
    return {"id": a.id, "admin": a.admin, "action": a.action, "entity": a.entity,
            "entity_id": a.entity_id, "before": a.before, "after": a.after,
            "reverted_by": a.reverted_by, "created_at": a.created_at}


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

async def _db_insert(row: dict) -> None:
    async with AsyncSessionLocal() as s:
        s.add(AdminAudit(**row))
        await s.commit()


async def _db_list(admin, entity, date_from, date_to, limit, offset) -> list[dict]:
    stmt = select(AdminAudit)
    if admin:
        stmt = stmt.where(AdminAudit.admin == admin)
    if entity:
        stmt = stmt.where(AdminAudit.entity == entity)
    if date_from:
        stmt = stmt.where(AdminAudit.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AdminAudit.created_at < date_to + timedelta(days=1))
    stmt = stmt.order_by(AdminAudit.id.desc()).limit(limit).offset(offset)
    async with AsyncSessionLocal() as s:
        return [_to_dict(a) for a in (await s.execute(stmt)).scalars().all()]


async def _db_get(entry_id: int) -> dict | None:
    async with AsyncSessionLocal() as s:
        a = await s.get(AdminAudit, entry_id)
        return _to_dict(a) if a else None


async def _db_mark_reverted(entry_id: int, admin: str) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(update(AdminAudit).where(AdminAudit.id == entry_id).values(reverted_by=admin))
        await s.commit()


# ── API pública ──────────────────────────────────────────────────────────────

async def record(action: str, entity: str, entity_id, before: dict | None, after: dict | None) -> None:
    """Grava uma alteração. Nunca levanta exceção."""
    row = {"admin": current_admin.get() or UNKNOWN_ADMIN, "action": action, "entity": entity,
           "entity_id": None if entity_id is None else str(entity_id),
           "before": _jsonable(before), "after": _jsonable(after)}
    try:
        await _db_insert(row)
    except Exception as e:
        logger.warn("AUDIT", f"Falha ao gravar auditoria ({entity}/{action}): {e}")


async def list_entries(admin: str | None = None, entity: str | None = None,
                       date_from: datetime | None = None, date_to: datetime | None = None,
                       limit: int = 50, offset: int = 0) -> list[dict]:
    return await _db_list(admin, entity, date_from, date_to, limit, offset)


async def get_entry(entry_id: int) -> dict | None:
    return await _db_get(entry_id)


async def mark_reverted(entry_id: int, admin: str) -> None:
    await _db_mark_reverted(entry_id, admin)


def changes(entry: dict) -> list[dict]:
    """Campos que mudaram entre before e after: [{field, before, after}]."""
    before, after = entry.get("before") or {}, entry.get("after") or {}
    return [{"field": k, "before": before.get(k), "after": after.get(k)}
            for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
