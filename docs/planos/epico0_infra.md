# Plano — Épico 0: Infraestrutura (Base)

> Pré-requisito de todos os outros épicos. Sem esta fase nenhum outro plano pode ser executado.

---

## Objetivo

Provisionar o ambiente local com PostgreSQL + pgvector, Redis e WAHA via Docker, criar as migrations do banco e garantir que `config.py` centraliza todas as variáveis.

---

## Passos

### 0.1 — Docker Compose

Criar `infra/docker-compose.yml` com os serviços:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  waha:
    image: devlikeapro/waha
    ports: ["3000:3000"]
    environment:
      WHATSAPP_DEFAULT_ENGINE: WEBJS
```

### 0.2 — Migrations SQL

Criar `infra/migrations/` com os três arquivos na ordem:

**001_user_auth.sql**
```sql
CREATE TABLE user_auth (
  id          SERIAL PRIMARY KEY,
  chat_id     TEXT UNIQUE NOT NULL,
  matricula   TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);
```

**002_message_queue.sql**
```sql
CREATE TYPE msg_status AS ENUM ('pending','processing','completed','failed');

CREATE TABLE message_queue (
  id           SERIAL PRIMARY KEY,
  chat_id      TEXT NOT NULL,
  content      TEXT NOT NULL,
  type         TEXT NOT NULL DEFAULT 'text',
  status       msg_status NOT NULL DEFAULT 'pending',
  error_detail TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_queue_status_created ON message_queue(status, created_at);
```

**003_thread_history.sql**
```sql
CREATE TYPE msg_role AS ENUM ('user','assistant');

CREATE TABLE thread_history (
  id         SERIAL PRIMARY KEY,
  chat_id    TEXT NOT NULL,
  role       msg_role NOT NULL,
  content    TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_thread_chat_id ON thread_history(chat_id, created_at DESC);
```

### 0.3 — Extensão pgvector

Adicionar ao topo de `001_user_auth.sql` ou em migration separada:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 0.4 — Script de execução das migrations

Criar `infra/run_migrations.sh`:
```bash
#!/bin/bash
for f in infra/migrations/*.sql; do
  psql "$DATABASE_URL" -f "$f"
done
```

### 0.5 — Atualizar `config.py`

Garantir que as seguintes variáveis estejam presentes:

```python
DATABASE_URL       # postgresql+asyncpg://...
REDIS_URL          # redis://localhost:6379/0
WAHA_BASE_URL      # http://localhost:3000
WAHA_API_KEY       # token do WAHA
OPENAI_API_KEY
COHERE_API_KEY
LOG_LEVEL          # DEBUG | INFO | ERROR  (default INFO)
SIMILARITY_THRESHOLD  # default 0.75 (RN09)
MAX_HISTORY_MESSAGES  # default 10 (RN10)
RATE_LIMIT_PER_DAY   # default 25 (RN06)
QUEUE_TIMEOUT_MINUTES # default 2 (RN07)
```

### 0.6 — Atualizar `requirements.txt`

Adicionar se ausente:
```
asyncpg
sqlalchemy[asyncio]
redis[asyncio]
httpx
python-dotenv
```

---

## Critérios de Aceite

- `docker compose up` sobe os três serviços sem erro.
- Migrations executam sem conflito em banco vazio.
- `psql` confirma tabelas `user_auth`, `message_queue`, `thread_history` e extensão `vector`.
- `config.py` carrega todas as variáveis com fallbacks documentados.
