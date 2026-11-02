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

from services.shared import access_log_service, guardrail_service, logger, prompt_service
from services.chat import thread_service
from services.shared.session_service import get_token
from config import FALLBACK_TEXT, UNKNOWN_COMMAND_TEXT, about_text, menu_text

# Trechos que indicam que o agente não encontrou resposta (textos das tools de
# busca em rag_agent/_run_knowledge e as formas usuais da resposta final).
NO_ANSWER_MARKERS = (
    "não encontrei",
    "nenhuma informação encontrada",
    "não tenho informaç",
    "não sei responder",
    "não possuo informaç",
    "não consegui encontrar",
)


def _meta(chunks: list | None = None, no_answer: bool = False, ask_feedback: bool = False) -> dict:
    """
    Metadados da resposta:
    - chunks       : metadados dos trechos (manuais/base de conhecimento) usados;
    - no_answer    : o agente não encontrou resposta;
    - ask_feedback : resposta do agente que pode ser avaliada (não vale para comandos,
                     bloqueios de guardrail e falhas).
    """
    return {"chunks": chunks or [], "no_answer": no_answer, "ask_feedback": ask_feedback}


def is_no_answer(resposta: str, chunks: list | None) -> bool:
    """Sem trecho recuperado e com texto de "não encontrei" na resposta."""
    texto = (resposta or "").lower()
    return not chunks and any(m in texto for m in NO_ANSWER_MARKERS)


async def route(chat_id: str, message: str) -> tuple[str, dict]:
    """
    Classifica a mensagem e despacha para o fluxo correto (RF06, RN04).

    Retorna (resposta, metadados); ver `_meta`.
    """
    body = message.strip()

    # Comandos estáticos: não acionam o agente nem salvam histórico
    if body == "/menu":
        return menu_text(prompt_service.agent_name()), _meta()

    if body == "/about":
        return about_text(prompt_service.agent_name()), _meta()

    # Qualquer outro comando desconhecido (RN04)
    if body.startswith("/"):
        return UNKNOWN_COMMAND_TEXT, _meta()

    # Guardrail de entrada: bloqueia sem acionar o LLM
    gr = guardrail_service.check_input(body)
    if gr.blocked:
        access_log_service.log_event(chat_id, "guardrail_input", detail=gr.rule)
        return gr.response, _meta()

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
        return FALLBACK_TEXT, _meta()

    # Guardrail de saída: mascara/substitui antes de persistir e enviar
    resposta, regras = guardrail_service.apply_output(resposta)
    if regras:
        access_log_service.log_event(chat_id, "guardrail_output", detail=", ".join(regras))

    # Persiste o par (pergunta, resposta) no histórico para a próxima mensagem
    await thread_service.append_messages(chat_id, body, resposta)

    no_answer = is_no_answer(resposta, metadata)
    return resposta, _meta(metadata, no_answer=no_answer, ask_feedback=not no_answer)


def _call_agent(message: str, token: str, history: list[dict]) -> tuple[str, list[dict]]:
    """
    Chama o agente de forma síncrona (executado em thread separada via to_thread).
    O import é feito localmente para evitar importação circular na inicialização.
    """
    from services.chat.agent_orchestrator import gerar_resposta_agente
    return gerar_resposta_agente(message, token=token, history=history)
