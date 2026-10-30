# Plano: painel admin web do SUAP-IA

## Contexto

Hoje o system prompt vem de `SYSTEM_PROMPT` no env, lido no import (`services/agent_orchestrator.py:38`, com uma cópia duplicada em `services/rag_agent.py:21`), então editar exige reiniciar. Não existe blocklist (a allowlist é a env `NUMEROS_PERMITIDOS`, `config.py`), não existe loader de skills, não existe guardrail, e a única tela admin (`GET /admin/queue`) é somente leitura e tem XSS (`routes/admin.py`). A fila vive no Postgres (`message_queue`) e não há log de acesso.

**Objetivo:** um painel em `/admin` para editar o prompt, ver skills e gerenciar guardrails, anexar conhecimento, ver a fila de atendimento e controlar quem pode usar o bot.

**Decisões tomadas:**
- UI server-rendered no FastAPI (Jinja2 + HTMX), sem build de frontend.
- Login admin com usuário/senha do env e cookie de sessão assinado.
- Divisão de armazenamento (abaixo).
- Fila em Redis com listas simples.
- **Um único worker:** um processo uvicorn (sem `--workers`) e um único consumidor da fila.
- Guardrails: filtro de entrada, filtro de saída e regras de comportamento no prompt.

## Divisão de armazenamento

| Armazenamento | Responsabilidade |
|---|---|
| **Redis** | Fila de atendimento, histórico curto de contexto (`suap:thread:*`), caches (perfil do aluno, respostas do SUAP) e estado com TTL (token SUAP, contador diário, link de onboarding) |
| **Postgres** | Log de acesso, allowlist, blocklist, guardrails, versões do system prompt, documentos de conhecimento, `user_auth` |
| **pgvector** | Manuais (`manuais_suap_ifpi`) e conhecimento (`conhecimento_agente`) |

Premissa a confirmar: token SUAP, contador diário e onboarding continuam no Redis porque são estado efêmero com TTL e não foram citados como mudança. A tabela `message_queue` é aposentada; o histórico do que foi atendido passa a ser o log de acesso.

O servidor roda com um único worker (`Makefile` de produção sem `--workers`). Consequências:
- Cache em memória do processo é seguro para o que o caminho quente lê (regras de acesso, guardrails compilados, prompt ativo): é carregado do Postgres na subida e invalidado direto pelas rotas admin, que rodam no mesmo processo. Sem chave de versão no Redis.
- Persistência continua obrigatória (Postgres/Redis), porque o cache some a cada restart.
- Escalar para mais processos no futuro exigiria trocar esse cache por invalidação via Redis; fica fora do escopo.

## 1. Fila de atendimento no Redis (listas)

Padrão de fila confiável com listas, para a mensagem não se perder se um worker cair:

| Chave | Tipo | Conteúdo |
|---|---|---|
| `suap:queue:pending` | list | Mensagens aguardando (`LPUSH` na entrada) |
| `suap:queue:processing` | list | Mensagens em atendimento |
| `suap:queue:started` | hash | `id → timestamp` de quando cada uma entrou em atendimento |
| `suap:queue:failed` | list | Falhas e timeouts, limitada com `LTRIM` (ex.: 500) |

- **Payload:** JSON `{id, chat_id, provider, content, enqueued_at, attempts}`.
- **Consumo:** um único consumidor (a task `_queue_worker` de `main.py`) usa `BLMOVE pending processing RIGHT LEFT` (FIFO, ordem global preservada). Ao terminar: `LREM` de `processing`, `HDEL` de `started`.
- **Recuperação:** na subida do app tudo o que sobrou em `processing` (queda no meio de um atendimento) volta para `pending`. Em execução, o `_stale_cleaner` de `main.py` varre `processing`: item parado há mais de `QUEUE_TIMEOUT_MINUTES` volta para `pending` (até `QUEUE_MAX_ATTEMPTS`) ou vai para `failed`.
- **Concorrência:** com um consumidor, as mensagens são atendidas uma por vez. Se a latência do LLM virar gargalo, o caminho é aumentar o número de consumidores asyncio dentro do mesmo processo (`QUEUE_CONSUMERS`, padrão 1), sem voltar a múltiplos workers.
- **Ações do admin:** listar cada lista (`LRANGE`), contagens (`LLEN`), cancelar item de `pending` (`LREM`), reenfileirar item de `failed`.
- **Limitação aceita:** listas não têm ack nativo nem consulta por id. A lista `processing` + hash `started` cobre a perda por queda de worker, mas ver o histórico completo fica a cargo do log de acesso (Postgres).
- **Arquivos:** reescrever `services/queue_service.py` (`enqueue`, `process_next`, `cleanup_stale`) preservando checagens atuais (rate limit, `marcar_lida`, digitando); remover `MessageQueue` de `models/database.py` após migrar.

## 2. Postgres: acesso e log

**`access_rule`** (allowlist e blocklist numa tabela)
- Colunas: `chat_id` (único, no formato qualificado dos providers), `kind` (`allow` | `block`), `reason`, `created_at`, `created_by`.
- Regra: **block sempre vence**. Com `RESPONDER_QUALQUER_NUMERO=false`, só `allow` passa; com `true`, só `block` barra.
- `NUMEROS_PERMITIDOS` do env vira seed único no `init_db`; depois a tabela manda.
- Cache: sets `allow`/`block` em memória, carregados do Postgres na subida e atualizados pelas rotas admin na escrita. O webhook nunca consulta o Postgres.

**`access_log`**
- Colunas: `id`, `chat_id`, `provider`, `event` (`received`, `blocked`, `denied`, `rate_limited`, `guardrail_input`, `guardrail_output`, `answered`, `failed`), `detail`, `duration_ms`, `created_at`. Índices por `chat_id` e `created_at`.
- **LGPD:** não gravar o texto da mensagem por padrão, só tamanho/hash; guardar conteúdo só se `ACCESS_LOG_STORE_CONTENT=true`. Purga por retenção (`ACCESS_LOG_RETENTION_DAYS`).
- Gravação fora do caminho crítico (`asyncio.create_task`), para o log não atrasar a resposta.

**Integração:** `routes/webhook.py:59` troca a checagem de env por `acl_service.check(chat_id)`; bloqueado é descartado em silêncio e registrado no log. Bloquear pode limpar `suap:token:*` e `suap:thread:*` (opção).

## 3. System prompt (Postgres + cache)

- Tabela `prompt_version` (`id`, `content`, `active`, `created_at`, `author`); uma versão ativa.
- `services/prompt_service.py`: `get_system_prompt()` devolve o prompt ativo guardado em memória (carregado do Postgres na subida, atualizado ao salvar), com fallback ao env/default. Mantém `{AGENT_NAME}`. `save`, `activate` (restaurar versão antiga).
- `agent_orchestrator.invoke` e `rag_agent.py` passam a chamar `get_system_prompt()`. O orquestrador é criado por mensagem, então vale na hora.

## 4. Skills e guardrails (mesma página `/admin/skills`)

### Skills
- `services/skill_service.py` guarda as skills no Postgres (tabela `skill`: slug, nome, descrição, tools, corpo); CRUD pelo painel.

### Guardrails (CRUD)

Tabela `guardrail`:

| Campo | Valores |
|---|---|
| `name`, `description` | Texto livre |
| `scope` | `input` · `output` · `prompt` |
| `match_type` | `keyword` · `regex` (só para `input`/`output`) |
| `pattern` | Termo(s) ou expressão |
| `action` | `block` (responde `response` e não chama o LLM), `mask` (substitui o trecho por `***`), `replace` (troca a resposta inteira por `response`), `instruct` (só `prompt`) |
| `response` | Mensagem enviada ao usuário quando a regra dispara |
| `instruction` | Texto injetado no system prompt (`scope=prompt`) |
| `priority`, `enabled` | Ordem de avaliação e liga/desliga |

Comportamento:
- **Entrada:** em `services/message_router.route`, depois dos comandos estáticos e antes do agente. Regra `block` responde na hora, sem custo de LLM, e registra `guardrail_input`.
- **Saída:** sobre a resposta do agente antes do envio (`mask` para CPF/token/matrícula, `replace`/`block` para termos proibidos). Registra `guardrail_output`.
- **Prompt:** regras `instruct` ativas são concatenadas ao system prompt pelo `prompt_service`, em bloco "Regras de comportamento". Observação: é orientação ao modelo, sem garantia dura; o que precisa ser garantido usa entrada/saída.
- **Cache:** regras compiladas em memória, recarregadas do Postgres pelas rotas admin a cada escrita.
- **Segurança:** validar a regex ao salvar (compila, tamanho máximo, tempo limite no teste) para evitar ReDoS; endpoint `POST /admin/api/guardrails/test` aplica as regras a um texto de exemplo sem enviar nada.
- **Fora desta fase:** checagem por LLM.

## 5. Base de conhecimento (RAG editável) — **implementado**

CRUD de documentos complementares, sem tocar nos manuais já indexados.

- Coleção pgvector própria `conhecimento_agente` + tabela `knowledge_document` (texto completo e `chunk_count`).
- `services/knowledge_service.py`: `create/update/delete/get/list_documents`, `search`. Ids de chunk determinísticos (uuid5): atualizar faz upsert e remove só as sobras; falha no banco desfaz os vetores.
- Tool `search_knowledge` no agente, ao lado de `search_manuals`.
- API (hoje Basic Auth; migra para a sessão do painel):

| Método | Rota | Função |
|---|---|---|
| GET | `/admin/api/knowledge` | Lista |
| GET | `/admin/api/knowledge/{id}` | Completo |
| POST | `/admin/api/knowledge` | Cria |
| POST | `/admin/api/knowledge/upload` | Cria de `.txt`/`.md` |
| PUT | `/admin/api/knowledge/{id}` | Atualiza e reindexa |
| DELETE | `/admin/api/knowledge/{id}` | Remove |
| GET | `/admin/api/knowledge/search?q=` | Testa a recuperação |

- Testes em `tests/test_knowledge_service.py` e `tests/test_admin_knowledge_routes.py`.

## 6. Rotas e UI

`routes/admin.py` é reescrito; templates em `web/admin/`.

**Autenticação:** `GET/POST /admin/login` valida `ADMIN_USERNAME`/`ADMIN_PASSWORD` com `secrets.compare_digest`; cookie assinado (`itsdangerous`, `ADMIN_SESSION_SECRET`), HttpOnly, SameSite=Strict, com expiração; CSRF em todo POST; throttle de login no Redis; 503 se a senha estiver vazia.

| Página | Função |
|---|---|
| `/admin` | Resumo: tamanho das listas da fila, bloqueados, atendimentos do dia, versão do prompt |
| `/admin/queue` | Fila de atendimento em três abas (pendentes, em atendimento, falhas), com cancelar/reenfileirar e auto-refresh HTMX |
| `/admin/prompt` | Editor do system prompt, histórico, restaurar versão |
| `/admin/skills` | Skills (lista/detalhe) e, na mesma página, CRUD de guardrails com botão "testar" |
| `/admin/knowledge` | Documentos de conhecimento (CRUD, upload, testar busca) |
| `/admin/access` | Allowlist e blocklist (adicionar/remover, motivo, busca por número) |
| `/admin/logs` | Log de acesso com filtros por usuário, evento e data |

Renderização: Jinja2 com autoescape (resolve o XSS atual) e parciais HTMX. Dependências: `jinja2`, `itsdangerous`, `python-multipart`, `pytest`, `httpx`.

## 7. Infra

- `Makefile`: `make prod` sem `--workers` (feito).
- Novas envs em `config.py` (regra do arquivo) e `.env.example`: `ADMIN_SESSION_SECRET`, `QUEUE_MAX_ATTEMPTS`, `QUEUE_CONSUMERS`, `ACCESS_LOG_STORE_CONTENT`, `ACCESS_LOG_RETENTION_DAYS`.
- Migração: as tabelas novas entram via `create_all` no `init_db` (`models/database.py`); `message_queue` pode ser removida depois que a fila Redis estiver em produção.

## Ordem sugerida de implementação

1. Fila em Redis (substitui `message_queue`) e tela `/admin/queue`.
2. `access_rule` + cache Redis + integração no webhook, tela `/admin/access`.
3. `access_log` e tela `/admin/logs`.
4. Login com sessão e CSRF; migrar as rotas existentes de Basic Auth.
5. `prompt_service` e `/admin/prompt`.
6. Guardrails (entrada, saída, prompt) e `/admin/skills`.
7. Tela `/admin/knowledge` sobre a API já pronta.

## Verificação

**Automatizada** (`chat/tests/`, pytest com fakes manuais; Redis fake ou monkeypatch)
- Fila: enqueue/consumo FIFO, recuperação de `processing` na subida, item volta de `processing` após timeout, vai para `failed` após `QUEUE_MAX_ATTEMPTS`, cancelar/reenfileirar.
- ACL: block vence allow; modo `RESPONDER_QUALQUER_NUMERO`; cache em memória atualiza na escrita.
- Guardrails: `block`/`mask`/`replace`/`instruct`, ordem por prioridade, regex inválida rejeitada.
- Rotas: login, CSRF, 401/403, CRUD de cada recurso.
- Webhook: chat bloqueado não gera item na fila e gera `access_log`.

**Manual** (`make dev`, porta 8002)
1. Mandar mensagens e acompanhar a fila em `/admin/queue`.
2. Matar o worker no meio de um atendimento e ver o item voltar de `processing`.
3. Editar o prompt e ver a mudança sem restart.
4. Criar guardrail de entrada e de saída e conferir o efeito e o `access_log`.
5. Bloquear/liberar um número.
6. Confirmar que conteúdo com `<script>` aparece escapado.

**Produção** (`make prod`, 1 worker): alterar prompt, guardrails e bloqueio e conferir que valem na hora; reiniciar o app com itens em `processing` e conferir que voltam para `pending` e são atendidos uma única vez.
