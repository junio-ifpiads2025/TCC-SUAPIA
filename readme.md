# SUAPIA - Assistente Virtual RAG para o SUAP (IFPI)

Sistema de Inteligência Artificial baseado em **RAG (Retrieval-Augmented Generation)** desenvolvido para atuar como assistente virtual integrado ao WhatsApp. O objetivo é responder dúvidas e fornecer orientações sobre os manuais do sistema SUAP do IFPI.

## Visão Geral da Arquitetura

O projeto é dividido em pipelines de dados em **CLI** (extração, ingestão, geração de Q&A e avaliação), um chatbot em **FastAPI** e serviços de infraestrutura em **Docker**:

```
TCC-SUAPIA/
├── Makefile                   # Atalhos para todas as pipelines (make help)
├── dockercompose.yml          # Infraestrutura Docker (WAHA + pgvector)
├── pipeline/manualsExtraction/links.json  # URLs dos manuais do SUAP
├── chat-bot/                  # Webhook RAG para WhatsApp (porta 8002)
└── pipeline/
    ├── manualsExtraction/     # CLI de extração de HTML -> .md
    ├── manualsIngestion-RAG/  # CLI de vetorização e ingestão (.md -> pgvector)
    ├── q&a-generator/         # Gerador de datasets sintéticos para avaliação
    └── evaluation/            # Avaliação do RAG (RAGAS)
```

### Fluxo de Dados

**Pipeline de Ingestão:**
```
links.json → manualsExtraction (CLI, gera .md) → manualsIngestion-RAG (CLI) → PostgreSQL pgvector
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

## 2. Extração dos Manuais (`pipeline/manualsExtraction`)

CLI que baixa o export HTML dos manuais do SUAP e gera **um `.md` por página** em `pipeline/manualsExtraction/output/<data_hora>/<manual>/...`.

Veja o [README do manualsExtraction](./pipeline/manualsExtraction/readme.md).

```bash
make install-extraction
make extract-links                       # usa links.json (ou LINKS_JSON=outro.json)
make extract URLS='https://... https://...'

# sem Makefile (a partir da raiz)
python -m pipeline.manualsExtraction links-json pipeline/manualsExtraction/links.json
python -m pipeline.manualsExtraction lote URL [URL ...]
```

---

## 3. Ingestão Vetorial (`pipeline/manualsIngestion-RAG`)

CLI que lê os `.md` da extração, divide em chunks, gera embeddings via OpenAI e grava no PostgreSQL pgvector. É idempotente: reenviar um manual substitui seus chunks.

Veja o [README do manualsIngestion-RAG](./pipeline/manualsIngestion-RAG/readme.md). Requer `pipeline/manualsIngestion-RAG/.env` (use o `.env.example`).

```bash
make install-ingestion
make db-up                               # sobe o pgvector
make ingest                              # ingere a extração mais recente
make ingest SRC=pipeline/manualsExtraction/output/<data_hora>   # pasta ou .json específico
make db-count                            # chunks por coleção
make ingest-reset                        # apaga a coleção (pede confirmação)

# sem Makefile (a partir da raiz)
python pipeline/manualsIngestion-RAG [CAMINHO]
```

---

## 4. Chatbot RAG (`chat-bot`)

Webhook que recebe mensagens do WhatsApp via WAHA, faz busca semântica no pgvector e gera respostas com a LLM da OpenAI.

Veja o [README do chat-bot](./chat-bot/readme.md) para instruções detalhadas.

**Execução rápida:**
```bash
make chatbot-install
make chatbot-dev                         # ou chatbot-prod

# sem Makefile
cd chat-bot
pip install -r requirements.txt
uvicorn main:app --reload --port 8002
```

---

## 5. Gerador de Q&A e Avaliação (`pipeline/q&a-generator`, `pipeline/evaluation`)

Utilitário para geração de datasets sintéticos de perguntas e respostas usando o Google Gemini, utilizado para avaliar a qualidade do RAG com o framework Ragas.

Veja o [README do q&a-generator](./pipeline/q&a-generator/readme.md) para instruções detalhadas.

```bash
make install-qa install-eval
make qa-generate                         # gera dataset sintético (Gemini)
make eval                                # roda RAGAS sobre o dataset mais recente
```

---

## Stack Tecnológica

| Camada | Tecnologia |
|---|---|
| Chatbot (web) | FastAPI + Uvicorn |
| Pipelines | CLIs Python (argparse) + Makefile |
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

```bash
make install-all                         # venvs de todas as pipelines
make chatbot-install
make db-up                               # 1. pgvector
make extract-links                       # 2. links.json -> .md
make ingest                              # 3. .md -> pgvector
docker compose up -d                     # 4. WAHA (WhatsApp)
make chatbot-dev                         # 5. chatbot na porta 8002
```

Depois, opcionalmente: `make qa-generate` e `make eval` para avaliar o RAG. Veja todos os alvos com `make help`.
