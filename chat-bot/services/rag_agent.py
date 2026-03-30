import os
from openai import OpenAI
from qdrant_client import QdrantClient
from dotenv import load_dotenv

load_dotenv()

# Configurações
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "manuais_suap_ifpi")

# Clientes
openai_client = OpenAI(api_key=OPENAI_API_KEY)
qdrant_client = QdrantClient(url=QDRANT_URL)

def recuperar_contexto_e_metadata(pergunta: str):
    """Busca o contexto relevante no Qdrant e retorna texto e metadados."""
    try:
        res_embedding = openai_client.embeddings.create(
            input=pergunta,
            model="text-embedding-3-small"
        )
        vetor = res_embedding.data[0].embedding

        # Faz a busca no Qdrant
        resposta = qdrant_client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=vetor,
            limit=3
        )
        
        # --- ALTERAÇÃO AQUI ---
        # Recuperamos o conteúdo de texto para a IA ler
        textos_recuperados = [hit.payload.get("page_content", "") for hit in resposta.points]
        contexto_final = "\n\n".join(textos_recuperados)
        
        # Recuperamos os metadados originais (que contém os links das imagens)
        metadados_recuperados = [hit.payload.get("metadata", {}) for hit in resposta.points]
        
        return contexto_final, metadados_recuperados
        # ----------------------
    except Exception as e:
        print(f"Erro no Qdrant: {e}")
        return "", []

def gerar_resposta(pergunta: str):
    """Orquestra o RAG: Recupera contexto e gera resposta com OpenAI."""
    
    # 1. Recupera o contexto e os metadados (incluindo links de imagens)
    contexto, metadados = recuperar_contexto_e_metadata(pergunta)
    
    if not contexto:
        # Se você alterou o System Prompt, mude aqui também
        return "Desculpe, não encontrei informações sobre isso nos manuais.", []
        
    # 2. Prepara o prompt (System e User)
    system_prompt = """Você é um assistente virtual especialista nos manuais do SUAP do IFPI. 
Use o CONTEXTO abaixo para responder à pergunta do usuário. 
Sempre responda em Português (Brasil).
Se a resposta não estiver no contexto, diga que não sabe. Não invente informações."""

    prompt_contexto = f"""CONTEXTO RECUPERADO DOS MANUAIS:
-----------------------------------
{contexto}
-----------------------------------
PERGUNTA DO USUÁRIO: {pergunta}"""

    try:
        # 3. Chama a OpenAI para gerar o texto
        res_openai = openai_client.chat.completions.create(
            model="gpt-3.5-turbo", # Ou gpt-4-turbo se tiver crédito
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_contexto}
            ],
            temperature=0.3 # Baixa temperatura para ser mais fiel ao texto
        )
        
        resposta_final_texto = res_openai.choices[0].message.content
        
        # 4. --- RETORNA A RESPOSTA DE TEXTO E OS METADADOS (PARA AS IMAGENS) ---
        return resposta_final_texto, metadados
        # -----------------------------------------------------------------------
        
    except Exception as e:
        print(f"Erro na OpenAI: {e}")
        return "Desculpe, tive um erro ao processar sua pergunta.", []