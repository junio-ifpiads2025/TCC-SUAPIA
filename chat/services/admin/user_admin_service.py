"""
Usuários do assistente no painel: busca, detalhe e uso do dia.

Fonte: `user_auth` (quem já fez login no SUAP). O painel identifica o usuário
pelo id interno da linha; o chat_id só aparece mascarado (LGPD). Abrir o
detalhe de um usuário é registrado na auditoria (acesso a dado pessoal).
"""

from sqlalchemy import or_, select

import config
from models.database import AccessLog, AsyncSessionLocal, UserAuth
from services.shared import acl_service, audit_service, session_service
from utils.security import mask_chat_id

SEARCH_LIMIT = 50
EVENTS_LIMIT = 20


def _to_dict(u: UserAuth) -> dict:
    return {"id": u.id, "chat_id": u.chat_id, "matricula": u.matricula,
            "terms_accepted_at": u.terms_accepted_at, "created_at": u.created_at}


def _public(u: dict) -> dict:
    """Linha para a tela: chat_id mascarado, situação de acesso e limite efetivo."""
    out = {k: v for k, v in u.items() if k != "chat_id"}
    out.update(masked=mask_chat_id(u["chat_id"]), status=acl_service.check(u["chat_id"]),
               daily_limit=acl_service.daily_limit(u["chat_id"]),
               own_limit=acl_service.user_limit(u["chat_id"]))
    return out


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

async def _db_search(q: str | None, limit: int) -> list[dict]:
    stmt = select(UserAuth).order_by(UserAuth.updated_at.desc()).limit(limit)
    if q:
        termo = f"%{q}%"
        stmt = stmt.where(or_(UserAuth.matricula.ilike(termo), UserAuth.chat_id.ilike(termo)))
    async with AsyncSessionLocal() as s:
        return [_to_dict(u) for u in (await s.execute(stmt)).scalars().all()]


async def _db_get(user_id: int) -> dict | None:
    async with AsyncSessionLocal() as s:
        u = await s.get(UserAuth, user_id)
        return _to_dict(u) if u else None


async def _db_events(chat_id: str, limit: int) -> list[dict]:
    stmt = (select(AccessLog).where(AccessLog.chat_id == chat_id)
            .order_by(AccessLog.created_at.desc(), AccessLog.id.desc()).limit(limit))
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(stmt)).scalars().all()
    return [{"event": r.event, "provider": r.provider, "detail": r.detail,
             "duration_ms": r.duration_ms, "created_at": r.created_at} for r in rows]


# ── API pública ──────────────────────────────────────────────────────────────

async def search(q: str = "") -> list[dict]:
    """Busca por matrícula ou chat_id (parcial); sem termo, os mais recentes."""
    return [_public(u) for u in await _db_search(q.strip() or None, SEARCH_LIMIT)]


async def get_chat_id(user_id: int) -> str | None:
    """chat_id real do usuário, para as ações do painel (nunca vai para a tela)."""
    u = await _db_get(user_id)
    return u["chat_id"] if u else None


async def detail(user_id: int) -> dict | None:
    """Dados do usuário, eventos recentes e uso de hoje. Auditado como leitura."""
    u = await _db_get(user_id)
    if u is None:
        return None
    chat_id = u["chat_id"]
    out = _public(u)
    out["events"] = await _db_events(chat_id, EVENTS_LIMIT)
    try:
        out["messages_today"] = await session_service.get_rate(chat_id)
        out["tokens_today"] = await session_service.get_tokens(chat_id)
    except Exception:  # Redis fora do ar não impede ver o resto
        out["messages_today"] = out["tokens_today"] = None
    out["token_budget"] = config.DAILY_TOKEN_BUDGET
    await audit_service.record("view", "user_data", user_id, None, None)
    return out
