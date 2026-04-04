from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

def executar_metricas_ragas(dados_formatados: dict):
    """Converte os dados, inicializa os juízes LLM e calcula as métricas."""
    dataset = Dataset.from_dict(dados_formatados)

    print("\n📊 Executando Ragas (LLM-as-a-judge)...")
    
    llm_avaliador = ChatOpenAI(model="gpt-3.5-turbo")
    embeddings_avaliador = OpenAIEmbeddings(model="text-embedding-3-small")
    
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
    
    return resultados