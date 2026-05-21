"""
Roteador de mensagens do SUAP-IA.

Classifica a mensagem recebida e despacha para o fluxo correto:
- Comandos especiais (/menu) são tratados diretamente com texto estático.
- Mensagens de texto livre são enviadas ao agente com o histórico da conversa.

O /sair é interceptado antes de route() ser chamado (em queue_service.enqueue),
portanto nunca chega aqui.

O histórico de conversa (thread_service) é carregado antes de acionar o agente
e salvo após a resposta, permitindo que perguntas de acompanhamento referenciem
respostas anteriores sem novas chamadas ao SUAP.
"""

import asyncio

from services import logger
from services import thread_service
from services.session_service import get_token
from config import ABOUT_TEXT, FALLBACK_TEXT, MENU_TEXT, UNKNOWN_COMMAND_TEXT


async def route(chat_id: str, message: str) -> tuple[str, list[dict]]:
    """
    Classifica a mensagem e despacha para o fluxo correto (RF06, RN04).

    Retorna uma tupla (resposta, metadados), onde metadados contém
    informações de rastreabilidade retornadas pelo agente (ex: chunks RAG usados).
    """
    body = message.strip()

    # Comandos estáticos: não acionam o agente nem salvam histórico
    if body == "/menu":
        return MENU_TEXT, []

    if body == "/about":
        return ABOUT_TEXT, []

    # Qualquer outro comando desconhecido (RN04)
    if body.startswith("/"):
        return UNKNOWN_COMMAND_TEXT, []

    # Recupera token e histórico de forma concorrente
    token, history = await asyncio.gather(
        get_token(chat_id),
        thread_service.get_thread(chat_id),
    )
    token = token or ""

    try:
        resposta, metadata = await asyncio.to_thread(
            _call_agent, body, token, history
        )
    except Exception as e:
        logger.error("ROUTER", f"route_error chat_id={chat_id} error={e}")
        return FALLBACK_TEXT, []

    # Persiste o par (pergunta, resposta) no histórico para a próxima mensagem
    await thread_service.append_messages(chat_id, body, resposta)

    return resposta, metadata


def _call_agent(message: str, token: str, history: list[dict]) -> tuple[str, list[dict]]:
    """
    Chama o agente de forma síncrona (executado em thread separada via to_thread).
    O import é feito localmente para evitar importação circular na inicialização.
    """
    from services.agent_orchestrator import gerar_resposta_agente
    return gerar_resposta_agente(message, token=token, history=history)
