import asyncio

from fastapi import APIRouter, BackgroundTasks, Request

from services import logger
from services.advanced_rag_agent import gerar_resposta_crag
from services.auth_service import generate_onboarding_link, logout
from services.session_service import delete_token, increment_rate, is_authenticated
from services.messaging_client import enviar_texto, enviar_imagem
from config import MAX_DAILY_MESSAGES, NUMEROS_PERMITIDOS, RESPONDER_QUALQUER_NUMERO

router = APIRouter()


# ── Background task ───────────────────────────────────────────────────────────

async def _processar_mensagem(chat_id: str, body: str) -> None:
    # RF04: /sair
    if body.strip() == "/sair":
        await delete_token(chat_id)
        await logout(chat_id)
        enviar_texto(
            chat_id,
            "Sessão encerrada. Na próxima mensagem você receberá o link de login.",
        )
        return

    # RF01: autenticação obrigatória
    if not await is_authenticated(chat_id):
        link = await generate_onboarding_link(chat_id)
        enviar_texto(
            chat_id,
            f"Olá! Para usar o SUAP-IA, acesse o link abaixo para fazer login com sua conta SUAP "
            f"(válido por 15 minutos):\n\n{link}",
        )
        return

    # RN06: rate limit diário
    count = await increment_rate(chat_id)
    if count > MAX_DAILY_MESSAGES:
        enviar_texto(
            chat_id,
            "Você atingiu o limite de 25 mensagens por dia. Tente novamente amanhã.",
        )
        return

    # Processa a mensagem via pipeline IA (função síncrona → thread pool)
    logger.incoming(chat_id, body)
    resposta_ia, lista_metadata = await asyncio.to_thread(gerar_resposta_crag, body)
    logger.response_log(resposta_ia)
    enviar_texto(chat_id, resposta_ia)

    # links = {link for m in lista_metadata for link in m.get("links_imagens", []) if link}
    # if links:
    #     logger.info("IMAGENS", f"Enviando {len(links)} imagem(ns)...")
    #     for url in links:
    #         enviar_imagem(chat_id, url)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def waha_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    if data.get("event") == "message.waiting_message":
        return {"status": "ignored"}

    payload = data.get("payload", {})
    body = payload.get("body")
    chat_id = payload.get("from")
    is_from_me = payload.get("fromMe")

    if body and not is_from_me:
        if RESPONDER_QUALQUER_NUMERO or chat_id in NUMEROS_PERMITIDOS:
            background_tasks.add_task(_processar_mensagem, chat_id, body)
        else:
            logger.warn("WEBHOOK", f"Número sem permissão: {chat_id}")

    return {"status": "ok"}
