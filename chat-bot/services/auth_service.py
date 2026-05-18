import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from models.database import AsyncSessionLocal, UserAuth
from services import logger
from services.session_service import (
    delete_onboarding_link,
    delete_token,
    set_onboarding_link,
    set_token,
)
from config import APP_BASE_URL, SESSION_TTL_SECONDS, SUAP_BASE_URL


@dataclass
class LoginResult:
    success: bool
    message: str


async def generate_onboarding_link(chat_id: str) -> str:
    link_uuid = str(uuid.uuid4())
    await set_onboarding_link(link_uuid, chat_id, ttl=900)
    return f"{APP_BASE_URL}/auth/login?token={link_uuid}"


async def login_with_suap(chat_id: str, matricula: str, senha: str) -> LoginResult:
    suap_url = f"{SUAP_BASE_URL}/api/token/pair"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(suap_url, json={"username": matricula, "password": senha})
    except httpx.RequestError:
        return LoginResult(
            success=False,
            message="O SUAP está inacessível no momento. Tente novamente em alguns instantes.",
        )

    if resp.status_code == 401:
        return LoginResult(
            success=False,
            message="Matrícula ou senha incorretos. Verifique os dados e tente novamente.",
        )

    if resp.status_code != 200:
        logger.warn("AUTH", f"SUAP retornou status inesperado: {resp.status_code}")
        return LoginResult(
            success=False,
            message="Erro ao acessar o SUAP. Tente novamente mais tarde.",
        )

    data = resp.json()
    token = data.get("access")
    ttl_seconds = int(data.get("expires_in", SESSION_TTL_SECONDS))

    if not token:
        logger.warn("AUTH", "Token ausente na resposta do SUAP")
        return LoginResult(success=False, message="Resposta inesperada do SUAP. Tente novamente.")

    # Persiste vínculo no PostgreSQL — token nunca é armazenado aqui (RN01, RN03)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserAuth).where(UserAuth.chat_id == chat_id))
        user = result.scalar_one_or_none()
        if user:
            user.matricula = matricula
        else:
            user = UserAuth(chat_id=chat_id, matricula=matricula)
            session.add(user)
        await session.commit()

    await set_token(chat_id, token, ttl_seconds=ttl_seconds)
    logger.success("AUTH", f"Login realizado — chat_id={chat_id} matricula={matricula}")
    return LoginResult(success=True, message="Login realizado com sucesso! Pode voltar ao WhatsApp.")


async def logout(chat_id: str) -> None:
    await delete_token(chat_id)
    logger.info("AUTH", f"Sessão encerrada — chat_id={chat_id}")


async def get_linked_matricula(chat_id: str) -> str | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserAuth).where(UserAuth.chat_id == chat_id))
        user = result.scalar_one_or_none()
        return user.matricula if user else None
