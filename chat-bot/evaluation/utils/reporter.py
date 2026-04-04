import os
from datetime import datetime

def salvar_relatorio_csv(resultados, pasta_destino: str):
    """Converte o resultado em uma tabela Pandas e salva como CSV."""
    os.makedirs(pasta_destino, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho_arquivo = os.path.join(pasta_destino, f"avaliacao_ragas_{timestamp}.csv")
    
    df_resultados = resultados.to_pandas()
    df_resultados.to_csv(caminho_arquivo, index=False, encoding='utf-8')
    
    print("\n✅ Avaliação Concluída com Sucesso!")
    print(f"📈 Resumo das Médias:\n{resultados}")
    print(f"\n📂 Relatório detalhado salvo em: {caminho_arquivo}")