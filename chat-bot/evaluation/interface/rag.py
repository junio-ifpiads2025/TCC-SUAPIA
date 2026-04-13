import os
import sys
from dataclasses import dataclass, field
from typing import List

# Ajusta o path para importar o seu bot
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from services.rag_agent import gerar_resposta, recuperar_contexto_e_metadata

# ==========================================
# NOSSA INTERFACE DE DADOS
# ==========================================
@dataclass
class RagasDataset:
    """Interface que define a estrutura de dados exigida pelo Ragas."""
    question: List[str] = field(default_factory=list)
    answer: List[str] = field(default_factory=list)
    contexts: List[List[str]] = field(default_factory=list)
    ground_truth: List[str] = field(default_factory=list)

    def adicionar_amostra(self, pergunta: str, resposta_ia: str, contexto: str, resposta_esperada: str):
        """Método helper para adicionar uma nova linha de avaliação de forma segura."""
        self.question.append(pergunta)
        self.answer.append(resposta_ia)
        self.contexts.append([contexto]) # Já coloca o contexto dentro da lista exigida
        self.ground_truth.append(resposta_esperada)
        
    def to_dict(self) -> dict:
        """Converte a classe para o dicionário que o HuggingFace exige."""
        return {
            "question": self.question,
            "answer": self.answer,
            "contexts": self.contexts,
            "ground_truth": self.ground_truth
        }

# ==========================================
# O RUNNER
# ==========================================
def gerar_dados_para_avaliacao(qa_dados: list) -> dict:
    """Passa as perguntas no seu Qdrant/OpenAI e estrutura os dados."""
    
    # Instancia a nossa interface limpa
    dataset_ragas = RagasDataset()

    print(f"⏳ Processando {len(qa_dados)} perguntas no banco vetorial...\n")
    
    for i, item in enumerate(qa_dados, 1):
        pergunta = item["user_input"]
        ground_truth = item["reference"]
        
        print(f"[{i}/{len(qa_dados)}] Coletando dados para: {pergunta}")
        
        # Chama as funções do seu bot
        resposta_ia, _ = gerar_resposta(pergunta)
        contexto_texto, _ = recuperar_contexto_e_metadata(pergunta)
        
        # Usa o método seguro da interface em vez de manipular o dicionário
        dataset_ragas.adicionar_amostra(
            pergunta=pergunta,
            resposta_ia=resposta_ia,
            contexto=contexto_texto,
            resposta_esperada=ground_truth
        )
        
    # Retorna como dicionário para não quebrar o evaluator.py
    return dataset_ragas.to_dict()