import os
from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv

load_dotenv()

from services import logger

# ---------------------------------------------------------------------------
# Seleção do pipeline via variável de ambiente
# USE_ADVANCED_RAG=true  → Advanced RAG (reescrita + multi-query + reranking)
# USE_ADVANCED_RAG=false → RAG simples (comportamento original)
# ---------------------------------------------------------------------------
_use_advanced = os.getenv("USE_ADVANCED_RAG", "false").lower() in ("true", "1", "t")

if _use_advanced:
    from services.advanced_rag_agent import gerar_resposta_avancada as gerar_resposta
    logger.success("BOOT", "Modo: Advanced RAG Pipeline")
else:
    from services.rag_agent import gerar_resposta
    logger.success("BOOT", "Modo: RAG Simples")

from services.waha_client import enviar_mensagem_waha, enviar_imagem_waha
from config import RESPONDER_QUALQUER_NUMERO, NUMEROS_PERMITIDOS

app = FastAPI(title="WhatsApp RAG Bot")


def processar_fluxo_mensagem(chat_id: str, pergunta: str):
    """Orquestra geração de resposta e envio (texto + imagens) em background."""

    logger.incoming(chat_id, pergunta)

    # 1. Gera a resposta com IA e recupera os metadados do banco vetorial
    resposta_ia, lista_metadata = gerar_resposta(pergunta)

    # 2. Envia o texto principal
    logger.response_log(resposta_ia)
    enviar_mensagem_waha(chat_id, resposta_ia)

    # 3. Coleta links de imagens únicos presentes nos chunks recuperados
    links_imagens_unicos = set()
    for metadata in lista_metadata:
        for link_img in metadata.get("links_imagens", []):
            if link_img:
                links_imagens_unicos.add(link_img)

    # 4. Envia cada imagem como mensagem separada
    if links_imagens_unicos:
        logger.info("IMAGENS", f"Enviando {len(links_imagens_unicos)} imagem(ns) do contexto...")
        for link_url in links_imagens_unicos:
            enviar_imagem_waha(chat_id, link_url)


@app.post("/webhook")
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
            background_tasks.add_task(processar_fluxo_mensagem, chat_id, body)
        else:
            logger.warn("WEBHOOK", f"Mensagem ignorada — número sem permissão: {chat_id}")

    return {"status": "ok"}
