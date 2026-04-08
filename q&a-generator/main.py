import json
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# 1. Configuração da API
client = OpenAI(api_key="sk-SUA_CHAVE_AQUI")

# 2. Configuração dos Links amarrados com Personas
# Agora você define exatamente QUEM está lendo aquele manual
tarefas_geracao = [
    {
        "livro": "Restaurante Institucional",
        "url": "https://manuais.ifpi.edu.br/books/restaurante-institucional-ifpi/export/html",
        "persona": "Aluno Calouro (informal, usa gírias como 'tô', 'oq', está confuso com o sistema e muitas vezes conta uma historinha de que não conseguiu almoçar)"
    },
    {
        "livro": "Acesso ao SUAP",
        "url": "https://manuais.ifpi.edu.br/books/acesso-ao-suap/export/html",
        "persona": "Professor recém-contratado (formal, apressado, irritado porque precisa lançar notas e não sabe a senha padrão)"
    }
]

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

def gerar_perguntas_com_ia(chunk_de_texto, persona_alvo):
    """Agora a função recebe a persona e injeta no prompt dinamicamente"""
    
    # O prompt agora é focado 100% na persona que você passou
    prompt_sistema = f"""
Você é um gerador de dados sintéticos para o assistente virtual 'SUAPIA' do IFPI.
Sua tarefa é gerar 3 interações simuladas baseadas estritamente no texto fornecido.

REGRA DE PERSONA OBRIGATÓRIA:
Você DEVE assumir o seguinte perfil para formular a pergunta humana: "{persona_alvo}".
A pergunta deve refletir a dor, o tom de voz e o contexto dessa persona específica.

Diretrizes:
1. Tipos: Misture perguntas Factuais (regras) e Procedimentais (passo a passo).
2. Retorne uma lista vazia se o texto não contiver informações úteis para gerar dúvidas.

Formato JSON estrito:
{{
  "qna": [
    {{
      "persona": "{persona_alvo}",
      "contexto_base": "...",
      "pergunta_humana": "...",
      "resposta_esperada": "...",
      "tipo_pergunta": "..."
    }}
  ]
}}
"""
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            temperature=0.7,
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Trecho do manual:\n\n{chunk_de_texto}"}
            ]
        )
        resposta_json = json.loads(completion.choices[0].message.content)
        return resposta_json.get('qna', [])
    except Exception as e:
        print(f"Erro na API: {e}")
        return []

def main():
    dataset_final = []
    
    # O loop agora itera sobre as tarefas definidas, passando a persona certa
    for tarefa in tarefas_geracao:
        print(f"\n--- Processando o manual: {tarefa['livro']} com a Persona: {tarefa['persona']} ---")
        
        texto_completo = extrair_texto_da_url(tarefa['url'])
        chunks = dividir_em_chunks(texto_completo)
        
        for i, chunk in enumerate(chunks):
            if len(chunk) > 100:
                # Injetamos a persona amarrada à URL diretamente na função
                perguntas_geradas = gerar_perguntas_com_ia(chunk, tarefa['persona'])
                dataset_final.extend(perguntas_geradas)
                print(f" -> Lote {i+1}: {len(perguntas_geradas)} perguntas geradas.")
    
    with open("dataset_suapia_personas.json", 'w', encoding='utf-8') as f:
        json.dump(dataset_final, f, ensure_ascii=False, indent=4)
        
    print(f"\nFinalizado! {len(dataset_final)} perguntas salvas em 'dataset_suapia_personas.json'.")

if __name__ == "__main__":
    main()