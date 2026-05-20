"""
Roteador de mensagens do SUAP-IA.

Classifica a mensagem recebida e despacha para o fluxo correto:
- Comandos especiais (/menu, /sair, etc.) são tratados diretamente.
- Mensagens de texto livre são enviadas ao agente (RAG ou ReAct).

O /sair é interceptado antes de route() ser chamado (em queue_service.enqueue),
portanto nunca chega aqui.
"""

import asyncio

from services import logger
from services.session_service import get_token
from config import FALLBACK_TEXT, MENU_TEXT, UNKNOWN_COMMAND_TEXT


async def route(chat_id: str, message: str) -> tuple[str, list[dict]]:
    """
    Classifica a mensagem e despacha para o fluxo correto (RF06, RN04).

    Retorna uma tupla (resposta, metadados), onde metadados contém
    informações de rastreabilidade retornadas pelo agente (ex: chunks usados).

    O agente é chamado via asyncio.to_thread pois as bibliotecas LangChain/
    OpenAI usadas internamente são síncronas e bloqueariam o event loop.
    """
    body = message.strip()

    # Comando de menu: retorna texto estático sem acionar o agente
    if body == "/menu":
        return MENU_TEXT, []

    # Qualquer outro comando desconhecido (RN04)
    # Nota: /sair é tratado antes de route() ser chamado
    if body.startswith("/"):
        return UNKNOWN_COMMAND_TEXT, []

    # Recupera o token do Redis para que o agente possa consultar a API do SUAP
    token = await get_token(chat_id) or ""
    try:
        resposta, metadata = await asyncio.to_thread(_call_agent, body, token)
        return resposta, metadata
    except Exception as e:
        logger.error("ROUTER", f"route_error chat_id={chat_id} error={e}")
        return FALLBACK_TEXT, []


def _call_agent(message: str, token: str) -> tuple[str, list[dict]]:
    """
    Chama o agente de forma síncrona (executado em thread separada).
    O import é feito localmente para evitar importação circular na inicialização.
    """
    from services.agent_orchestrator import gerar_resposta_agente
    return gerar_resposta_agente(message, token=token)
