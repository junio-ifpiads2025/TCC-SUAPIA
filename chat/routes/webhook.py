"""
Endpoint de recepção de eventos das plataformas de mensageria.

Cada provider habilitado recebe seus eventos em POST /webhook/<provider>.
POST /webhook é mantido como alias do WAHA para não exigir reconfiguração
do webhook já cadastrado.

A tradução do payload da plataforma para IncomingMessage é responsabilidade do
provider (parse_webhook); este handler só aplica controle de acesso e enfileira.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services import logger
from services.providers import DEFAULT_PROVIDER, InvalidPayload, get_provider, qualify
from services import acl_service, access_log_service
from services.queue_service import enqueue

router = APIRouter()


@router.post("/webhook")
async def default_webhook(request: Request):
    return await _handle(DEFAULT_PROVIDER, request)


@router.post("/webhook/{provider_name}")
async def provider_webhook(provider_name: str, request: Request):
    return await _handle(provider_name, request)


async def _handle(provider_name: str, request: Request):
    """
    Fluxo:
    1. Provider converte o payload em IncomingMessage (None = evento ignorado).
    2. Payload inválido -> 400 (RF09).
    3. Aplica acl_service.check (bloqueado/negado: descarta e registra no log).
    4. Delega para queue_service.enqueue() e retorna 200 imediatamente (RF08, RNF01).
    """
    try:
        provider = get_provider(provider_name)
    except KeyError:
        return JSONResponse(status_code=404, content={"detail": "provider desconhecido"})

    try:
        msg = await provider.parse_webhook(request)
    except InvalidPayload as e:
        logger.warn("WEBHOOK", f"Payload inválido — {e} (provider={provider_name})")
        return JSONResponse(status_code=400, content={"detail": str(e)})

    if msg is None:
        return {"status": "ignored"}

    chat_id = qualify(provider_name, msg.chat_id)

    # Controle de acesso via cache em memória (block vence; sem I/O)
    verdict = acl_service.check(chat_id)
    if verdict == "ok":
        access_log_service.log_event(
            chat_id, "received", provider=provider_name,
            detail=access_log_service.describe_content(msg.text or ""))
        await enqueue(chat_id, msg.text, msg.message_id)
    else:
        # Descartado em silêncio (sem resposta ao usuário)
        access_log_service.log_event(chat_id, verdict, provider=provider_name)

    # Retorna imediatamente para não bloquear a plataforma (RNF01)
    return {"status": "ok"}
