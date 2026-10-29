"""
Endpoint de recepção de eventos do WAHA (WhatsApp HTTP API).

O WAHA envia um POST para /webhook a cada evento da sessão WhatsApp
(mensagens recebidas, ACKs, mudanças de presença, etc.).
Este handler extrai apenas mensagens de texto recebidas pelo usuário
e as encaminha para a fila de processamento.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services import logger
from services.queue_service import enqueue
from config import NUMEROS_PERMITIDOS, RESPONDER_QUALQUER_NUMERO

router = APIRouter()

# Eventos que o WAHA envia mas que não precisam de processamento.
# Retornamos 200 para que o WAHA não fique reenviando.
_IGNORED_EVENTS = {
    "message.waiting_message",
    "message.ack",
    "message.revoked",
    "session.status",
    "presence.update",
}


@router.post("/webhook")
async def waha_webhook(request: Request):
    """
    Recebe eventos do WAHA e enfileira mensagens de texto para processamento.

    Fluxo:
    1. Ignora eventos que não são mensagens (ACKs, status, etc.).
    2. Valida presença de chat_id quando há body (RF09).
    3. Filtra por número permitido se RESPONDER_QUALQUER_NUMERO=False.
    4. Delega para queue_service.enqueue() e retorna 200 imediatamente (RF08, RNF01).
    """
    data = await request.json()

    event = data.get("event", "")

    # Eventos sem relevância para o fluxo de mensagens
    if event in _IGNORED_EVENTS:
        return {"status": "ignored"}

    payload = data.get("payload", {})
    body_text = payload.get("body")       # texto enviado pelo usuário
    chat_id = payload.get("from")         # identificador único do contato no WhatsApp
    message_id = payload.get("id")        # ID da mensagem (necessário para sendSeen)
    is_from_me = payload.get("fromMe")    # True quando a mensagem foi enviada pelo próprio bot

    # RF09: se há corpo de mensagem mas o remetente está ausente, o payload está malformado
    if body_text and not chat_id:
        logger.warn("WEBHOOK", f"Payload inválido — chat_id ausente (event={event})")
        return JSONResponse(status_code=400, content={"detail": "chat_id ausente"})

    if body_text and not is_from_me:
        # Controle de acesso por número: só responde a números na allowlist
        # (ou a qualquer número se RESPONDER_QUALQUER_NUMERO=True)
        if RESPONDER_QUALQUER_NUMERO or chat_id in NUMEROS_PERMITIDOS:
            await enqueue(chat_id, body_text, message_id)
        else:
            logger.warn("WEBHOOK", f"Número sem permissão: {chat_id}")

    # Retorna imediatamente para não bloquear o WAHA (RNF01)
    return {"status": "ok"}
