"""
Controle de acesso (allowlist/blocklist) com cache em memória.

As regras ficam na tabela `access_rule` (Postgres) e são espelhadas em dois sets
carregados na subida. `check()` é síncrono e sem I/O: o webhook nunca consulta
o banco. Um único processo escreve (as rotas admin), então o cache é mantido
direto na escrita. Regra: block sempre vence; com "responder qualquer número"
desligado só allow passa; ligado só block barra. O valor vem do painel (tabela
`app_setting`); sem registro, vale RESPONDER_QUALQUER_NUMERO do env.

Também guarda o limite diário de mensagens (RN06): padrão global em
`app_setting` (`max_daily_messages`, sem registro vale MAX_DAILY_MESSAGES) e
override por usuário em `access_rule.daily_limit`. Um usuário sem regra de
acesso que recebe limite próprio ganha uma linha `kind='limit'`, que não afeta
allow/block.
"""

from sqlalchemy import delete, func, select

import config
from models.database import AccessRule, AppSetting, AsyncSessionLocal
from services.shared import audit_service, logger

KINDS = ("allow", "block")
LIMIT_KIND = "limit"  # linha só com limite próprio, sem allow/block
MAX_LIMIT = 10000

_allow: set[str] = set()
_block: set[str] = set()
_limits: dict[str, int] = {}
_open_mode: bool | None = None  # None = usa o default do env
_default_limit: int | None = None  # None = usa MAX_DAILY_MESSAGES do env

OPEN_KEY = "responder_qualquer_numero"
DAILY_LIMIT_KEY = "max_daily_messages"


# ── Acesso ao banco (isolado para facilitar testes) ──────────────────────────

async def _db_all() -> list[tuple[str, str]]:
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(AccessRule.chat_id, AccessRule.kind))
        return [(r[0], r[1]) for r in rows]


async def _db_get_open() -> bool | None:
    async with AsyncSessionLocal() as s:
        row = await s.get(AppSetting, OPEN_KEY)
    return None if row is None else row.value == "true"


async def _db_set_open(enabled: bool) -> None:
    async with AsyncSessionLocal() as s:
        await s.merge(AppSetting(key=OPEN_KEY, value="true" if enabled else "false"))
        await s.commit()


async def _db_get_setting(key: str) -> str | None:
    async with AsyncSessionLocal() as s:
        row = await s.get(AppSetting, key)
    return None if row is None else row.value


async def _db_set_setting(key: str, value: str | None) -> None:
    """Grava a configuração; None remove (volta ao padrão do env)."""
    async with AsyncSessionLocal() as s:
        if value is None:
            await s.execute(delete(AppSetting).where(AppSetting.key == key))
        else:
            await s.merge(AppSetting(key=key, value=value))
        await s.commit()


async def _db_limits() -> dict[str, int]:
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(AccessRule.chat_id, AccessRule.daily_limit)
                               .where(AccessRule.daily_limit.is_not(None)))
        return {r[0]: r[1] for r in rows}


async def _db_set_limit(chat_id: str, limit: int | None, created_by: str | None) -> None:
    """Grava o limite próprio; cria linha `limit` se não houver regra; apaga a linha `limit` sem limite."""
    async with AsyncSessionLocal() as s:
        rule = (await s.execute(select(AccessRule).where(AccessRule.chat_id == chat_id))).scalar_one_or_none()
        if rule is None:
            if limit is not None:
                s.add(AccessRule(chat_id=chat_id, kind=LIMIT_KIND, daily_limit=limit, created_by=created_by))
        elif limit is None and rule.kind == LIMIT_KIND:
            await s.delete(rule)
        else:
            rule.daily_limit = limit
        await s.commit()


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


async def _db_get(chat_id: str) -> dict | None:
    async with AsyncSessionLocal() as s:
        r = (await s.execute(select(AccessRule).where(AccessRule.chat_id == chat_id))).scalar_one_or_none()
    return None if r is None else {"chat_id": r.chat_id, "kind": r.kind, "reason": r.reason,
                                   "daily_limit": r.daily_limit}


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
         "daily_limit": r.daily_limit, "created_by": r.created_by, "created_at": r.created_at}
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
    global _open_mode, _default_limit
    rows = await _db_all()
    _open_mode = await _db_get_open()
    raw = await _db_get_setting(DAILY_LIMIT_KEY)
    _default_limit = int(raw) if raw else None
    _allow.clear()
    _block.clear()
    for chat_id, kind in rows:
        _apply(chat_id, kind)
    _limits.clear()
    _limits.update(await _db_limits())
    logger.info("ACL", f"Regras carregadas: allow={len(_allow)} block={len(_block)}")


async def startup() -> None:
    """Ponto de entrada para o lifespan."""
    await load()


def check(chat_id: str) -> str:
    """'ok' | 'blocked' | 'denied'. Síncrono, só lê o cache."""
    if chat_id in _block:
        return "blocked"
    if is_open() or chat_id in _allow:
        return "ok"
    return "denied"


def is_open() -> bool:
    """True se qualquer número (exceto bloqueados) pode conversar."""
    return config.RESPONDER_QUALQUER_NUMERO if _open_mode is None else _open_mode


def default_limit() -> int:
    """Limite diário global de mensagens (painel ou, sem registro, o do env)."""
    return config.MAX_DAILY_MESSAGES if _default_limit is None else _default_limit


def user_limit(chat_id: str) -> int | None:
    """Limite próprio do usuário, ou None se segue o padrão."""
    return _limits.get(chat_id)


def daily_limit(chat_id: str) -> int:
    """Limite efetivo do usuário hoje. Síncrono, só lê o cache."""
    return _limits.get(chat_id, default_limit())


def counts() -> dict:
    return {"allow": len(_allow), "block": len(_block)}


# ── Escrita (admin) ──────────────────────────────────────────────────────────

def _rule_snapshot(rule: dict | None) -> dict | None:
    """Regra allow/block para a auditoria (o limite tem auditoria própria)."""
    if rule is None or rule["kind"] not in KINDS:
        return None
    return {"chat_id": rule["chat_id"], "kind": rule["kind"], "reason": rule["reason"]}

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
    reason = (reason or "").strip() or None
    before = await _db_get(chat_id)
    await _db_upsert(chat_id, kind, reason, created_by)
    _apply(chat_id, kind)
    await audit_service.record("upsert", "access_rule", chat_id, _rule_snapshot(before),
                               {"chat_id": chat_id, "kind": kind, "reason": reason})
    if kind == "block" and clear_session:
        await clear_user_session(chat_id)


async def set_open(enabled: bool) -> None:
    """Liga/desliga 'responder qualquer número'. Persiste e atualiza o cache na hora."""
    global _open_mode
    before = is_open()
    await _db_set_open(enabled)
    _open_mode = enabled
    await audit_service.record("update", "setting", OPEN_KEY, {"value": before}, {"value": enabled})


def _parse_limit(value) -> int | None:
    """'' / None = sem limite próprio; senão inteiro entre 0 e MAX_LIMIT."""
    if value is None or str(value).strip() == "":
        return None
    try:
        n = int(str(value).strip())
    except ValueError as e:
        raise ValueError("O limite deve ser um número inteiro.") from e
    if not 0 <= n <= MAX_LIMIT:
        raise ValueError(f"O limite deve ficar entre 0 e {MAX_LIMIT}.")
    return n


async def set_default_limit(value) -> None:
    """Limite diário global. Vazio volta ao MAX_DAILY_MESSAGES do env. Auditado."""
    global _default_limit
    limit = _parse_limit(value)
    before = _default_limit
    await _db_set_setting(DAILY_LIMIT_KEY, None if limit is None else str(limit))
    _default_limit = limit
    await audit_service.record("update", "setting", DAILY_LIMIT_KEY, {"value": before}, {"value": limit})


async def set_user_limit(chat_id: str, value, created_by: str | None = None) -> None:
    """Limite próprio de um usuário. Vazio remove o override. Auditado."""
    chat_id = (chat_id or "").strip()
    if not chat_id:
        raise ValueError("chat_id vazio")
    limit = _parse_limit(value)
    before = _limits.get(chat_id)
    await _db_set_limit(chat_id, limit, created_by)
    if limit is None:
        _limits.pop(chat_id, None)
    else:
        _limits[chat_id] = limit
    await audit_service.record("update", "daily_limit", chat_id,
                               {"daily_limit": before}, {"daily_limit": limit})


async def remove_rule(chat_id: str) -> None:
    """Remove allow/block. Se o usuário tem limite próprio, a linha vira `limit` e o mantém."""
    chat_id = (chat_id or "").strip()
    before = await _db_get(chat_id)
    if before and before.get("daily_limit") is not None:
        await _db_upsert(chat_id, LIMIT_KIND, None, None)
    else:
        await _db_delete(chat_id)
    _apply(chat_id, None)
    if before and before["kind"] in KINDS:
        await audit_service.record("delete", "access_rule", chat_id, _rule_snapshot(before), None)


async def clear_user_session(chat_id: str) -> None:
    """Apaga token SUAP, perfil e histórico (suap:token/profile/thread:*) do chat."""
    from services.shared import session_service
    from services.chat import thread_service
    try:
        await session_service.delete_token(chat_id)
        await session_service.delete_profile(chat_id)
        await thread_service.clear_thread(chat_id)
    except Exception as e:  # Redis fora do ar não deve impedir o bloqueio
        logger.warn("ACL", f"Falha ao limpar sessão de {chat_id}: {e}")
