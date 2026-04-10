import json
import os
import requests
import datetime
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from dotenv import load_dotenv
import time

# 1. Carrega as variáveis de ambiente do arquivo .env
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
prompt_system = os.getenv("PROMPT_SYSTEM")

if not api_key:
    raise ValueError("Chave da API do Google não encontrada! Verifique se o arquivo .env existe e contém GEMINI_API_KEY.")

if not prompt_system:
    raise ValueError("Prompt do sistema não encontrado! Verifique se o arquivo .env existe e contém PROMPT_SYSTEM.")

# Configura o NOVO cliente do Gemini
client = genai.Client(api_key=api_key)

def extrair_texto_da_url(url):
    print(f"Acessando: {url}")
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    return soup.get_text(separator='\n', strip=True)

def dividir_em_chunks(texto, tamanho_max=3000):
    chunks = []
    while len(texto) > tamanho_max:
        ponto_de_corte = texto.rfind('.', 0, tamanho_max)
        if ponto_de_corte == -1: ponto_de_corte = tamanho_max
        chunks.append(texto[:ponto_de_corte+1])
        texto = texto[ponto_de_corte+1:].strip()
    chunks.append(texto)
    return chunks

def gerar_perguntas_com_ia(chunk_de_texto, persona_alvo, qtd_perguntas):
    # Injetamos a persona e a quantidade dinamicamente no prompt do sistema
    prompt_sistema = prompt_system.format(
        persona_alvo=persona_alvo, 
        qtd_perguntas=qtd_perguntas
    )
    
    try:
        prompt_usuario = f"Trecho do manual:\n\n{chunk_de_texto}"
        
        # Chamada usando a nova SDK
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_usuario,
            config=types.GenerateContentConfig(
                system_instruction=prompt_sistema,
                temperature=0.7,
                response_mime_type="application/json"
            )
        )
        
        # Faz o parse do texto gerado para dicionário Python
        resposta_json = json.loads(response.text)
        
        # Retorna a lista 'qna' conforme a estrutura esperada pelo seu código
        return resposta_json.get('qna', [])
        
    except Exception as e:
        print(f"Erro na API do Gemini: {e}")
        return []

def main():
    arquivo_config_manuais = "manuais.json"
    
    try:
        with open(arquivo_config_manuais, 'r', encoding='utf-8') as f:
            tarefas_geracao = json.load(f)
    except Exception as e:
        print(f"ERRO ao ler {arquivo_config_manuais}: {e}")
        return

    pasta_saida = "dataset"
    os.makedirs(pasta_saida, exist_ok=True)
    
    # --- CONFIGURAÇÃO DA META GLOBAL ---
    META_GLOBAL_PERGUNTAS = 10
    qtd_links = len(tarefas_geracao)
    
    # Matemática para distribuir as perguntas igualmente (e lidar com restos da divisão)
    cotas_por_link = [META_GLOBAL_PERGUNTAS // qtd_links + (1 if i < META_GLOBAL_PERGUNTAS % qtd_links else 0) for i in range(qtd_links)]
    
    print(f"Iniciando processamento. Meta global: {META_GLOBAL_PERGUNTAS} perguntas distribuídas em {qtd_links} manuais.\n")
    
    for indice_tarefa, tarefa in enumerate(tarefas_geracao):
        cota_deste_manual = cotas_por_link[indice_tarefa]
        nome_livro = tarefa['livro']
        
        print(f"--- Processando: {nome_livro} | Cota: {cota_deste_manual} pergunta(s) ---")
        
        # Se a cota for 0, pula o manual
        if cota_deste_manual == 0:
            print(" -> Cota zero para este manual. Pulando.")
            continue
            
        dataset_manual_atual = []
        texto_completo = extrair_texto_da_url(tarefa['url'])
        chunks = dividir_em_chunks(texto_completo)
        
        perguntas_faltantes = cota_deste_manual

        for chunk in chunks:
            # Se já bateu a cota deste manual, interrompe a leitura dos chunks e vai pro próximo livro
            if perguntas_faltantes <= 0:
                break
                
            if len(chunk) > 100:
                # Pede apenas a quantidade que falta para bater a cota
                perguntas_geradas = gerar_perguntas_com_ia(chunk, tarefa['persona'], perguntas_faltantes)
                dataset_manual_atual.extend(perguntas_geradas)
                
                # Abate da cota o que a IA conseguiu gerar
                perguntas_faltantes -= len(perguntas_geradas)
                print(f" -> Geradas: {len(perguntas_geradas)} | Faltam: {max(0, perguntas_faltantes)}")
                
                # NOVO: Pausa para não estourar a cota gratuita da API
                if perguntas_faltantes > 0:
                    print(" -> Aguardando 20 segundos para respeitar o limite gratuito da API...")
                    time.sleep(20)
        
        # Salva apenas se gerou alguma coisa
        if dataset_manual_atual:
            dataset_formatado = {}
            for index, item in enumerate(dataset_manual_atual, start=1):
                dataset_formatado[f"pergunta {index}"] = item
                
            data_atual = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            nome_arquivo_limpo = nome_livro.replace(" ", "_").lower()
            caminho_arquivo = os.path.join(pasta_saida, f"{nome_arquivo_limpo}_{data_atual}.json")
            
            with open(caminho_arquivo, 'w', encoding='utf-8') as f:
                json.dump(dataset_formatado, f, ensure_ascii=False, indent=4)
                
            print(f"✅ Arquivo salvo: {caminho_arquivo}\n")

if __name__ == "__main__":
    main()