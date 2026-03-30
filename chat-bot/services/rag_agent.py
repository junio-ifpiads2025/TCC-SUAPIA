from openai import OpenAI
from qdrant_client import QdrantClient
from config import OPENAI_API_KEY, QDRANT_URL, QDRANT_COLLECTION

openai_client = OpenAI(api_key=OPENAI_API_KEY)
qdrant_client = QdrantClient(url=QDRANT_URL)

def recuperar_contexto(pergunta: str) -> str:
    """Busca o contexto relevante no Qdrant."""
    try:
        res_embedding = openai_client.embeddings.create(
            input=pergunta,
            model="text-embedding-3-small"
        )
        vetor = res_embedding.data[0].embedding

        resultados = qdrant_client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=vetor,
            limit=3
        )
        
        return "\n\n".join([hit.payload.get("texto", "") for hit in resultados])
    except Exception as e:
        print(f"Erro no Qdrant: {e}")
        return ""

def gerar_resposta(pergunta_usuario: str) -> str:
    """Orquestra o RAG e retorna a resposta gerada pelo LLM."""
    contexto = recuperar_contexto(pergunta_usuario)

    system_prompt = f"""Você é um assistente virtual inteligente.
Responda baseando-se APENAS no contexto abaixo.
Se a resposta não estiver no contexto, diga que não sabe.

CONTEXTO:
{contexto}"""

    try:
        resposta_llm = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": pergunta_usuario}
            ],
            temperature=0.2
        )
        return resposta_llm.choices[0].message.content
    except Exception as e:
        print(f"Erro na OpenAI: {e}")
        return "Desculpe, ocorreu um erro ao processar sua solicitação."