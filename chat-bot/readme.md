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
      ├─► [não autenticado] auth_service → gera link UUID → messaging_client → WhatsApp
      │         GET  /auth/login?token={uuid} → login.html
      │         POST /auth/login?token={uuid} → valida SUAP → token no Redis
      │                                       → messaging_client → notifica resultado
      │
      └─► [autenticado] pipeline IA (background task)
                │
                ├─► advanced_rag_agent  (manuais / pgvector)
                └─► agent_orchestrator  (MCP SUAP tools)
                          │
                          ▼
                   messaging_client → provider (waha_client) → WhatsApp
```

---

## Contrato de Mensageria

Todo envio de mensagem passa por **`services/messaging_client.py`**. As rotas nunca importam `waha_client` diretamente.

O contrato define 3 funções que qualquer provider deve implementar:

| Função | Tipo | Uso |
|--------|------|-----|
| `enviar_texto(chat_id, texto)` | síncrono | respostas da IA, avisos de limite, link de login |
| `enviar_imagem(chat_id, url)` | síncrono | imagens dos manuais |
| `enviar_texto_async(chat_id, texto)` | assíncrono | notificações de login (BackgroundTasks) |

**Para trocar de provider:**
1. Crie `services/<provider>_client.py` implementando as 3 funções acima com exatamente essa assinatura.
2. Atualize os imports em `services/messaging_client.py`.
3. Nenhuma rota precisa ser alterada.

---

## Estrutura de Arquivos

```
chat-bot/
├── main.py                         # FastAPI: monta rotas e lifespan
├── config.py                       # Todas as variáveis de ambiente centralizadas
├── requirements.txt
├── .env                            # Não versionado
├── web/
│   └── login.html                  # Página de login (HTML puro)
├── models/
│   └── database.py                 # SQLAlchemy async: UserAuth
├── routes/
│   ├── webhook.py                  # POST /webhook — recebe eventos WAHA
│   └── auth.py                     # GET/POST /auth/login — fluxo de autenticação web
├── services/
│   ├── messaging_client.py         # ★ Abstração de mensageria (único ponto de import)
│   ├── waha_client.py              # Implementação WAHA (provider atual)
│   ├── auth_service.py             # Autenticação SUAP, vínculo chat_id → matrícula
│   ├── session_service.py          # Redis: token TTL, rate limit, link UUID
│   ├── rag_agent.py                # RAG simples
│   ├── advanced_rag_agent.py       # Advanced RAG + CRAG
│   ├── agent_orchestrator.py       # Orquestrador ReAct (tool_calling loop)
│   ├── mcp_client.py               # Wrapper suap_api com ferramentas OpenAI
│   └── logger.py                   # Logger estruturado
└── utils/
    └── security.py                 # Sanitização de logs (remove token, senha, CPF)
```

---

## Fluxo de Autenticação

O link enviado ao aluno **nunca contém o número de telefone ou matrícula** — apenas um UUID de uso único:

```
1. Aluno envia mensagem sem vínculo
2. Sistema gera UUID → Redis: suap:onboarding_link:{uuid} = chat_id  (TTL: 15 min)
3. messaging_client envia ao aluno: https://dominio/auth/login?token={uuid}
4. Aluno preenche matrícula + senha → POST /auth/login?token={uuid}
5. Backend valida UUID → autentica no SUAP → token no Redis (TTL retornado pela API)
6. Vínculo chat_id → matrícula persistido em user_auth (PostgreSQL)
7. messaging_client notifica o resultado no WhatsApp (sucesso ou erro)
```

---

## Pipeline de Mensagens

- Webhook retorna `200 OK` imediatamente; processamento ocorre em background (RNF01).
- Limite: **25 mensagens/dia** por conta — contador no Redis, reset meia-noite BRT.

---

## Agentes de IA

| Modo | Variável | Descrição |
|------|----------|-----------|
| Agente ReAct | `USE_AGENT=true` | MCP SUAP + RAG combinados via tool_calling |
| Advanced RAG | `USE_ADVANCED_RAG=true` | Reescrita de query + multi-query + Cohere reranking |
| CRAG | `USE_CRAG=true` | Relevância condicional com fallback |
| RAG simples | _(padrão)_ | Busca vetorial direta + geração |

---

## Pré-requisitos

- Python 3.12+
- PostgreSQL 16 com extensão **pgvector**
- **Redis** 7
- **WAHA** (via `docker compose up -d`)
- Chave de API OpenAI e Cohere

---

## Instalação e Execução

```bash
cd chat-bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # configure as variáveis
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

---

## Variáveis de Ambiente

### Conexões

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `OPENAI_API_KEY` | — | Chave da OpenAI |
| `COHERE_API_KEY` | — | Chave do Cohere (reranking) |
| `WAHA_BASE_URL` | `http://localhost:3000` | URL base do WAHA |
| `PGVECTOR_CONNECTION_STRING` | `postgresql+psycopg://...` | PostgreSQL (RAG) |
| `REDIS_URL` | `redis://localhost:6379` | Redis |
| `SUAP_BASE_URL` | `https://suap.ifpi.edu.br` | URL base da API do SUAP |
| `APP_BASE_URL` | `http://localhost:8002` | URL pública deste serviço |

### Comportamento

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `USE_AGENT` | `false` | Ativa o Agente ReAct |
| `USE_ADVANCED_RAG` | `false` | Ativa o Advanced RAG |
| `USE_CRAG` | `false` | Ativa o CRAG |
| `RESPONDER_QUALQUER_NUMERO` | `False` | Se `True`, responde qualquer número |
| `NUMEROS_PERMITIDOS` | — | Lista separada por vírgula |
| `MAX_DAILY_MESSAGES` | `25` | Limite diário de mensagens por aluno |
| `SESSION_TTL_SECONDS` | `28800` | TTL do token de sessão (8h) |
| `AGENT_MAX_ITERATIONS` | `5` | Iterações máximas do loop ReAct |

### Pipeline RAG avançado

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `MODELO_LLM` | `gpt-4o-mini` | Modelo principal |
| `MODELO_LLM_RAPIDO` | `gpt-4o-mini` | Modelo para passos rápidos |
| `MODELO_LLM_AVANCADO` | `gpt-4o` | Modelo para geração final |
| `MODELO_EMBEDDING` | `text-embedding-3-small` | Modelo de embeddings |
| `RERANKER_MODEL` | `rerank-multilingual-v3.0` | Modelo Cohere para reranking |
| `RETRIEVAL_TOP_K` | `5` | Documentos recuperados |
| `RERANKER_TOP_K` | `5` | Documentos após reranking |
| `CRAG_SCORE_THRESHOLD` | `0.4` | Limiar de relevância CRAG |

---

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `POST` | `/webhook` | Recebe eventos do WAHA |
| `GET` | `/auth/login?token={uuid}` | Renderiza página de login |
| `POST` | `/auth/login?token={uuid}` | Processa credenciais e autentica no SUAP |

---

## Segurança

- Link de login contém apenas UUID temporário — sem número de telefone ou matrícula na URL.
- Token SUAP e senha nunca aparecem em logs ou em texto plano no banco (RN03, RNF02).
- `utils/security.py` sanitiza todos os dicts antes de logar.
