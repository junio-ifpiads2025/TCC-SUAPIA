import asyncio

from services import logger
from services.session_service import get_token
from config import FALLBACK_TEXT, MENU_TEXT, UNKNOWN_COMMAND_TEXT


async def route(chat_id: str, message: str) -> tuple[str, list[dict]]:
    """Classifica a mensagem e despacha para o fluxo correto (RF06, RN04)."""
    body = message.strip()

    if body == "/menu":
        return MENU_TEXT, []

    # Qualquer outro comando desconhecido (RN04). /sair é tratado antes de route() ser chamado.
    if body.startswith("/"):
        return UNKNOWN_COMMAND_TEXT, []

    token = await get_token(chat_id) or ""
    try:
        resposta, metadata = await asyncio.to_thread(_call_agent, body, token)
        return resposta, metadata
    except Exception as e:
        logger.error("ROUTER", f"route_error chat_id={chat_id} error={e}")
        return FALLBACK_TEXT, []


def _call_agent(message: str, token: str) -> tuple[str, list[dict]]:
    from services.agent_orchestrator import gerar_resposta_agente
    return gerar_resposta_agente(message, token=token)
