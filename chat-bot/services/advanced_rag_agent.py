import os
import hashlib
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document
from dotenv import load_dotenv

from sentence_transformers import CrossEncoder

load_dotenv()

# ---------------------------------------------------------------------------
# Configuração via variáveis de ambiente
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PG_CONNECTION = os.getenv(
    "PGVECTOR_CONNECTION_STRING",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/vetordatabase",
)
PGVECTOR_COLLECTION = os.getenv("PGVECTOR_COLLECTION", "manuais_suap_ifpi")
MODELO_LLM_RAPIDO = os.getenv("MODELO_LLM_RAPIDO", "gpt-4o-mini")
MODELO_LLM_AVANCADO = os.getenv("MODELO_LLM_AVANCADO", "gpt-4o")
MODELO_EMBEDDING = os.getenv("MODELO_EMBEDDING", "text-embedding-3-small")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
RERANKER_TOP_K = int(os.getenv("RERANKER_TOP_K", "3"))
MULTI_QUERY_COUNT = int(os.getenv("MULTI_QUERY_COUNT", "3"))
TEMPERATURE_AVANCADO = float(os.getenv("TEMPERATURE", "0.1"))
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    (
        "Você é um assistente virtual especialista nos manuais do SUAP do IFPI. "
        "Use o CONTEXTO abaixo para responder à pergunta do usuário. "
        "Sempre responda em Português (Brasil). "
        "Se a resposta não estiver no contexto, diga que não sabe. "
        "Não invente informações."
    ),
)

# ---------------------------------------------------------------------------
# Clientes compartilhados (inicializados uma única vez)
# ---------------------------------------------------------------------------
_openai_client = OpenAI(api_key=OPENAI_API_KEY)
_embeddings = OpenAIEmbeddings(model=MODELO_EMBEDDING, api_key=OPENAI_API_KEY)
_vector_store = PGVector(
    collection_name=PGVECTOR_COLLECTION,
    connection=PG_CONNECTION,
    embeddings=_embeddings,
)


# ---------------------------------------------------------------------------
# Fase 1 — Transformação da Consulta (Query Transformation)
# ---------------------------------------------------------------------------
class QueryTransformer:
    """Reescreve a query informal e gera variações semânticas."""

    def __init__(self, client: OpenAI, model: str):
        self._client = client
        self._model = model

    def rewrite(self, query: str) -> str:
        """Converte linguagem informal/gírias para o vocabulário oficial do SUAP."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um especialista nos sistemas acadêmicos do IFPI, especificamente o SUAP. "
                        "Reformule a pergunta do usuário convertendo linguagem informal, gírias e abreviações "
                        "para o vocabulário técnico e formal dos manuais oficiais do SUAP. "
                        "Retorne SOMENTE a pergunta reformulada, sem explicações."
                    ),
                },
                {"role": "user", "content": query},
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content.strip()

    def expand(self, query: str) -> List[str]:
        """Gera N variações semânticas da query reformulada."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Gere exatamente {MULTI_QUERY_COUNT} variações semânticas da pergunta fornecida "
                        "para buscar informações nos manuais do SUAP do IFPI. "
                        "Cada variação deve abordar o tema de um ângulo diferente. "
                        f"Retorne SOMENTE as {MULTI_QUERY_COUNT} variações, uma por linha, sem numeração."
                    ),
                },
                {"role": "user", "content": query},
            ],
            temperature=0.7,
        )
        lines = response.choices[0].message.content.strip().splitlines()
        return [v.strip() for v in lines if v.strip()][:MULTI_QUERY_COUNT]

    def transform(self, raw_query: str) -> Tuple[str, List[str]]:
        """Retorna (query_reformulada, [query_reformulada] + variações)."""
        rewritten = self.rewrite(raw_query)
        variations = self.expand(rewritten)
        return rewritten, [rewritten] + variations


# ---------------------------------------------------------------------------
# Fase 2 — Busca Vetorial Multivias (Retrieval)
# ---------------------------------------------------------------------------
class MultiviewRetriever:
    """Realiza buscas paralelas para todas as variações da query."""

    def __init__(self, store: PGVector, top_k: int):
        self._store = store
        self._top_k = top_k

    def _search_one(self, query: str) -> List[Document]:
        try:
            return self._store.similarity_search(query, k=self._top_k)
        except Exception as e:
            print(f"[Retriever] Erro na busca para '{query[:50]}': {e}")
            return []

    def retrieve(self, queries: List[str]) -> List[Document]:
        """Executa buscas em paralelo e retorna documentos únicos."""
        all_docs: List[Document] = []
        with ThreadPoolExecutor(max_workers=len(queries)) as executor:
            for docs in executor.map(self._search_one, queries):
                all_docs.extend(docs)
        return self._deduplicate(all_docs)

    @staticmethod
    def _deduplicate(docs: List[Document]) -> List[Document]:
        seen: set = set()
        unique: List[Document] = []
        for doc in docs:
            key = hashlib.md5(doc.page_content.encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(doc)
        return unique


# ---------------------------------------------------------------------------
# Fase 3 — Re-ranqueamento (Reranking)
# ---------------------------------------------------------------------------
class ContextReranker:
    """Aplica Cross-Encoder para reordenar os documentos por relevância."""

    def __init__(self, model_name: str, top_k: int):
        self._top_k = top_k
        self._model_name = model_name
        self._reranker = None
        self._load_reranker()

    def _load_reranker(self) -> None:
        try:
           

            print(f"[Reranker] Carregando modelo: {self._model_name}")
            self._reranker = CrossEncoder(self._model_name, max_length=512)
            print("[Reranker] Modelo carregado com sucesso.")
        except Exception as e:
            print(f"[Reranker] Falha ao carregar o modelo ({e}). Reranking desabilitado.")
            self._reranker = None

    def rerank(self, query: str, docs: List[Document]) -> List[Document]:
        if not docs:
            return docs

        if self._reranker is None:
            # Fallback: retorna os primeiros top_k sem reranking
            print("[Reranker] Usando fallback (sem reranking).")
            return docs[: self._top_k]

        pairs = [[query, doc.page_content] for doc in docs]
        scores = self._reranker.predict(pairs)
        ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
        return [doc for _, doc in ranked[: self._top_k]]


# ---------------------------------------------------------------------------
# Fase 4 — Geração da Resposta
# ---------------------------------------------------------------------------
class AnswerGenerator:
    """Monta o prompt e aciona o LLM principal para gerar a resposta."""

    def __init__(self, client: OpenAI, model: str, system_prompt: str, temperature: float):
        self._client = client
        self._model = model
        self._system_prompt = system_prompt
        self._temperature = temperature

    def generate(self, query: str, docs: List[Document]) -> str:
        context = "\n\n".join(doc.page_content for doc in docs)
        user_prompt = (
            "CONTEXTO RECUPERADO DOS MANUAIS:\n"
            "-----------------------------------\n"
            f"{context}\n"
            "-----------------------------------\n"
            f"PERGUNTA DO USUÁRIO: {query}"
        )
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self._temperature,
        )
        return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Orquestrador — Advanced RAG Pipeline
# ---------------------------------------------------------------------------
class AdvancedRAGPipeline:
    """
    Pipeline completo de Advanced RAG:
      Fase 1 → Transformação da Consulta (reescrita + expansão multi-query)
      Fase 2 → Busca Vetorial Multivias (retrieval paralelo + deduplicação)
      Fase 3 → Re-ranqueamento (Cross-Encoder BGE)
      Fase 4 → Geração da Resposta (LLM principal)
    """

    def __init__(self):
        self.transformer = QueryTransformer(_openai_client, MODELO_LLM_RAPIDO)
        self.retriever = MultiviewRetriever(_vector_store, RETRIEVAL_TOP_K)
        self.reranker = ContextReranker(RERANKER_MODEL, RERANKER_TOP_K)
        self.generator = AnswerGenerator(
            _openai_client, MODELO_LLM_AVANCADO, SYSTEM_PROMPT, TEMPERATURE_AVANCADO
        )

    def invoke(self, user_query: str) -> Tuple[str, List[dict]]:
        """
        Executa o pipeline completo.

        Retorna:
            resposta (str): texto gerado pelo LLM.
            metadados (List[dict]): metadados dos chunks usados no contexto.
        """
        print(f"\n[Advanced RAG] Query original: {user_query}")

        # Fase 1 — Transformação
        rewritten_query, all_queries = self.transformer.transform(user_query)
        print(f"[Advanced RAG] Query reescrita: {rewritten_query}")
        print(f"[Advanced RAG] Total de queries (1 + {len(all_queries) - 1} variações): {len(all_queries)}")

        # Fase 2 — Retrieval
        candidate_docs = self.retriever.retrieve(all_queries)
        print(f"[Advanced RAG] Documentos únicos recuperados: {len(candidate_docs)}")

        if not candidate_docs:
            return "Desculpe, não encontrei informações sobre isso nos manuais.", []

        # Fase 3 — Reranking
        top_docs = self.reranker.rerank(rewritten_query, candidate_docs)
        print(f"[Advanced RAG] Documentos após reranking (Top-{RERANKER_TOP_K}): {len(top_docs)}")

        # Fase 4 — Geração
        try:
            answer = self.generator.generate(rewritten_query, top_docs)
        except Exception as e:
            print(f"[Advanced RAG] Erro na geração: {e}")
            return "Desculpe, tive um erro ao processar sua pergunta.", []

        metadata = [doc.metadata for doc in top_docs]
        return answer, metadata


# ---------------------------------------------------------------------------
# Instância global (lazy — criada na primeira chamada)
# ---------------------------------------------------------------------------
_pipeline: AdvancedRAGPipeline | None = None


def gerar_resposta_avancada(pergunta: str) -> Tuple[str, List[dict]]:
    """Função de entrada compatível com a interface do rag_agent.py simples."""
    global _pipeline
    if _pipeline is None:
        _pipeline = AdvancedRAGPipeline()
    return _pipeline.invoke(pergunta)
