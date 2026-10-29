import os
import sys
from dataclasses import dataclass, field
from typing import List

# Ajusta o path para importar os serviços do bot
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'chat-bot')))

from services.rag_agent import gerar_resposta
from services.rag_agent import gerar_resposta_com_contexto


def _executar_com_contexto(pergunta: str):
    """Executa o RAG simples uma única vez e retorna (answer, context, metadata)."""
    return gerar_resposta_com_contexto(pergunta)


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
    pipeline_nome = "RAG Simples"
    dataset_ragas = RagasDataset()

    print(f"⏳ Processando {len(qa_dados)} perguntas [{pipeline_nome}]...\n")

    for i, item in enumerate(qa_dados, 1):
        pergunta = item["user_input"]
        ground_truth = item["reference"]

        print(f"[{i}/{len(qa_dados)}] {pergunta}")

        resposta_ia, contexto_texto, _ = _executar_com_contexto(pergunta)

        dataset_ragas.adicionar_amostra(
            pergunta=pergunta,
            resposta_ia=resposta_ia,
            contexto=contexto_texto,
            resposta_esperada=ground_truth,
        )

    return dataset_ragas.to_dict()
