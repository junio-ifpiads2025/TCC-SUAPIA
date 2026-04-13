# SUAPIA - Assistente Virtual RAG para o SUAP (IFPI)

Sistema de Inteligência Artificial baseado em **RAG (Retrieval-Augmented Generation)** desenvolvido para atuar como assistente virtual integrado ao WhatsApp. O objetivo é responder dúvidas e fornecer orientações sobre os manuais do sistema SUAP do IFPI.

## Visão Geral da Arquitetura

O projeto é dividido em microsserviços independentes construídos com **FastAPI** e serviços de infraestrutura em **Docker**:

```
TCC-SUAPIA/
├── dockercompose.yml          # Infraestrutura Docker (WAHA)
├── links.json                 # URLs dos manuais do SUAP
├── manualsExtraction/         # Serviço de extração de HTML (porta 8000)
├── manualsIngestion-RAG/      # Serviço de vetorização e ingestão (porta 8001)
├── chat-bot/                  # Webhook RAG para WhatsApp (porta 8002)
└── q&a-generator/             # Gerador de datasets sintéticos para avaliação
```

### Fluxo de Dados

**Pipeline de Ingestão:**
```
links.json → manualsExtraction (porta 8000) → manualsIngestion-RAG (porta 8001) → PostgreSQL pgvector
```

**Pipeline de Resposta:**
```
WhatsApp → WAHA (Docker) → chat-bot webhook (porta 8002) → pgvector + OpenAI → WhatsApp
```

---

## Pré-requisitos

- Docker e Docker Compose
- Python 3.10+
- Chave de API da OpenAI
- PostgreSQL com a extensão **pgvector** instalada

---

## 1. Infraestrutura Base (Docker)

O arquivo `dockercompose.yml` sobe o **WAHA**, motor de integração com o WhatsApp:

```bash
docker compose up -d
```

- **WAHA (WhatsApp API):** `http://localhost:3000`

> **Banco de vetores (pgvector):** O projeto utiliza PostgreSQL com a extensão pgvector. Certifique-se de que uma instância do PostgreSQL com pgvector está rodando e acessível antes de iniciar os microsserviços de ingestão e chatbot.

### Configurando o WhatsApp (WAHA)

1. Acesse o painel do WAHA: `http://localhost:3000/dashboard`
2. Inicie uma nova sessão (ex: `default`)
3. Escaneie o QR Code com o número que será o bot
4. O webhook já está configurado no `dockercompose.yml` para apontar para `http://host.docker.internal:8002/webhook`

---

## 2. Extração dos Manuais (`manualsExtraction`)

Faz o download e o parsing inteligente do HTML dos manuais do SUAP, extraindo tópicos, textos e links de imagens.

Veja o [README do manualsExtraction](./manualsExtraction/README.md) para instruções detalhadas.

**Execução rápida:**
```bash
cd manualsExtraction
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

---

## 3. Ingestão Vetorial (`manualsIngestion-RAG`)

Recebe os dados extraídos, gera embeddings via OpenAI e armazena os vetores no PostgreSQL pgvector.

Veja o [README do manualsIngestion-RAG](./manualsIngestion-RAG/README.md) para instruções detalhadas.

**Execução rápida:**
```bash
cd manualsIngestion-RAG
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

---

## 4. Chatbot RAG (`chat-bot`)

Webhook que recebe mensagens do WhatsApp via WAHA, faz busca semântica no pgvector e gera respostas com a LLM da OpenAI.

Veja o [README do chat-bot](./chat-bot/README.md) para instruções detalhadas.

**Execução rápida:**
```bash
cd chat-bot
pip install -r requirements.txt
uvicorn main:app --reload --port 8002
```

---

## 5. Gerador de Q&A (`q&a-generator`)

Utilitário para geração de datasets sintéticos de perguntas e respostas usando o Google Gemini, utilizado para avaliar a qualidade do RAG com o framework Ragas.

Veja o [README do q&a-generator](./q&a-generator/README.md) para instruções detalhadas.

---

## Stack Tecnológica

| Camada | Tecnologia |
|---|---|
| Framework Web | FastAPI + Uvicorn |
| LLM | OpenAI GPT (configurável) |
| Embeddings | OpenAI text-embedding-3-small |
| Banco Vetorial | PostgreSQL + pgvector |
| RAG Orchestration | LangChain |
| WhatsApp Bridge | WAHA (via Docker) |
| Geração Sintética | Google Gemini |
| Avaliação RAG | Ragas |
| HTML Parsing | BeautifulSoup4 + HTTPX |
| Containerização | Docker / Docker Compose |

---

## Ordem de Inicialização Recomendada

1. `docker compose up -d` — sobe o WAHA
2. Garanta que o PostgreSQL com pgvector está rodando
3. `uvicorn app.main:app --reload --port 8000` — inicia a Extração
4. `uvicorn app.main:app --reload --port 8001` — inicia a Ingestão
5. Execute o pipeline de ingestão para popular o banco vetorial
6. `uvicorn main:app --reload --port 8002` — inicia o Chatbot
