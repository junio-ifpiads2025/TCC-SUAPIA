# Plano — Épico 3: Pipeline e Fila de Mensagens

> Requisitos cobertos: RF08, RF09, RF10, RF11, RF12 | Regras: RN05, RN06, RN07, RN08

**Depende de:** Épico 0 (tabela `message_queue`) e Épico 1 (sessão/auth)

---

## Objetivo

Receber mensagens via webhook, validá-las, enfileirá-las no PostgreSQL e processá-las de forma assíncrona em ordem FIFO por `chat_id`.

---

## Arquivos a criar / modificar

| Arquivo | Ação |
|---------|------|
| `routes/webhook.py` | Criar — handler do POST /webhook |
| `services/queue_service.py` | Criar |
| `models/database.py` | Atualizar — model `MessageQueue` |
| `main.py` | Atualizar — incluir router + lifespan para worker |

---

## Passos

### 3.1 — `routes/webhook.py` — Recepção (RF08, RF09, RN05)

```python
POST /webhook
```

1. **Validação de origem (RN05):** verificar IP allowlist ou header `X-WAHA-Signature` antes de qualquer processamento.
2. **Parse do payload (RF08):** extrair `chat_id` e `content` do JSON do WAHA.
3. **Validação de estrutura (RF09):** se campos obrigatórios ausentes → HTTP 400 + log + retorna.
4. Chamar `queue_service.enqueue(chat_id, content)`.
5. Retornar HTTP 200 imediatamente (RNF01 — não bloquear o webhook).

Exemplo de payload WAHA esperado:
```json
{ "event": "message", "payload": { "from": "5586999...", "body": "texto" } }
```

### 3.2 — `services/queue_service.py`

**`enqueue(chat_id, content)`** — RF10, RF11:
1. Verificar autenticação via `session_service.is_authenticated(chat_id)`.
   - Não autenticado → `auth_service.generate_onboarding_link(chat_id)` → envia link via WAHA (não enfileira).
2. Verificar rate limit via `session_service.increment_rate(chat_id)`.
   - Limite atingido (> 25) → envia aviso ao usuário (não enfileira).
3. Inserir `MessageQueue(chat_id, content, status='pending')` no PostgreSQL.

**`process_next()`** — RF12, RN07, RN08:
1. Buscar mensagem mais antiga com `status='pending'` agrupada por `chat_id` (FIFO por chat_id).
2. Marcar como `processing` + salvar `updated_at`.
3. Chamar `message_router.route(chat_id, content, token)`.
4. Em sucesso: status → `completed`, salvar resposta no `thread_history`.
5. Em falha/timeout: status → `failed`, salvar `error_detail`.
6. `chat_id`s distintos podem ser processados em paralelo (RN08).

**`cleanup_stale()`** — RN07:
- Buscar mensagens com `status='processing'` e `updated_at < now() - QUEUE_TIMEOUT_MINUTES`.
- Marcar como `failed` com `error_detail='timeout'`.
- Executar periodicamente (a cada 60s via `asyncio` lifespan task).

### 3.3 — Worker assíncrono em `main.py`

No lifespan do FastAPI:
```python
@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(queue_worker())      # processa fila
    asyncio.create_task(stale_cleaner())     # RN07: limpa stale
    yield
```

`queue_worker`: loop infinito com `await asyncio.sleep(1)` entre iterações.

### 3.4 — Índice e constraints da tabela

Garantir (na migration 002):
- `INDEX (status, created_at)` — RN07
- `updated_at` atualizado via trigger ou manualmente no ORM

---

## Critérios de Aceite

- **RF08:** Webhook recebe payload, extrai `chat_id` e `content`.
- **RF09:** Payload inválido → HTTP 4xx + log; payload válido → fila.
- **RF10:** Não autenticado → onboarding; cota excedida → aviso; ok → enfileira.
- **RF11:** Registro inserido com `status='pending'` e timestamp correto.
- **RF12:** `completed` tem resposta; `failed` tem erro logado; nenhuma mensagem fica `processing` além do timeout.
- **RN05:** Requests de IPs não autorizados são rejeitados com 403.
- **RN06:** Após 25 mensagens no dia, novas mensagens retornam aviso; contador reseta meia-noite BRT.
- **RN07:** Mensagens em `processing` há mais de `QUEUE_TIMEOUT_MINUTES` viram `failed`.
- **RN08:** Dois `chat_id`s distintos são processados simultaneamente; mesmo `chat_id` respeitado em FIFO.
