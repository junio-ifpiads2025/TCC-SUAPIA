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

    # 0. Carrega as variáveis de ambiente (API Keys)
    load_dotenv()

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
    print(f"📂 Dataset carregado: {os.path.basename(caminho_qa)}")
    
    print("🚀 Iniciando Pipeline de Avaliação do RAG...\n")
    
    # 2. Fluxo em formato de cascata (Pipeline)
    qa_dados = carregar_dados_qa(caminho_qa)
    dados_formatados = gerar_dados_para_avaliacao(qa_dados)
    resultados = executar_metricas_ragas(dados_formatados)
    salvar_relatorio_csv(resultados, pasta_resultados)

if __name__ == "__main__":
    main()