# chat-bot — Webhook RAG para WhatsApp

Microsserviço responsável por receber mensagens do WhatsApp via **WAHA**, executar a busca semântica no banco vetorial **pgvector** e retornar respostas geradas pela **OpenAI**, incluindo imagens relevantes dos manuais.

Porta padrão: **8002**

---

## Responsabilidades

1. Expõe o endpoint `POST /webhook` que recebe eventos do WAHA.
2. Filtra mensagens por número de telefone (lista de permissões configurável).
3. Executa o pipeline RAG em background:
   - Busca semântica nos vetores armazenados no PostgreSQL pgvector.
   - Gera resposta de texto com a LLM da OpenAI.
   - Envia a resposta de texto ao usuário via WAHA.
   - Envia as imagens associadas ao contexto recuperado via WAHA.

---

## Estrutura

```
chat-bot/
├── main.py                  # Aplicação FastAPI e orquestrador do fluxo
├── config.py                # Leitura de variáveis de ambiente e controle de acesso
├── requirements.txt         # Dependências Python
├── .env                     # Variáveis de ambiente (não versionado)
└── services/
    ├── rag_agent.py         # Lógica RAG: busca no pgvector + geração com OpenAI
    └── waha_client.py       # Cliente HTTP para envio de texto e imagens via WAHA
```

---

## Pré-requisitos

- Python 3.10+
- PostgreSQL com a extensão **pgvector** instalada e populada pelo `manualsIngestion-RAG`
- **WAHA** rodando (via `docker compose up -d` na raiz do projeto)
- Chave de API da OpenAI

---

## Instalação e Execução

```bash
cd chat-bot

# Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt

# Configure as variáveis de ambiente
cp .env.example .env  # edite o arquivo .env com suas credenciais

# Inicie o servidor
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

---

## Variáveis de Ambiente (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `OPENAI_API_KEY` | — | Chave de API da OpenAI |
| `WAHA_BASE_URL` | `http://localhost:3000` | URL base do WAHA |
| `PGVECTOR_CONNECTION_STRING` | `postgresql+psycopg://admin:adminpassword@localhost:5432/vetordatabase` | String de conexão com o PostgreSQL |
| `PGVECTOR_COLLECTION` | `manuais_suap_ifpi` | Nome da coleção de vetores |
| `MODELO_LLM` | `gpt-3.5-turbo` | Modelo da OpenAI para geração de resposta |
| `MODELO_EMBEDDING` | `text-embedding-3-small` | Modelo de embeddings da OpenAI |
| `TEMPERATURE` | `0.3` | Temperatura de geração da LLM (0.0 a 1.0) |
| `SYSTEM_PROMPT` | _(prompt padrão do SUAP)_ | Instrução de sistema enviada à LLM |
| `RESPONDER_QUALQUER_NUMERO` | `False` | Se `True`, responde a qualquer número |
| `NUMEROS_PERMITIDOS` | — | Lista de números autorizados, separados por vírgula (ex: `5511999887766@c.us,5511888776655@c.us`) |

---

## Fluxo de Processamento

```
WhatsApp (usuário)
      │
      ▼
   WAHA (Docker)
      │  POST /webhook
      ▼
   main.py
      │  BackgroundTask
      ▼
   rag_agent.py ──► pgvector (busca semântica, k=3)
      │
      ▼
   OpenAI API (geração de resposta)
      │
      ▼
   waha_client.py ──► /api/sendText  (resposta de texto)
                  └──► /api/sendImage (imagens do contexto)
      │
      ▼
WhatsApp (usuário)
```

---

## Endpoint

### `POST /webhook`

Recebe eventos do WAHA. O processamento ocorre em background para que o WAHA receba o `200 OK` imediatamente, sem timeout.

**Payload esperado (WAHA):**
```json
{
  "event": "message",
  "payload": {
    "body": "Como faço para lançar notas no SUAP?",
    "from": "5586999887766@c.us",
    "fromMe": false
  }
}
```

**Resposta:**
```json
{ "status": "ok" }
```

---

## Controle de Acesso

- Se `RESPONDER_QUALQUER_NUMERO=True`, o bot responde a qualquer número que enviar mensagem.
- Se `False`, apenas os números listados em `NUMEROS_PERMITIDOS` recebem resposta. Útil durante desenvolvimento e testes.
