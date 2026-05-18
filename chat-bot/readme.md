# chat-bot — SUAPIA Webhook

Microsserviço principal do SUAPIA. Recebe mensagens do WhatsApp via **WAHA**, autentica o aluno no **SUAP**, gerencia sessão/fila e retorna respostas geradas por IA — combinando busca semântica nos manuais (RAG) e consulta de dados acadêmicos pessoais (MCP SUAP).

Porta padrão: **8002**

---

## Arquitetura Geral

```
WhatsApp (aluno)
      │
      ▼
   WAHA (Docker) ──► POST /webhook
      │
      ▼
   main.py  (FastAPI)
      │
      ├─► [não autenticado] auth_service → gera link UUID → WAHA envia ao aluno
      │         GET /login?token={uuid} → login.html (Jinja2)
      │         POST /auth/login        → valida SUAP → token no Redis
      │
      └─► [autenticado] queue_service → message_queue (PostgreSQL)
                │
                ▼
          worker assíncrono
                │
                ├─► message_router → classify
                │         ├─► rag_agent    (manuais / pgvector)
                │         └─► agent_orchestrator (MCP SUAP tools)
                │
                └─► waha_client → /api/sendText → WhatsApp (aluno)
                    history_service → thread_history (PostgreSQL)
```

---

## Estrutura de Arquivos

```
chat-bot/
├── main.py                         # FastAPI: webhook, rota de login, lifespan worker
├── config.py                       # Todas as variáveis de ambiente centralizadas
├── requirements.txt
├── .env                            # Não versionado
├── web/
│   └── login.html                  # Página de login (servida via Jinja2Templates)
├── models/
│   └── database.py                 # SQLAlchemy async: UserAuth, MessageQueue, ThreadHistory
├── routes/
│   └── webhook.py                  # Handler POST /webhook separado do main
├── services/
│   ├── auth_service.py             # Autenticação SUAP, vínculo chat_id → matrícula
│   ├── session_service.py          # Redis: token TTL, rate limit, link UUID
│   ├── queue_service.py            # Fila FIFO por chat_id, worker, limpeza de stale
│   ├── message_router.py           # Classificação RAG / MCP SUAP / ambos
│   ├── history_service.py          # thread_history: leitura e gravação de contexto
│   ├── rag_agent.py                # RAG simples
│   ├── advanced_rag_agent.py       # Advanced RAG + CRAG
│   ├── agent_orchestrator.py       # Orquestrador ReAct (tool_calling loop)
│   ├── mcp_client.py               # Wrapper suap_api com 10 ferramentas OpenAI
│   ├── waha_client.py              # Envio de texto e imagens via WAHA
│   └── logger.py                   # Logger estruturado (JSON)
└── utils/
    └── security.py                 # Sanitização de logs (remove token, senha, CPF)
```

---

## Fluxo de Autenticação (Épico 1)

O link enviado ao aluno **nunca contém o número de telefone ou matrícula**. Ele carrega apenas um UUID de uso único gerado pelo servidor:

```
1. Aluno envia mensagem sem vínculo
2. Sistema gera UUID → armazena Redis:  suap:onboarding_link:{uuid} = chat_id  (TTL: 15 min)
3. WAHA envia ao aluno:  https://dominio/login?token={uuid}
4. Aluno abre o link → FastAPI renderiza login.html via Jinja2Templates
5. Aluno preenche matrícula + senha → POST /auth/login?token={uuid}
6. Backend valida UUID no Redis → obtém chat_id → autentica no SUAP
7. Token SUAP salvo no Redis:  suap:token:{chat_id}  (TTL = retornado pela API, fallback 8h)
8. Vínculo chat_id → matrícula persistido em user_auth (PostgreSQL)
```

O UUID é descartado após uso ou expiração. Tokens SUAP nunca são gravados em texto plano no banco.

---

## Pipeline de Mensagens (Épico 3)

- Webhook retorna `200 OK` imediatamente; processamento ocorre em background (RNF01).
- Fila FIFO por `chat_id` na tabela `message_queue` (PostgreSQL).
- Usuários distintos são processados em paralelo.
- Limite: **25 mensagens/dia** por conta — contador no Redis, reset meia-noite BRT.
- Mensagens em `processing` há mais de `QUEUE_TIMEOUT_MINUTES` são marcadas como `failed`.

---

## Agentes de IA

| Modo | Variável | Descrição |
|------|----------|-----------|
| Agente ReAct | `USE_AGENT=true` | MCP SUAP + RAG combinados via tool_calling (padrão do projeto) |
| Advanced RAG | `USE_ADVANCED_RAG=true` | Reescrita de query + multi-query + Cohere reranking |
| CRAG | `USE_CRAG=true` | Relevância condicional com fallback |
| RAG simples | _(padrão)_ | Busca vetorial direta + geração |

---

## Frontend (Página de Login)

Servida pelo próprio FastAPI via **Jinja2Templates**:

```python
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="web")

@app.get("/login")
async def login_page(request: Request, token: str):
    return templates.TemplateResponse("login.html", {"request": request, "token": token})
```

Sem framework JavaScript — HTML puro com validação client-side e POST ao backend.

---

## Pré-requisitos

- Python 3.12+
- PostgreSQL 16 com extensão **pgvector**
- **Redis** 7
- **WAHA** (via `docker compose up -d`)
- Chave de API OpenAI e Cohere
- `suap-mcp` instalado localmente: `pip install -e /caminho/para/suap-mcp`

---

## Instalação e Execução

```bash
cd chat-bot

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env  # configure as variáveis

uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

---

## Variáveis de Ambiente (`.env`)

### Conexões

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `OPENAI_API_KEY` | — | Chave da OpenAI |
| `COHERE_API_KEY` | — | Chave do Cohere (reranking) |
| `WAHA_BASE_URL` | `http://localhost:3000` | URL base do WAHA |
| `WAHA_API_KEY` | — | Token de autenticação do WAHA |
| `PGVECTOR_CONNECTION_STRING` | `postgresql+psycopg://...` | PostgreSQL (síncrono, RAG) |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL (assíncrono, fila/auth) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `SUAP_BASE_URL` | `https://suap.ifpi.edu.br` | URL base da API do SUAP |

### Comportamento

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `USE_AGENT` | `false` | Ativa o Agente ReAct |
| `USE_ADVANCED_RAG` | `false` | Ativa o Advanced RAG |
| `USE_CRAG` | `false` | Ativa o CRAG |
| `RESPONDER_QUALQUER_NUMERO` | `False` | Se `True`, responde qualquer número |
| `NUMEROS_PERMITIDOS` | — | Lista separada por vírgula |
| `LOG_LEVEL` | `INFO` | Nível de log: `DEBUG`, `INFO`, `ERROR` |

### Limites e Thresholds

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `SIMILARITY_THRESHOLD` | `0.75` | Limiar mínimo de similaridade no RAG (RN09) |
| `MAX_HISTORY_MESSAGES` | `10` | Mensagens de histórico carregadas por interação (RN10) |
| `RATE_LIMIT_PER_DAY` | `25` | Limite diário de mensagens por aluno (RN06) |
| `QUEUE_TIMEOUT_MINUTES` | `2` | Timeout para mensagens presas em `processing` (RN07) |
| `ONBOARDING_LINK_TTL` | `900` | Validade do link de login em segundos (15 min) |
| `AGENT_MAX_ITERATIONS` | `5` | Iterações máximas do loop ReAct |

---

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `POST` | `/webhook` | Recebe eventos do WAHA |
| `GET` | `/login?token={uuid}` | Renderiza página de login (Jinja2) |
| `POST` | `/auth/login?token={uuid}` | Processa credenciais e autentica no SUAP |

---

## Segurança

- Link de login contém apenas UUID temporário — sem número de telefone, matrícula ou qualquer dado do aluno na URL.
- Token SUAP, senha e CPF nunca aparecem em logs ou texto plano no banco (RN03, RNF02).
- `utils/security.py` sanitiza todos os dicts antes de logar.
- Origem do webhook validada por IP allowlist ou assinatura WAHA (RN05).
