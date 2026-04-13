import os
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

MODELO_AVALIADOR_LLM       = os.getenv("MODELO_AVALIADOR_LLM", "gpt-3.5-turbo")
MODELO_AVALIADOR_EMBEDDING = os.getenv("MODELO_AVALIADOR_EMBEDDING", "text-embedding-3-small")

def executar_metricas_ragas(dados_formatados: dict):
    """Converte os dados, inicializa os juízes LLM e calcula as métricas.

    Retorna:
        resultados: objeto EvaluationResult do Ragas
        info_modelos: dict com os modelos de avaliação utilizados
    """
    dataset = Dataset.from_dict(dados_formatados)

    print("\n📊 Executando Ragas (LLM-as-a-judge)...")
    print(f"   Avaliador LLM:        {MODELO_AVALIADOR_LLM}")
    print(f"   Avaliador Embedding:  {MODELO_AVALIADOR_EMBEDDING}")

    llm_avaliador       = ChatOpenAI(model=MODELO_AVALIADOR_LLM)
    embeddings_avaliador = OpenAIEmbeddings(model=MODELO_AVALIADOR_EMBEDDING)

    resultados = evaluate(
        dataset=dataset,
        metrics=[
            context_precision,
            context_recall,
            faithfulness,
            answer_relevancy,
        ],
        llm=llm_avaliador,
        embeddings=embeddings_avaliador
    )

    info_modelos = {
        "modelo_llm_avaliador":           MODELO_AVALIADOR_LLM,
        "modelo_embedding_avaliador":     MODELO_AVALIADOR_EMBEDDING,
    }

    return resultados, info_modelos