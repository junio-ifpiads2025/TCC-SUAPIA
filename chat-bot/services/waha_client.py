"""
Cliente WAHA — implementação do contrato de mensageria para o provider WAHA.

⚠️  Comportamento anti-ban (WAHA-específico, RN14)
    Antes de enviar qualquer mensagem de texto o cliente executa a sequência:
      1. sendSeen      — marca a mensagem do usuário como lida
      2. startTyping   — aciona o indicador "digitando..."
      3. sleep(delay)  — aguarda tempo proporcional ao tamanho da resposta
      4. stopTyping    — encerra o indicador
      5. sendText      — envia o texto

    Esse padrão é exigido pelo WAHA para reduzir o risco de bloqueio do número.
    Não faz parte do contrato público (messaging_client.py) pois é detalhe do provider.
"""
import asyncio
import os
import random
import time

import httpx
import requests
from dotenv import load_dotenv

from services import logger

load_dotenv()

WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "http://localhost:3000")

_DEFAULT_SESSION = "default"


def _typing_delay(texto: str) -> float:
    """Retorna um delay em segundos proporcional ao tamanho da mensagem (máx 8s)."""
    chars = len(texto)
    delay = random.uniform(1.0, 2.0) + chars * random.uniform(0.01, 0.03)
    return min(delay, 8.0)


def _session(chat_id: str) -> dict:
    return {"chatId": chat_id, "session": _DEFAULT_SESSION}


# ── Sync (usado em webhook.py) ────────────────────────────────────────────────

def enviar_mensagem_waha(chat_id: str, texto: str):
    try:
        requests.post(f"{WAHA_BASE_URL}/api/sendSeen", json=_session(chat_id), timeout=5)
        requests.post(f"{WAHA_BASE_URL}/api/startTyping", json=_session(chat_id), timeout=5)
        time.sleep(_typing_delay(texto))
        requests.post(f"{WAHA_BASE_URL}/api/stopTyping", json=_session(chat_id), timeout=5)
        resp = requests.post(
            f"{WAHA_BASE_URL}/api/sendText",
            json={**_session(chat_id), "text": texto},
            timeout=10,
        )
        logger.success("WAHA", f"Texto enviado para {chat_id}")
        return resp.json()
    except Exception as e:
        logger.error("WAHA", f"Erro ao enviar texto: {e}")
        return None


def enviar_imagem_waha(chat_id: str, image_url: str):
    payload = {**_session(chat_id), "file": {"url": image_url}}
    try:
        logger.image_log(chat_id, image_url)
        resp = requests.post(f"{WAHA_BASE_URL}/api/sendImage", json=payload, timeout=15)
        time.sleep(1)
        return resp.json()
    except Exception as e:
        logger.error("WAHA", f"Erro ao enviar imagem: {e}")
        return None


# ── Async (usado em auth.py via BackgroundTasks) ──────────────────────────────

async def enviar_mensagem_waha_async(chat_id: str, texto: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{WAHA_BASE_URL}/api/sendSeen", json=_session(chat_id))
            await client.post(f"{WAHA_BASE_URL}/api/startTyping", json=_session(chat_id))
            await asyncio.sleep(_typing_delay(texto))
            await client.post(f"{WAHA_BASE_URL}/api/stopTyping", json=_session(chat_id))
            await client.post(
                f"{WAHA_BASE_URL}/api/sendText",
                json={**_session(chat_id), "text": texto},
            )
        logger.success("WAHA", f"Notificação enviada para {chat_id}")
    except Exception as e:
        logger.error("WAHA", f"Erro ao enviar notificação: {e}")
