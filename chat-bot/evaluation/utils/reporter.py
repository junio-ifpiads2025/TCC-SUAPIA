import os
import pandas as pd
from datetime import datetime

METRICAS = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]

def salvar_relatorio_csv(resultados, pasta_destino: str, metadata: dict = None):
    """Converte o resultado em uma tabela Pandas enriquecida e salva como CSV."""
    os.makedirs(pasta_destino, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_legivel = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    caminho_arquivo = os.path.join(pasta_destino, f"avaliacao_ragas_{timestamp}.csv")

    df = resultados.to_pandas()

    # --- Colunas de contexto: quantidade de chunks recuperados ---
    if "retrieved_contexts" in df.columns:
        df["num_contextos_recuperados"] = df["retrieved_contexts"].apply(
            lambda x: len(x) if isinstance(x, list) else 1
        )

    # --- Metadados por linha ---
    meta = metadata or {}
    df.insert(0, "data_avaliacao",          data_legivel)
    df.insert(1, "dataset_arquivo",         meta.get("dataset_arquivo", "N/A"))
    df.insert(2, "modelo_llm_rag",          meta.get("modelo_llm_rag", "N/A"))
    df.insert(3, "modelo_embedding_rag",    meta.get("modelo_embedding_rag", "N/A"))
    df.insert(4, "modelo_llm_avaliador",    meta.get("modelo_llm_avaliador", "N/A"))
    df.insert(5, "modelo_embedding_avaliador", meta.get("modelo_embedding_avaliador", "N/A"))
    df.insert(6, "temperature",             meta.get("temperature", "N/A"))
    df.insert(7, "system_prompt",           meta.get("system_prompt", "N/A"))

    # --- Linha de resumo com médias das métricas ---
    metricas_presentes = [m for m in METRICAS if m in df.columns]
    linha_resumo = {col: "" for col in df.columns}
    linha_resumo["data_avaliacao"]              = data_legivel
    linha_resumo["dataset_arquivo"]             = meta.get("dataset_arquivo", "N/A")
    linha_resumo["modelo_llm_rag"]              = meta.get("modelo_llm_rag", "N/A")
    linha_resumo["modelo_embedding_rag"]        = meta.get("modelo_embedding_rag", "N/A")
    linha_resumo["modelo_llm_avaliador"]        = meta.get("modelo_llm_avaliador", "N/A")
    linha_resumo["modelo_embedding_avaliador"]  = meta.get("modelo_embedding_avaliador", "N/A")
    linha_resumo["temperature"]                 = meta.get("temperature", "N/A")
    linha_resumo["system_prompt"]               = meta.get("system_prompt", "N/A")
    linha_resumo["user_input"]                  = "*** MÉDIA GERAL ***"
    for metrica in metricas_presentes:
        linha_resumo[metrica] = round(df[metrica].mean(), 6)
    if "num_contextos_recuperados" in df.columns:
        linha_resumo["num_contextos_recuperados"] = round(df["num_contextos_recuperados"].mean(), 2)

    df_final = pd.concat([df, pd.DataFrame([linha_resumo])], ignore_index=True)
    df_final.to_csv(caminho_arquivo, index=False, encoding='utf-8')

    # --- Resumo no terminal ---
    print("\n✅ Avaliação Concluída com Sucesso!")
    print(f"\n📈 Médias das Métricas:")
    for metrica in metricas_presentes:
        print(f"   {metrica:<25} {df[metrica].mean():.4f}")
    print(f"\n📂 Relatório detalhado salvo em: {caminho_arquivo}")