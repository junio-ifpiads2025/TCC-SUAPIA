"""
Exclusão dos dados de um titular (LGPD, art. 18, VI) a pedido feito ao administrador.

`erase(chat_id)` remove tudo que identifica o usuário:
- Postgres: `user_auth`, `access_log`, `access_rule` (inclui bloqueio e limite
  próprio) e `qa_case`; em `llm_usage` o chat_id vira NULL (os totais de tokens
  ficam, já anônimos).
- Redis: token SUAP, perfil, histórico, pendência de feedback, contadores do
  dia (mensagens e tokens) e links de login ainda válidos.
- Fila: itens do usuário em pending/processing/failed/done.
A ação é auditada sem o chat_id (só o id interno e as contagens).
"""

from sqlalchemy import delete, update

from models.database import AccessLog, AccessRule, AsyncSessionLocal, LlmUsage, QaCase, UserAuth
from services.chat import feedback_service, queue_service
from services.shared import acl_service, audit_service, logger, session_service

_GLOB_SPECIAL = "\\*?[]"


def _glob_escape(value: str) -> str:
    return "".join("\\" + c if c in _GLOB_SPECIAL else c for c in value)


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

async def _db_erase(chat_id: str) -> dict:
    """Apaga/anonimiza numa transação. Retorna quantas linhas por tabela."""
    counts = {}
    async with AsyncSessionLocal() as s:
        for name, model in (("user_auth", UserAuth), ("access_log", AccessLog),
                            ("access_rule", AccessRule), ("qa_case", QaCase)):
            res = await s.execute(delete(model).where(model.chat_id == chat_id))
            counts[name] = res.rowcount or 0
        res = await s.execute(update(LlmUsage).where(LlmUsage.chat_id == chat_id).values(chat_id=None))
        counts["llm_usage_anonimizados"] = res.rowcount or 0
        await s.commit()
    return counts


async def _redis_erase(chat_id: str) -> int:
    """Chaves por dia (rate/tokens) e links de login que apontam para o chat_id."""
    r = session_service.get_redis()
    esc = _glob_escape(chat_id)
    keys = []
    for pattern in (f"suap:rate:{esc}:*", f"suap:tokens:{esc}:*"):
        keys += [k async for k in r.scan_iter(match=pattern)]
    async for k in r.scan_iter(match="suap:onboarding:*"):
        if await r.get(k) == chat_id:
            keys.append(k)
    if keys:
        await r.delete(*keys)
    return len(keys)


# ── API pública ──────────────────────────────────────────────────────────────

async def erase(chat_id: str, user_id: int | None = None) -> dict:
    """
    Apaga os dados do titular em Redis, fila e Postgres. Retorna as contagens.
    Redis vem primeiro: se estiver fora do ar, a exclusão falha antes de tocar o
    banco e pode ser repetida inteira.
    """
    chat_id = (chat_id or "").strip()
    if not chat_id:
        raise ValueError("chat_id vazio")
    fila = await queue_service.remove_user_items(chat_id)
    redis = await _redis_erase(chat_id)
    await feedback_service.clear(chat_id)
    await acl_service.clear_user_session(chat_id)  # token, perfil e histórico
    counts = await _db_erase(chat_id)
    counts.update(redis=redis, fila=fila)
    await acl_service.load()  # bloqueio/limite apagados saem do cache
    await audit_service.record("erase", "user_data", user_id, counts, None)
    logger.info("LGPD", f"Dados de um titular apagados: {counts}")
    return counts
