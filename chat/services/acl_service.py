"""
Controle de acesso (allowlist/blocklist) com cache em memória.

As regras ficam na tabela `access_rule` (Postgres) e são espelhadas em dois sets
carregados na subida. `check()` é síncrono e sem I/O: o webhook nunca consulta
o banco. Um único processo escreve (as rotas admin), então o cache é mantido
direto na escrita. Regra: block sempre vence; com RESPONDER_QUALQUER_NUMERO=false
só allow passa; com true só block barra.
"""

from sqlalchemy import delete, func, select

import config
from models.database import AccessRule, AsyncSessionLocal
from services import logger

KINDS = ("allow", "block")

_allow: set[str] = set()
_block: set[str] = set()


# ── Acesso ao banco (isolado para facilitar testes) ──────────────────────────

async def _db_all() -> list[tuple[str, str]]:
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(AccessRule.chat_id, AccessRule.kind))
        return [(r[0], r[1]) for r in rows]


async def _db_upsert(chat_id: str, kind: str, reason: str | None, created_by: str | None) -> None:
    async with AsyncSessionLocal() as s:
        rule = (await s.execute(select(AccessRule).where(AccessRule.chat_id == chat_id))).scalar_one_or_none()
        if rule:
            rule.kind, rule.reason = kind, reason
            if created_by:
                rule.created_by = created_by
        else:
            s.add(AccessRule(chat_id=chat_id, kind=kind, reason=reason, created_by=created_by))
        await s.commit()


async def _db_delete(chat_id: str) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(AccessRule).where(AccessRule.chat_id == chat_id))
        await s.commit()


async def _db_list(kind: str | None, q: str | None) -> list[dict]:
    stmt = select(AccessRule).order_by(AccessRule.created_at.desc())
    if kind in KINDS:
        stmt = stmt.where(AccessRule.kind == kind)
    if q:
        stmt = stmt.where(AccessRule.chat_id.ilike(f"%{q.strip()}%"))
    async with AsyncSessionLocal() as s:
        rules = (await s.execute(stmt)).scalars().all()
    return [
        {"chat_id": r.chat_id, "kind": r.kind, "reason": r.reason,
         "created_by": r.created_by, "created_at": r.created_at}
        for r in rules
    ]


# ── Cache ────────────────────────────────────────────────────────────────────

def _apply(chat_id: str, kind: str | None) -> None:
    """Atualiza os sets: kind=None remove a regra."""
    _allow.discard(chat_id)
    _block.discard(chat_id)
    if kind == "allow":
        _allow.add(chat_id)
    elif kind == "block":
        _block.add(chat_id)


async def load() -> None:
    """Carrega as regras do Postgres (única fonte; nada vem do env)."""
    rows = await _db_all()
    _allow.clear()
    _block.clear()
    for chat_id, kind in rows:
        _apply(chat_id, kind)
    logger.info("ACL", f"Regras carregadas: allow={len(_allow)} block={len(_block)}")


async def startup() -> None:
    """Ponto de entrada para o lifespan."""
    await load()


def check(chat_id: str) -> str:
    """'ok' | 'blocked' | 'denied'. Síncrono, só lê o cache."""
    if chat_id in _block:
        return "blocked"
    if config.RESPONDER_QUALQUER_NUMERO or chat_id in _allow:
        return "ok"
    return "denied"


def counts() -> dict:
    return {"allow": len(_allow), "block": len(_block)}


# ── Escrita (admin) ──────────────────────────────────────────────────────────

async def list_rules(kind: str | None = None, q: str | None = None) -> list[dict]:
    return await _db_list(kind, q)


async def add_rule(chat_id: str, kind: str, reason: str | None = None,
                   created_by: str | None = None, clear_session: bool = False) -> None:
    """Upsert da regra (mudar o kind atualiza). Atualiza o cache na hora."""
    chat_id = (chat_id or "").strip()
    if not chat_id:
        raise ValueError("chat_id vazio")
    if kind not in KINDS:
        raise ValueError(f"kind inválido: {kind}")
    await _db_upsert(chat_id, kind, (reason or "").strip() or None, created_by)
    _apply(chat_id, kind)
    if kind == "block" and clear_session:
        await clear_user_session(chat_id)


async def remove_rule(chat_id: str) -> None:
    await _db_delete(chat_id)
    _apply(chat_id, None)


async def clear_user_session(chat_id: str) -> None:
    """Apaga token SUAP, perfil e histórico (suap:token/profile/thread:*) do chat."""
    from services import session_service, thread_service
    try:
        await session_service.delete_token(chat_id)
        await session_service.delete_profile(chat_id)
        await thread_service.clear_thread(chat_id)
    except Exception as e:  # Redis fora do ar não deve impedir o bloqueio
        logger.warn("ACL", f"Falha ao limpar sessão de {chat_id}: {e}")
