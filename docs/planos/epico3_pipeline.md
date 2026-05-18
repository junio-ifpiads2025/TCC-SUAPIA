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
| `routes/admin.py` | Criar — painel HTML GET /admin/queue |

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

### 3.5 — `routes/admin.py` — Painel de fila (monitoramento)

```python
GET /admin/queue
```

Endpoint de uso interno para visualizar mensagens que estão aguardando ou em processamento na fila do PostgreSQL.

**Comportamento:**
1. Buscar do banco todas as mensagens com `status IN ('pending', 'processing')`, ordenadas por `created_at ASC`.
2. Retornar uma `HTMLResponse` com uma tabela HTML simples contendo os dados.
3. Não requer autenticação por ora (uso local/dev); em produção proteger com IP allowlist ou Basic Auth.

**Implementação sugerida em `routes/admin.py`:**

```python
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from models.database import MessageQueue
from sqlalchemy import select
from db import async_session  # sessão AsyncSession do projeto

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/queue", response_class=HTMLResponse)
async def queue_dashboard():
    async with async_session() as session:
        result = await session.execute(
            select(MessageQueue)
            .where(MessageQueue.status.in_(["pending", "processing"]))
            .order_by(MessageQueue.created_at.asc())
        )
        rows = result.scalars().all()

    rows_html = "".join(
        f"<tr>"
        f"<td>{r.id}</td>"
        f"<td>{r.chat_id}</td>"
        f"<td style='max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{r.content}</td>"
        f"<td><span style='color:{'orange' if r.status == 'processing' else 'steelblue'}'>{r.status}</span></td>"
        f"<td>{r.created_at.strftime('%d/%m/%Y %H:%M:%S')}</td>"
        f"<td>{r.updated_at.strftime('%d/%m/%Y %H:%M:%S') if r.updated_at else '—'}</td>"
        f"</tr>"
        for r in rows
    )

    html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="10">
  <title>SUAP-IA · Fila de Mensagens</title>
  <style>
    body {{ font-family: sans-serif; padding: 2rem; background: #f5f5f5; }}
    h1   {{ color: #333; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.15); }}
    th, td {{ border: 1px solid #ddd; padding: .6rem 1rem; text-align: left; font-size: .9rem; }}
    th {{ background: #4a90d9; color: #fff; }}
    tr:nth-child(even) {{ background: #f9f9f9; }}
    .badge {{ padding: 2px 8px; border-radius: 4px; color: #fff; font-size: .8rem; }}
    .empty {{ color: #888; font-style: italic; padding: 1rem; }}
    footer {{ margin-top: 1rem; font-size: .8rem; color: #aaa; }}
  </style>
</head>
<body>
  <h1>SUAP-IA · Fila de Mensagens Pendentes</h1>
  <p>Total aguardando resposta: <strong>{len(rows)}</strong> &nbsp;|&nbsp; Página atualiza automaticamente a cada 10s.</p>
  <table>
    <thead>
      <tr>
        <th>#ID</th><th>chat_id</th><th>Conteúdo</th><th>Status</th><th>Criado em</th><th>Atualizado em</th>
      </tr>
    </thead>
    <tbody>
      {rows_html if rows_html else '<tr><td colspan="6" class="empty">Nenhuma mensagem aguardando.</td></tr>'}
    </tbody>
  </table>
  <footer>SUAP-IA TCC · somente mensagens com status <em>pending</em> ou <em>processing</em> são exibidas.</footer>
</body>
</html>"""
    return HTMLResponse(content=html)
```

**Registrar em `main.py`:**
```python
from routes.admin import router as admin_router
app.include_router(admin_router)
```

**Notas:**
- A tag `<meta http-equiv="refresh" content="10">` recarrega a página a cada 10 segundos, funcionando como um painel live sem JavaScript extra.
- Em produção, remover ou proteger com middleware de Basic Auth ou restrição de IP (`X-Forwarded-For` / `request.client.host`).

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
- **Admin:** `GET /admin/queue` retorna HTML com todas as mensagens `pending`/`processing` ordenadas por `created_at`; página recarrega automaticamente a cada 10s.
