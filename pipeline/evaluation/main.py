import os
import glob
from dotenv import load_dotenv

# Importando os nossos próprios módulos
from utils.data_loader import carregar_dados_qa
from interface.rag import gerar_dados_para_avaliacao
from evaluator_ragas import executar_metricas_ragas
from utils.reporter import salvar_relatorio_csv

def main():
    """Função principal que orquestra o fluxo de avaliação."""

    # 0. Carrega as variáveis de ambiente (API Keys e configurações)
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

    # 1. Configura os caminhos
    diretorio_atual = os.path.dirname(__file__)
    pasta_dataset = os.path.join(diretorio_atual, 'dataset')
    pasta_resultados = os.path.join(diretorio_atual, 'results')

    # Pega o dataset mais recente da pasta automaticamente
    arquivos = sorted(glob.glob(os.path.join(pasta_dataset, '*.json')))
    if not arquivos:
        print("❌ Nenhum arquivo de dataset encontrado em 'dataset/'.")
        return
    caminho_qa = arquivos[-1]
    nome_dataset = os.path.basename(caminho_qa)
    print(f"📂 Dataset carregado: {nome_dataset}")

    print("🚀 Iniciando Pipeline de Avaliação do RAG...\n")

    # 2. Coleta metadados da configuração para enriquecer o relatório
    metadata = {
        "dataset_arquivo":            nome_dataset,
        "modelo_llm_rag":             os.getenv("MODELO_LLM", "N/A"),
        "modelo_embedding_rag":       os.getenv("MODELO_EMBEDDING", "N/A"),
        "temperature":                os.getenv("TEMPERATURE", "N/A"),
        "system_prompt":              os.getenv("SYSTEM_PROMPT", "N/A"),
    }

    # 3. Fluxo em formato de cascata (Pipeline)
    qa_dados = carregar_dados_qa(caminho_qa)
    dados_formatados = gerar_dados_para_avaliacao(qa_dados)
    resultados, info_modelos = executar_metricas_ragas(dados_formatados)

    # Incorpora os modelos do avaliador nos metadados
    metadata.update(info_modelos)

    salvar_relatorio_csv(resultados, pasta_resultados, metadata=metadata)

if __name__ == "__main__":
    main()