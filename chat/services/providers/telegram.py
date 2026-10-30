"""
Provider Telegram (Bot API) — implementa MessagingProvider.

Recebe updates via webhook (POST /webhook/telegram) e responde via sendMessage.
Diferenças em relação ao WhatsApp/WAHA:
  - não há "lida" para bots (marcar_lida usa o no-op padrão);
  - não há risco de ban, então sem delay artificial de digitação;
  - mensagens limitadas a 4096 caracteres (enviar_texto divide em partes);
  - texto enviado sem parse_mode: marcações como *negrito* aparecem literais.
"""

import hmac
import logging

import httpx
from fastapi import Request

from config import APP_BASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET
from services import logger
from services.providers.base import IncomingMessage, InvalidPayload, MessagingProvider

# O httpx loga a URL de cada request em INFO, e a URL da Bot API contém o token.
logging.getLogger("httpx").setLevel(logging.WARNING)

_API_URL = "https://api.telegram.org/bot{token}/{method}"
_MAX_LEN = 4096


def _split(texto: str, limit: int = _MAX_LEN) -> list[str]:
    """Divide em partes <= limit, preferindo quebrar em parágrafo, linha ou espaço."""
    parts = []
    while len(texto) > limit:
        cut = max(texto.rfind(sep, 0, limit) for sep in ("\n\n", "\n", " "))
        if cut <= 0:
            cut = limit
        parts.append(texto[:cut].rstrip())
        texto = texto[cut:].lstrip()
    if texto:
        parts.append(texto)
    return parts


class TelegramProvider(MessagingProvider):
    name = "telegram"

    async def _call(self, method: str, **params) -> dict | None:
        url = _API_URL.format(token=TELEGRAM_BOT_TOKEN, method=method)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=params)
            data = resp.json()
            if not data.get("ok"):
                logger.error("TELEGRAM", f"{method} falhou: {data.get('description')}")
                return None
            return data
        except Exception as e:
            # str(e) do httpx pode conter a URL (e portanto o token)
            logger.error("TELEGRAM", f"{method} erro: {type(e).__name__}")
            return None

    async def startup(self) -> None:
        if not TELEGRAM_BOT_TOKEN:
            logger.warn("TELEGRAM", "TELEGRAM_BOT_TOKEN ausente — provider inoperante")
            return
        if not APP_BASE_URL.startswith("https://"):
            logger.warn(
                "TELEGRAM",
                "APP_BASE_URL não é https público — webhook não registrado "
                "(em dev use um túnel, ex: ngrok/cloudflared)",
            )
            return
        params = {"url": f"{APP_BASE_URL.rstrip('/')}/webhook/telegram", "allowed_updates": ["message"]}
        if TELEGRAM_WEBHOOK_SECRET:
            params["secret_token"] = TELEGRAM_WEBHOOK_SECRET
        if await self._call("setWebhook", **params):
            logger.success("TELEGRAM", "Webhook registrado")

    async def parse_webhook(self, request: Request) -> IncomingMessage | None:
        if TELEGRAM_WEBHOOK_SECRET:
            received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not hmac.compare_digest(received, TELEGRAM_WEBHOOK_SECRET):
                raise InvalidPayload("secret inválido")

        update = await request.json()
        message = update.get("message")
        if not message:
            return None

        chat = message.get("chat") or {}
        text = message.get("text")
        # Apenas conversas privadas com texto (ignora grupos, mídia, etc.)
        if chat.get("type") != "private" or not text:
            return None
        if (message.get("from") or {}).get("is_bot"):
            return None
        if chat.get("id") is None:
            raise InvalidPayload("chat_id ausente")

        return IncomingMessage(
            chat_id=str(chat["id"]),
            text=text,
            message_id=str(message.get("message_id")),
        )

    async def enviar_texto(self, chat_id: str, texto: str) -> None:
        for part in _split(texto):
            await self._call("sendMessage", chat_id=chat_id, text=part)
        logger.success("TELEGRAM", f"Texto enviado para {chat_id}")

    async def enviar_imagem(self, chat_id: str, url: str) -> None:
        await self._call("sendPhoto", chat_id=chat_id, photo=url)

    async def iniciar_digitacao(self, chat_id: str) -> None:
        await self._call("sendChatAction", chat_id=chat_id, action="typing")
