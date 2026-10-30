"""
System prompt editável do SUAP-IA.

O prompt ativo vive no Postgres (`prompt_version`) e é espelhado em memória:
carregado na subida (`startup`) e atualizado em `save`/`activate`. O caminho
quente (`get_system_prompt`) é síncrono e sem I/O. Única fonte é o banco: sem
versão, devolve o `default` do chamador. Regras guardrail `instruct` são anexadas ao final.
"""

from sqlalchemy import select, update

from config import AGENT_NAME
from models.database import AsyncSessionLocal, PromptVersion
from services import guardrail_service, logger

MAX_PROMPT_LEN = 20000


class PromptError(ValueError):
    """Conteúdo inválido (vazio ou grande demais)."""


class PromptNotFound(LookupError):
    """Versão inexistente."""


# Cache do prompt ativo: {"id","content","created_at","author"} ou None
_active: dict | None = None


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

def _to_dict(v: PromptVersion) -> dict:
    return {"id": v.id, "content": v.content, "active": v.active,
            "author": v.author, "created_at": v.created_at}


async def _db_active() -> dict | None:
    async with AsyncSessionLocal() as s:
        v = (await s.execute(
            select(PromptVersion).where(PromptVersion.active.is_(True))
            .order_by(PromptVersion.id.desc()).limit(1))).scalar_one_or_none()
        return _to_dict(v) if v else None


async def _db_insert_active(content: str, author: str | None) -> dict:
    async with AsyncSessionLocal() as s:
        await s.execute(update(PromptVersion).values(active=False))
        v = PromptVersion(content=content, author=author, active=True)
        s.add(v)
        await s.commit()
        await s.refresh(v)
        return _to_dict(v)


async def _db_activate(version_id: int) -> dict:
    async with AsyncSessionLocal() as s:
        v = await s.get(PromptVersion, version_id)
        if v is None:
            raise PromptNotFound(version_id)
        await s.execute(update(PromptVersion).values(active=False))
        v.active = True
        await s.commit()
        await s.refresh(v)
        return _to_dict(v)


async def _db_list() -> list[dict]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(PromptVersion).order_by(PromptVersion.id.desc()))).scalars().all()
        return [_to_dict(v) for v in rows]


# ── API pública ──────────────────────────────────────────────────────────────

async def load() -> None:
    """Carrega o prompt ativo do banco."""
    global _active
    _active = await _db_active()


async def startup() -> None:
    """Carrega prompt e guardrails; chamar no lifespan do app."""
    await load()
    await guardrail_service.startup()


def get_system_prompt(default: str = "") -> str:
    """Prompt ativo + bloco de regras de comportamento. Síncrono, sem I/O."""
    base = _active["content"] if _active else default
    base = base.replace("{AGENT_NAME}", AGENT_NAME).strip()
    block = guardrail_service.instruction_block()
    return f"{base}\n\n{block}".strip() if block else base


def active_content() -> str:
    """Texto editável do prompt ativo (sem o bloco de guardrails e sem substituições)."""
    return _active["content"] if _active else ""


def active_info() -> dict | None:
    if _active is None:
        return None
    return {"id": _active["id"], "created_at": _active["created_at"], "author": _active["author"]}


async def save(content: str, author: str | None = None) -> dict:
    """Cria uma nova versão já ativa. Devolve a versão (dict com 'id')."""
    global _active
    content = (content or "").strip()
    if not content:
        raise PromptError("O prompt não pode ficar vazio.")
    if len(content) > MAX_PROMPT_LEN:
        raise PromptError(f"Prompt longo demais (máx. {MAX_PROMPT_LEN} caracteres).")
    _active = await _db_insert_active(content, author)
    return _active


async def activate(version_id: int) -> dict:
    """Restaura uma versão antiga, tornando-a a ativa."""
    global _active
    _active = await _db_activate(version_id)
    return _active


async def list_versions() -> list[dict]:
    return await _db_list()
