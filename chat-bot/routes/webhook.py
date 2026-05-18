from fastapi import APIRouter, BackgroundTasks, Request

from services import logger
from services.auth_service import generate_onboarding_link, logout
from services.message_router import route
from services.session_service import delete_token, increment_rate, is_authenticated
from services.messaging_client import enviar_texto
from config import AGENT_NAME, MAX_DAILY_MESSAGES, NUMEROS_PERMITIDOS, RESPONDER_QUALQUER_NUMERO

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
            f"Olá! Para usar o {AGENT_NAME}, acesse o link abaixo para fazer login com sua conta SUAP "
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

    logger.incoming(chat_id, body)
    resposta, _ = await route(chat_id, body)
    logger.response_log(resposta)
    enviar_texto(chat_id, resposta)


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
