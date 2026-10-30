"""
Provider WAHA (WhatsApp HTTP API) — implementa MessagingProvider.

Os detalhes específicos do WAHA (anti-ban RN14: sendSeen → typing → delay → sendText)
ficam em services/waha_client.py; este módulo só adapta ao contrato.
"""

import asyncio

from fastapi import Request

from services import waha_client
from services.providers.base import IncomingMessage, InvalidPayload, MessagingProvider

# Eventos que o WAHA envia mas que não precisam de processamento.
_IGNORED_EVENTS = {
    "message.waiting_message",
    "message.ack",
    "message.revoked",
    "session.status",
    "presence.update",
}


class WahaProvider(MessagingProvider):
    name = "waha"

    async def parse_webhook(self, request: Request) -> IncomingMessage | None:
        data = await request.json()

        if data.get("event", "") in _IGNORED_EVENTS:
            return None

        payload = data.get("payload", {})
        body_text = payload.get("body")
        chat_id = payload.get("from")

        # RF09: há corpo de mensagem mas o remetente está ausente
        if body_text and not chat_id:
            raise InvalidPayload("chat_id ausente")

        if not body_text or payload.get("fromMe"):
            return None

        return IncomingMessage(chat_id=chat_id, text=body_text, message_id=payload.get("id"))

    async def enviar_texto(self, chat_id: str, texto: str) -> None:
        await waha_client.enviar_mensagem_waha_async(chat_id, texto)

    async def enviar_imagem(self, chat_id: str, url: str) -> None:
        # waha_client.enviar_imagem_waha usa requests (síncrono)
        await asyncio.to_thread(waha_client.enviar_imagem_waha, chat_id, url)

    async def marcar_lida(self, chat_id: str, message_id: str | None = None) -> None:
        await waha_client.marcar_lida_waha_async(chat_id, message_id)

    async def iniciar_digitacao(self, chat_id: str) -> None:
        await waha_client.iniciar_digitacao_waha_async(chat_id)
