# SUAPIA: Gerador de Dataset Sintético (Q&A) para Avaliação RAG

Este repositório contém o script de automação para a criação do *Golden Dataset* do projeto SUAPIA. A sua função principal é **gerar um conjunto de dados de perguntas e respostas para validar o Chatbot RAG utilizando o framework [Ragas](https://docs.ragas.io/)**, eliminando a necessidade de testes humanos extensivos e manuais.

O script realiza o *web scraping* dos manuais oficiais do SUAP em HTML e utiliza os modelos do **Google Gemini** para gerar perguntas e respostas orgânicas. Ele simula as dores e dúvidas reais de diferentes perfis de usuários (Alunos, Professores, Coordenadores) para testar o sistema em cenários próximos ao uso real.

## Funcionalidades

* **Otimizado para o Ragas:** Formata os dados de saída como uma **lista plana de objetos JSON** com campos compatíveis (`user_input`, `reference`, `reference_contexts`), prontos para carregar via HuggingFace Datasets.
* **Web Scraping Automatizado:** Extrai conteúdo textual diretamente das URLs dos manuais do IFPI utilizando `BeautifulSoup`.
* **Chunking Inteligente:** Divide textos longos de forma lógica para respeitar os limites de contexto da LLM durante a geração das perguntas.
* **Injeção de Personas Dinâmica:** Gera perguntas baseadas no perfil do usuário alvo (ex: aluno calouro informal), tornando as requisições sintéticas mais realistas e desafiadoras para o RAG.
* **Modelo Configurável:** Permite alternar facilmente entre diferentes modelos do Gemini (ex: Flash, Pro) diretamente pelo arquivo `.env`.
* **Retry com Backoff Exponencial:** Reage automaticamente a falhas de rede ou rate limits da API, com até 3 tentativas por chunk.

## Pré-requisitos

* **Python 3.10+** instalado.
* Uma chave de API válida do **Google Gemini** (Google AI Studio).

## Instalação e Configuração

**1. Navegue até a pasta do módulo e crie o ambiente virtual (opcional, mas recomendado):**

```bash
cd q&a-generator
python -m venv venv
# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

**2. Instale as dependências:**

```bash
pip install -r requirements.txt
```

**3. Configure as variáveis de ambiente:**

Renomeie ou copie o arquivo `.env.example` para `.env` e preencha as informações:

```env
GEMINI_API_KEY=sua_chave_api_do_google_aqui
PROMPT_SYSTEM="Você é um assistente encarregado de gerar {qtd_perguntas} perguntas no formato JSON simulando a persona: {persona_alvo}..."
GEMINI_MODEL=gemini-2.5-flash
QTD_PERGUNTAS=10
```

> Você pode alterar `GEMINI_MODEL` para `gemini-2.5-pro` para testar um modelo com maior capacidade de raciocínio.  
> `QTD_PERGUNTAS` define a meta global de perguntas, distribuída igualmente entre todos os manuais.

**4. Configure as fontes (URLs e Personas):**

Edite o arquivo `manuais.json` com os manuais que você deseja processar:

```json
[
  {
    "livro": "Restaurante Institucional",
    "url": "https://manuais.ifpi.edu.br/books/restaurante-institucional-ifpi/export/html",
    "persona": "Aluno Calouro (informal, usa gírias como 'tô', 'oq', está confuso com o sistema)"
  }
]
```

## Como Usar

Com as dependências instaladas e o `.env` configurado, execute o script principal:

```bash
python main.py
```

## Formato de Saída

Cada arquivo gerado em `dataset/` é uma lista JSON plana compatível com o Ragas:

```json
[
  {
    "user_input": "Como faço para reservar uma refeição?",
    "reference": "Acesse ATIVIDADES ESTUDANTIS > Refeições e clique em Reservar.",
    "reference_contexts": ["Trecho do manual usado para gerar esta pergunta..."],
    "persona": "Aluno Calouro",
    "tipo_pergunta": "Procedimental",
    "contexto_base": "Descrição resumida do contexto"
  }
]
```

Os campos `user_input`, `reference` e `reference_contexts` são os exigidos pelo Ragas para calcular métricas como *faithfulness* e *context_precision*.
