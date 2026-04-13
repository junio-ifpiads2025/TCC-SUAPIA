import os
from openai import OpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from dotenv import load_dotenv

load_dotenv()

# --- Configurações Iniciais ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PG_CONNECTION = os.getenv(
    "PGVECTOR_CONNECTION_STRING",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/vetordatabase"
)
PGVECTOR_COLLECTION = os.getenv("PGVECTOR_COLLECTION", "manuais_suap_ifpi")

# --- Novas Configurações via .env ---
MODELO_LLM = os.getenv("MODELO_LLM", "gpt-3.5-turbo")
MODELO_EMBEDDING = os.getenv("MODELO_EMBEDDING", "text-embedding-3-small")
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Você é um assistente virtual especialista nos manuais do SUAP do IFPI. Use o CONTEXTO abaixo para responder à pergunta do usuário. Sempre responda em Português (Brasil). Se a resposta não estiver no contexto, diga que não sabe. Não invente informações."
)
# Converte a temperatura para float (decimal), usando 0.3 como padrão se não encontrar
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.3"))

# Clientes
openai_client = OpenAI(api_key=OPENAI_API_KEY)
embeddings = OpenAIEmbeddings(model=MODELO_EMBEDDING, api_key=OPENAI_API_KEY)
vector_store = PGVector(
    collection_name=PGVECTOR_COLLECTION,
    connection=PG_CONNECTION,
    embeddings=embeddings,
)

def recuperar_contexto_e_metadata(pergunta: str):
    """Busca o contexto relevante no pgvector e retorna texto e metadados."""
    try:
        docs = vector_store.similarity_search(pergunta, k=3)

        textos_recuperados = [doc.page_content for doc in docs]
        contexto_final = "\n\n".join(textos_recuperados)

        metadados_recuperados = [doc.metadata for doc in docs]

        return contexto_final, metadados_recuperados
    except Exception as e:
        print(f"Erro no pgvector: {e}")
        return "", []

def gerar_resposta(pergunta: str):
    """Orquestra o RAG: Recupera contexto e gera resposta com OpenAI."""
    
    # 1. Recupera o contexto e os metadados (incluindo links de imagens)
    contexto, metadados = recuperar_contexto_e_metadata(pergunta)
    
    if not contexto:
        return "Desculpe, não encontrei informações sobre isso nos manuais.", []
        
    # 2. Prepara o prompt (User)
    # O System Prompt agora vem diretamente da variável global SYSTEM_PROMPT configurada no .env
    prompt_contexto = f"""CONTEXTO RECUPERADO DOS MANUAIS:
-----------------------------------
{contexto}
-----------------------------------
PERGUNTA DO USUÁRIO: {pergunta}"""

    try:
        # 3. Chama a OpenAI para gerar o texto
        res_openai = openai_client.chat.completions.create(
            model=MODELO_LLM, # Usa o modelo do .env
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT}, # Usa o prompt do .env
                {"role": "user", "content": prompt_contexto}
            ],
            temperature=TEMPERATURE # Usa a temperatura do .env
        )
        
        resposta_final_texto = res_openai.choices[0].message.content
        
        # 4. Retorna a resposta de texto e os metadados
        return resposta_final_texto, metadados
        
    except Exception as e:
        print(f"Erro na OpenAI: {e}")
        return "Desculpe, tive um erro ao processar sua pergunta.", []