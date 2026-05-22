"""
Serviço de autenticação com o SUAP (Sistema Unificado de Administração Pública).

Responsabilidades:
- Gerar links de onboarding únicos (UUID) enviados ao usuário via WhatsApp.
- Autenticar no SUAP com matrícula e senha via API REST.
- Persistir o vínculo chat_id ↔ matrícula no PostgreSQL.
- Armazenar o token de acesso no Redis (nunca no banco — RN01, RN03).
- Encerrar sessões (logout).
"""

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
    set_profile,
)
from config import APP_BASE_URL, SESSION_TTL_SECONDS, SUAP_BASE_URL


@dataclass
class LoginResult:
    """Resultado de uma tentativa de autenticação no SUAP."""
    success: bool
    message: str  # mensagem para exibir ao usuário (web ou WhatsApp)
    nome: str | None = None  # primeiro nome do usuário, preenchido após login bem-sucedido


async def generate_onboarding_link(chat_id: str) -> str:
    """
    Gera um link de login único para o usuário iniciar a autenticação SUAP.

    O UUID é armazenado no Redis com TTL de 15 minutos associado ao chat_id.
    Ao acessar o link, o usuário informa matrícula e senha no navegador.
    """
    link_uuid = str(uuid.uuid4())
    await set_onboarding_link(link_uuid, chat_id, ttl=900)
    return f"{APP_BASE_URL}/auth/login?token={link_uuid}"


async def login_with_suap(chat_id: str, matricula: str, senha: str) -> LoginResult:
    """
    Autentica o usuário na API do SUAP e persiste o resultado.

    Fluxo:
    1. POST para /api/token/pair do SUAP com matrícula e senha.
    2. Em caso de sucesso, salva/atualiza o registro em user_auth no PostgreSQL.
    3. Armazena o token de acesso no Redis com o TTL retornado pelo SUAP.

    Erros de rede ou status inesperado retornam LoginResult(success=False).
    O token nunca é armazenado no banco de dados (RN01, RN03).
    """
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
    # O SUAP retorna expires_in em segundos; usa SESSION_TTL_SECONDS como fallback
    ttl_seconds = int(data.get("expires_in", SESSION_TTL_SECONDS))

    if not token:
        logger.warn("AUTH", "Token ausente na resposta do SUAP")
        return LoginResult(success=False, message="Resposta inesperada do SUAP. Tente novamente.")

    # Persiste o vínculo chat_id ↔ matrícula no PostgreSQL (upsert)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserAuth).where(UserAuth.chat_id == chat_id))
        user = result.scalar_one_or_none()
        if user:
            user.matricula = matricula
        else:
            user = UserAuth(chat_id=chat_id, matricula=matricula)
            session.add(user)
        await session.commit()

    # Token vai apenas para o Redis — nunca para o banco (RN01, RN03)
    await set_token(chat_id, token, ttl_seconds=ttl_seconds)

    nome = await _fetch_and_save_profile(chat_id, token, ttl_seconds)

    logger.success("AUTH", f"Login realizado — chat_id={chat_id} matricula={matricula}")
    return LoginResult(success=True, message="Login realizado com sucesso! Pode voltar ao WhatsApp.", nome=nome)


async def logout(chat_id: str) -> None:
    """Remove o token do Redis, encerrando a sessão do usuário."""
    await delete_token(chat_id)
    logger.info("AUTH", f"Sessão encerrada — chat_id={chat_id}")


async def get_linked_matricula(chat_id: str) -> str | None:
    """Retorna a matrícula vinculada ao chat_id, ou None se não houver registro."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserAuth).where(UserAuth.chat_id == chat_id))
        user = result.scalar_one_or_none()
        return user.matricula if user else None


async def _fetch_and_save_profile(chat_id: str, token: str, ttl: int) -> str | None:
    """Busca nome e curso do usuário no SUAP e salva no Redis. Retorna o nome_usual."""
    try:
        from suap_api import SuapClient
        client = SuapClient(SUAP_BASE_URL, token=token)
        dados = client.comum.get_my_data()
        nome = dados.nome_usual or "Aluno"
        curso = dados.vinculo.curso if dados.vinculo else None
        await set_profile(chat_id, nome, curso, ttl)
        logger.success("AUTH", f"Perfil salvo — {nome} | curso={curso}")
        return nome
    except Exception as e:
        logger.error("AUTH", f"Falha ao buscar perfil SUAP: {e}")
        return None
