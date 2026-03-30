from fastapi import FastAPI, Request, BackgroundTasks
from services.rag_agent import gerar_resposta
from services.waha_client import enviar_mensagem_waha

app = FastAPI(title="WhatsApp RAG Bot")

def processar_fluxo_mensagem(chat_id: str, pergunta: str):
    """Função orquestradora que roda em background."""
    # 1. Gera a resposta com IA
    resposta = gerar_resposta(pergunta)
    
    # 2. Envia de volta para o usuário
    enviar_mensagem_waha(chat_id, resposta)

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
        # Delega o processamento pesado para background
        background_tasks.add_task(processar_fluxo_mensagem, chat_id, body)

    return {"status": "ok"}