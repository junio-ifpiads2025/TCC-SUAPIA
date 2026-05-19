# Plano Mestre de Implementação — SUAPIA

> Este documento é o guia central. Cada épico tem seu próprio plano detalhado em `docs/planos/`.

---

## Stack Tecnológico

| Camada | Tecnologia |
|--------|-----------|
| Webhook / API | FastAPI |
| WhatsApp | WAHA (self-hosted) |
| Banco relacional | PostgreSQL 16 + pgvector |
| Cache / Sessão | Redis 7 |
| LLM | OpenAI (gpt-4o-mini) |
| Embeddings | OpenAI text-embedding-3-small |
| Reranking | Cohere rerank-v3 |
| Agente MCP | suap-mcp (local, `-e`) |
| Fila | Tabela PostgreSQL (FIFO por chat_id) |

---

## Estrutura de Módulos Alvo

```
chat-bot/
├── main.py                         # Entrypoint FastAPI + roteamento de pipeline
├── config.py                       # Variáveis de ambiente centralizadas
├── models/
│   └── database.py                 # SQLAlchemy: UserAuth, MessageQueue, ThreadHistory
├── services/
│   ├── auth_service.py             # Épico 1 — autenticação e sessão
│   ├── session_service.py          # Épico 1 — Redis (token TTL, rate limit)
│   ├── queue_service.py            # Épico 3 — enfileiramento e processamento
│   ├── rag_agent.py                # Épico 4 — RAG (já existe, ajustar)
│   ├── mcp_client.py               # Épico 5 — tools MCP SUAP (já existe, ajustar)
│   ├── agent_orchestrator.py       # Épicos 4+5 — orquestrador ReAct (já existe)
│   └── waha_client.py              # Épico 6 — envio outbound
├── routes/
│   └── webhook.py                  # Épico 3 — handler do webhook separado do main
├── web/
│   └── login.html                  # Épico 1 — interface de login SUAP
└── utils/
    └── security.py                 # Sanitização de logs, sem texto plano sensível
infra/
├── docker-compose.yml              # PostgreSQL + pgvector, Redis, WAHA
└── migrations/
    ├── 001_user_auth.sql
    ├── 002_message_queue.sql
    └── 003_thread_history.sql
```

---

## Schema de Banco de Dados (alto nível)

```sql
-- Épico 1
user_auth (id, chat_id UNIQUE, matricula, created_at, updated_at)

-- Épico 3
message_queue (
  id, chat_id, content, type,
  status ENUM(pending|processing|completed|failed),
  created_at, updated_at, error_detail
)
INDEX (status, created_at)

-- Épicos 4+6
thread_history (
  id, chat_id, role ENUM(user|assistant),
  content, created_at
)
```

Redis keys:
```
suap:token:{chat_id}          TTL = informado pela API (fallback 8h)
suap:rate:{chat_id}:{YYYYMMDD} TTL = até meia-noite BRT
suap:onboarding_link:{uuid}   TTL curto (ex: 15 min)
```

---

## Ordem de Implementação e Dependências

```
Fase 0 — Infraestrutura (Docker + Migrations) 
    └─► Fase 1 — Épico 1: Autenticação e Sessão
            └─► Fase 2 — Épico 3: Pipeline e Fila
                    ├─► Fase 3a — Épico 4: Agente RAG (parcialmente feito)
                    └─► Fase 3b — Épico 5: Agente MCP SUAP
                            └─► Fase 4 — Épico 2: Roteamento e UX
                                    └─► Fase 5 — Épico 6: Resposta Outbound
```

> Épicos 4 e 5 podem ser desenvolvidos em paralelo após a Fase 2.

---

## Planos Individuais

| Épico | Arquivo | Status |
|-------|---------|--------|
| Infra (DB + Docker) | [planos/epico0_infra.md](planos/epico0_infra.md) | pendente |
| Épico 1 — Autenticação | [planos/epico1_autenticacao.md](planos/epico1_autenticacao.md) | pendente |
| Épico 2 — UX e Roteamento | [planos/epico2_ux.md](planos/epico2_ux.md) | pendente |
| Épico 3 — Pipeline e Fila | [planos/epico3_pipeline.md](planos/epico3_pipeline.md) | pendente |
| Épico 4 — Agente RAG (parcialmente ou quase todo implementado) | [planos/epico4_rag.md](planos/epico4_rag.md) | pendente |
| Épico 5 — Agente MCP SUAP | [planos/epico5_mcp_suap.md](planos/epico5_mcp_suap.md) | pendente |
| Épico 6 — Resposta Outbound | [planos/epico6_resposta.md](planos/epico6_resposta.md) | pendente |

---

## Convenções do Projeto

- **Segurança:** Token SUAP, senha e CPF jamais em logs ou texto plano (RN03, RNF02). Toda saída sensível passa por `utils/security.py`.
- **Logs:** JSON estruturado com nível configurável via `LOG_LEVEL` (DEBUG/INFO/ERROR) (RNF03).
- **Configuração:** Toda variável de ambiente centralizada em `config.py`. Sem hardcode.
- **Erros ao usuário:** Sempre mensagem amigável, sem stack trace (RF07, RN04).
- **Processamento:** FIFO por `chat_id`; `chat_id`s distintos em paralelo (RN08).
- **Rate limit:** 25 mensagens/dia por conta, contador em Redis com reset meia-noite BRT (RN06).
- **Mensageria:** As rotas importam exclusivamente de `services/messaging_client.py` — nunca do provider diretamente. O contrato expõe `enviar_texto`, `enviar_imagem` e `enviar_texto_async`. Comportamentos específicos de provider (ex: anti-ban do WAHA, RN14) vivem no módulo do provider e são invisíveis para o restante da aplicação.
