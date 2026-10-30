"""
Skills do agente, editáveis no painel e guardadas no Postgres (`skill`).

Cada skill tem slug único (validado por regex), nome, descrição
e corpo em markdown.
"""

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.database import AsyncSessionLocal, Skill

_SLUG = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_BODY_LEN = 20000

# Cache em memória (slug → skill) lido pelo agente sem I/O; recarregado a cada escrita.
_cache: dict[str, dict] = {}


class SkillError(ValueError):
    """Dados inválidos."""


class SkillNotFound(LookupError):
    """Skill inexistente."""


def _to_dict(s: Skill) -> dict:
    return {"slug": s.slug, "name": s.name, "description": s.description or "",
            "body": s.body, "updated_at": s.updated_at}


def _clean(data: dict) -> dict:
    name = (data.get("name") or "").strip()
    body = (data.get("body") or "").strip()
    if not name or len(name) > 100:
        raise SkillError("Nome obrigatório (máx. 100 caracteres).")
    if not body:
        raise SkillError("O corpo da skill não pode ficar vazio.")
    if len(body) > MAX_BODY_LEN:
        raise SkillError(f"Corpo longo demais (máx. {MAX_BODY_LEN} caracteres).")
    return {"name": name, "body": body,
            "description": (data.get("description") or "").strip()}


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

async def _db_list() -> list[dict]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Skill).order_by(Skill.name))).scalars().all()
        return [_to_dict(r) for r in rows]


async def _db_get(slug: str) -> dict | None:
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        return _to_dict(row) if row else None


async def _db_insert(slug: str, values: dict) -> dict:
    async with AsyncSessionLocal() as s:
        row = Skill(slug=slug, **values)
        s.add(row)
        try:
            await s.commit()
        except IntegrityError:
            raise SkillError("Já existe uma skill com esse slug.")
        await s.refresh(row)
        return _to_dict(row)


async def _db_update(slug: str, values: dict) -> dict:
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        if row is None:
            raise SkillNotFound(slug)
        for k, v in values.items():
            setattr(row, k, v)
        await s.commit()
        await s.refresh(row)
        return _to_dict(row)


async def _db_delete(slug: str) -> None:
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        if row is None:
            raise SkillNotFound(slug)
        await s.delete(row)
        await s.commit()


# ── API pública ──────────────────────────────────────────────────────────────

async def startup() -> None:
    """Carrega as skills no cache; chamar no lifespan do app."""
    await _reload()


async def _reload() -> None:
    global _cache
    _cache = {s["slug"]: s for s in await _db_list()}


def catalog() -> list[dict]:
    """Skills disponíveis para o agente: [{slug, name, description}]. Síncrono, sem I/O."""
    return [{"slug": s["slug"], "name": s["name"], "description": s["description"]}
            for s in sorted(_cache.values(), key=lambda s: s["name"])]


def get_body(slug: str) -> str | None:
    """Instruções (markdown) de uma skill do cache; None se não existir."""
    s = _cache.get(slug)
    return s["body"] if s else None


async def list_skills() -> list[dict]:
    return await _db_list()


async def get_skill(slug: str) -> dict | None:
    """Detalhe de uma skill; slug inválido ou inexistente devolve None."""
    if not _SLUG.match(slug or ""):
        return None
    return await _db_get(slug)


async def create_skill(slug: str, data: dict) -> dict:
    slug = (slug or "").strip()
    if not _SLUG.match(slug):
        raise SkillError("Slug inválido (letras, números, '-' e '_', máx. 80).")
    row = await _db_insert(slug, _clean(data))
    await _reload()
    return row


async def update_skill(slug: str, data: dict) -> dict:
    row = await _db_update(slug, _clean(data))
    await _reload()
    return row


async def delete_skill(slug: str) -> None:
    await _db_delete(slug)
    await _reload()
