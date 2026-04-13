import os
import sys
from dataclasses import dataclass, field
from typing import List

# Ajusta o path para importar os serviços do bot
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Seleção do pipeline de acordo com a variável de ambiente
_use_advanced = os.getenv("USE_ADVANCED_RAG", "false").lower() in ("true", "1", "t")

if _use_advanced:
    from services.advanced_rag_agent import gerar_resposta_avancada as gerar_resposta
    from services.advanced_rag_agent import AdvancedRAGPipeline

    def recuperar_contexto_e_metadata(pergunta: str):
        """Recupera contexto via pipeline avançado (reescrita + multi-query + reranking)."""
        pipeline = AdvancedRAGPipeline()
        _, rewritten_queries = pipeline.transformer.transform(pergunta)
        docs = pipeline.retriever.retrieve(rewritten_queries)
        top_docs = pipeline.reranker.rerank(rewritten_queries[0], docs)
        contexto = "\n\n".join(doc.page_content for doc in top_docs)
        metadados = [doc.metadata for doc in top_docs]
        return contexto, metadados
else:
    from services.rag_agent import gerar_resposta, recuperar_contexto_e_metadata


# ==========================================
# INTERFACE DE DADOS PARA O RAGAS
# ==========================================
@dataclass
class RagasDataset:
    """Estrutura de dados exigida pelo framework Ragas."""
    question: List[str] = field(default_factory=list)
    answer: List[str] = field(default_factory=list)
    contexts: List[List[str]] = field(default_factory=list)
    ground_truth: List[str] = field(default_factory=list)

    def adicionar_amostra(self, pergunta: str, resposta_ia: str, contexto: str, resposta_esperada: str):
        self.question.append(pergunta)
        self.answer.append(resposta_ia)
        self.contexts.append([contexto])
        self.ground_truth.append(resposta_esperada)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "contexts": self.contexts,
            "ground_truth": self.ground_truth,
        }


# ==========================================
# RUNNER
# ==========================================
def gerar_dados_para_avaliacao(qa_dados: list) -> dict:
    """Passa as perguntas pelo pipeline RAG ativo e estrutura os dados para o Ragas."""
    pipeline_nome = "Advanced RAG" if _use_advanced else "RAG Simples"
    dataset_ragas = RagasDataset()

    print(f"⏳ Processando {len(qa_dados)} perguntas [{pipeline_nome}]...\n")

    for i, item in enumerate(qa_dados, 1):
        pergunta = item["user_input"]
        ground_truth = item["reference"]

        print(f"[{i}/{len(qa_dados)}] {pergunta}")

        resposta_ia, _ = gerar_resposta(pergunta)
        contexto_texto, _ = recuperar_contexto_e_metadata(pergunta)

        dataset_ragas.adicionar_amostra(
            pergunta=pergunta,
            resposta_ia=resposta_ia,
            contexto=contexto_texto,
            resposta_esperada=ground_truth,
        )

    return dataset_ragas.to_dict()
