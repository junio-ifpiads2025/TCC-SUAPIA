import json
import sys

def carregar_dados_qa(caminho_arquivo: str) -> list:
    """Abre e lê o arquivo JSON com as perguntas e respostas esperadas (Ground Truth)."""
    try:
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Erro: Arquivo de Q&A não encontrado em: {caminho_arquivo}")
        print("Certifique-se de que a pasta 'dataset' e o arquivo 'questions_qa.json' existem.")
        sys.exit(1) # Mata a execução aqui