import json
import os
import time
import requests
import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
prompt_system = os.getenv("PROMPT_SYSTEM")
modelo_gemini = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
meta_global = int(os.getenv("QTD_PERGUNTAS", "10"))

if not api_key:
    raise ValueError("Chave da API do Google não encontrada! Verifique se o arquivo .env existe e contém GEMINI_API_KEY.")
if not prompt_system:
    raise ValueError("Prompt do sistema não encontrado! Verifique se o arquivo .env existe e contém PROMPT_SYSTEM.")

client = genai.Client(api_key=api_key)

BASE_DIR = Path(__file__).parent
DELAY_ENTRE_CHAMADAS = 2  # segundos entre chamadas à API
MAX_TENTATIVAS = 3


def extrair_texto_da_url(url: str) -> str:
    print(f"Acessando: {url}")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    return soup.get_text(separator='\n', strip=True)


def dividir_em_chunks(texto: str, tamanho_max: int = 3000) -> list[str]:
    chunks = []
    while len(texto) > tamanho_max:
        ponto_de_corte = texto.rfind('.', 0, tamanho_max)
        if ponto_de_corte == -1:
            ponto_de_corte = tamanho_max
        chunks.append(texto[:ponto_de_corte + 1])
        texto = texto[ponto_de_corte + 1:].strip()
    if texto:
        chunks.append(texto)
    return chunks


def gerar_perguntas_com_ia(chunk: str, persona_alvo: str, qtd_perguntas: int) -> list[dict]:
    prompt_sistema = prompt_system.format(
        persona_alvo=persona_alvo,
        qtd_perguntas=qtd_perguntas
    )
    prompt_usuario = f"Trecho do manual:\n\n{chunk}"

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            response = client.models.generate_content(
                model=modelo_gemini,
                contents=prompt_usuario,
                config=types.GenerateContentConfig(
                    system_instruction=prompt_sistema,
                    temperature=0.7,
                    response_mime_type="application/json"
                )
            )
            resposta_json = json.loads(response.text)
            itens = resposta_json.get('qna', [])

            # Mapeia para campos compatíveis com o Ragas, preservando metadados
            resultado = []
            for item in itens:
                resultado.append({
                    "user_input": item.get("pergunta_humana", ""),
                    "reference": item.get("resposta_esperada", ""),
                    "reference_contexts": [chunk],
                    "persona": item.get("persona", persona_alvo),
                    "tipo_pergunta": item.get("tipo_pergunta", ""),
                    "contexto_base": item.get("contexto_base", ""),
                })
            return resultado

        except Exception as e:
            print(f"  [Tentativa {tentativa}/{MAX_TENTATIVAS}] Erro na API: {e}")
            if tentativa < MAX_TENTATIVAS:
                espera = 2 ** tentativa
                print(f"  Aguardando {espera}s antes de tentar novamente...")
                time.sleep(espera)

    print("  Todas as tentativas falharam. Pulando este chunk.")
    return []


def main():
    arquivo_config = BASE_DIR / "manuais.json"

    try:
        with open(arquivo_config, 'r', encoding='utf-8') as f:
            tarefas = json.load(f)
    except Exception as e:
        print(f"ERRO ao ler {arquivo_config}: {e}")
        return

    pasta_saida = BASE_DIR / "dataset"
    pasta_saida.mkdir(exist_ok=True)

    qtd_links = len(tarefas)
    cotas = [
        meta_global // qtd_links + (1 if i < meta_global % qtd_links else 0)
        for i in range(qtd_links)
    ]

    print(f"Meta global: {meta_global} perguntas distribuídas em {qtd_links} manual(is).")
    print(f"Modelo configurado: {modelo_gemini}\n")

    for i, tarefa in enumerate(tarefas):
        cota = cotas[i]
        nome_livro = tarefa['livro']

        print(f"--- Processando: {nome_livro} | Cota: {cota} pergunta(s) ---")

        if cota == 0:
            print(" -> Cota zero para este manual. Pulando.")
            continue

        dataset_manual: list[dict] = []
        texto = extrair_texto_da_url(tarefa['url'])
        chunks = dividir_em_chunks(texto)
        faltam = cota

        for j, chunk in enumerate(chunks):
            if faltam <= 0:
                break
            if len(chunk) <= 100:
                continue

            if j > 0:
                time.sleep(DELAY_ENTRE_CHAMADAS)

            gerados = gerar_perguntas_com_ia(chunk, tarefa['persona'], faltam)
            dataset_manual.extend(gerados)
            faltam -= len(gerados)
            print(f" -> Geradas: {len(gerados)} | Faltam: {max(0, faltam)}")

        if dataset_manual:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            nome_arquivo = nome_livro.replace(" ", "_").lower()
            caminho = pasta_saida / f"{nome_arquivo}_{timestamp}.json"

            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(dataset_manual, f, ensure_ascii=False, indent=4)

            print(f"✅ Arquivo salvo: {caminho}\n")


if __name__ == "__main__":
    main()
