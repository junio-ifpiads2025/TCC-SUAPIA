"""Administradores do painel por matrícula SUAP (tabela `admin_user`)."""

import re

from sqlalchemy import delete, select

from models.database import AdminUser, AsyncSessionLocal

_MATRICULA = re.compile(r"^[0-9A-Za-z.\-]{3,30}$")


def normalize(matricula: str) -> str:
    matricula = (matricula or "").strip()
    if not _MATRICULA.match(matricula):
        raise ValueError("Matrícula inválida (use apenas letras, números, '.' ou '-').")
    return matricula


async def is_admin(matricula: str) -> bool:
    async with AsyncSessionLocal() as s:
        stmt = select(AdminUser.id).where(AdminUser.matricula == matricula)
        return (await s.execute(stmt)).first() is not None


async def list_admins() -> list[dict]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(AdminUser).order_by(AdminUser.created_at))).scalars().all()
    return [{"matricula": r.matricula, "added_by": r.added_by, "created_at": r.created_at} for r in rows]


async def add_admin(matricula: str, added_by: str) -> str:
    """Adiciona a matrícula; ValueError se inválida ou já cadastrada."""
    matricula = normalize(matricula)
    if await is_admin(matricula):
        raise ValueError("Essa matrícula já é administradora.")
    async with AsyncSessionLocal() as s:
        s.add(AdminUser(matricula=matricula, added_by=added_by))
        await s.commit()
    return matricula


async def remove_admin(matricula: str) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(AdminUser).where(AdminUser.matricula == matricula.strip()))
        await s.commit()
