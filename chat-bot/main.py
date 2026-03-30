from fastapi import FastAPI, Request, BackgroundTasks
from services.rag_agent import gerar_resposta
from services.waha_client import enviar_mensagem_waha, enviar_imagem_waha # Importando a nova função
from config import RESPONDER_QUALQUER_NUMERO, NUMEROS_PERMITIDOS

app = FastAPI(title="WhatsApp RAG Bot")

def processar_fluxo_mensagem(chat_id: str, pergunta: str):
    """Função orquestradora que roda em background (envia texto e depois imagens)."""
    
    # 1. Gera a resposta com IA e recupera os metadados brutos do Qdrant
    resposta_ia, lista_metadata = gerar_resposta(pergunta)
    
    # 2. Envia a resposta de texto PRINCIPAL gerada pela OpenAI
    # (É importante enviar o texto primeiro para o usuário ter a resposta rápida)
    enviar_mensagem_waha(chat_id, resposta_ia)
    
    # 3. --- ORQUESTRADOR DE IMAGENS ---
    # Coletamos todos os links de imagens únicos encontrados nos documentos recuperados
    links_imagens_unicos = set() # Usamos um Set para evitar imagens duplicadas
    for metadata in lista_metadata:
        for link_img in metadata.get("links_imagens", []):
            if link_img:
                links_imagens_unicos.add(link_img)
    
    # Envia cada imagem encontrada como uma mensagem separada logo em seguida
    if links_imagens_unicos:
        print(f"🖼️ Achadas {len(links_imagens_unicos)} imagens no contexto. Enviando...")
        for link_url in links_imagens_unicos:
            enviar_imagem_waha(chat_id, link_url)
    # -----------------------------------

@app.post("/webhook")
async def waha_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    
    if data.get("event") == "message.waiting_message":
        return {"status": "ignored"}

    payload = data.get("payload", {})
    body = payload.get("body")
    chat_id = payload.get("from")
    is_from_me = payload.get("fromMe")

    # Verifica se a mensagem tem corpo e não foi enviada pelo próprio bot
    if body and not is_from_me:
        if RESPONDER_QUALQUER_NUMERO or chat_id in NUMEROS_PERMITIDOS:
            # Chama a orquestração em background task
            background_tasks.add_task(processar_fluxo_mensagem, chat_id, body)
        else:
            print(f"🔒 Mensagem ignorada. O número {chat_id} não tem permissão.")

    return {"status": "ok"}