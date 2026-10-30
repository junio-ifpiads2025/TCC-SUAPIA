# chat-bot — SUAPIA Webhook

Microsserviço principal do SUAPIA. Recebe mensagens do WhatsApp (via **WAHA**) ou Telegram, autentica o aluno no **SUAP**, gerencia sessão/fila e retorna respostas geradas por IA — combinando busca semântica nos manuais (RAG), base de conhecimento editável, skills e consulta de dados acadêmicos pessoais (SUAP Ensino). Tudo é configurável em tempo real por um **painel admin web** (`/admin`).

Porta padrão: **8002** · Processo único (um worker uvicorn, sem `--workers`).

---

## Sumário de Funcionalidades

| Área | O que faz |
|------|-----------|
| Mensageria multi-plataforma | Providers plugáveis (WAHA, Telegram) atrás de um contrato único |
| Autenticação SUAP | Link UUID de uso único, login web, token só no Redis, aceite de Termos de Uso (LGPD) |
| Fila Redis | Fila confiável com listas, recuperação após queda, retry, falhas e histórico de atendidas |
| Controle de acesso (ACL) | Allowlist + blocklist no Postgres, cache em memória, `block` sempre vence |
| Log de acesso | Eventos de atendimento no Postgres, LGPD-safe, com retenção automática |
| System prompt editável | Versionado no Postgres, restaurável, vale sem restart |
| Guardrails | Regras de entrada, saída e comportamento (prompt), com teste no painel |
| Skills | Instruções em markdown carregadas sob demanda pelo agente (`load_skill`) |
| Base de conhecimento | Documentos próprios indexados em pgvector, CRUD + upload + teste de busca |
| Agente ReAct | Tool calling com SUAP (aluno e professor), manuais, conhecimento e skills |
| Histórico de conversa | Últimos pares pergunta/resposta no Redis para perguntas de acompanhamento |
| Painel admin | Jinja2 + HTMX, login com sessão assinada, CSRF, throttle de login |

---

## Arquitetura Geral

```
WhatsApp / Telegram
      │
      ▼
   WAHA (Docker) / Telegram ──► POST /webhook[/{provider}]
      │
      ▼
   routes/webhook.py
      │  provider.parse_webhook → IncomingMessage
      │  acl_service.check (block vence; sem I/O)  ──► bloqueado/negado: descarta + access_log
      ▼
   queue_service.enqueue
      │  /sair · autenticação · rate limit diário
      │  [não autenticado] → link UUID de login → messaging_client
      ▼
   Redis: suap:queue:pending ──► worker(s) asyncio (BLMOVE → processing)
      │
      ▼
   message_router.route
      │  comandos (/menu, /about)
      │  guardrail de ENTRADA (block → responde sem chamar LLM)
      │  token + histórico (Redis)
      ▼
   agent_orchestrator (ReAct, tool calling)
      │  system prompt ativo (Postgres) + guardrails "instruct" + catálogo de skills
      │  tools: SUAP · search_manuals · search_knowledge · load_skill
      ▼
   guardrail de SAÍDA (mask/replace/block) ─► thread_service ─► messaging_client ─► provider ─► plataforma
```

---

## Contrato de Mensageria

Todo envio passa por **`services/messaging_client.py`** (fachada), que escolhe o provider pelo `chat_id`. Rotas e serviços nunca importam código de plataforma.

O contrato é a classe abstrata **`MessagingProvider`** (`services/providers/base.py`):

| Método | Obrigatório | Função |
|--------|:-----------:|--------|
| `parse_webhook(request) -> IncomingMessage \| None` | ✅ | converte o webhook da plataforma em mensagem normalizada (`None` = ignorar; `InvalidPayload` = HTTP 400) |
| `enviar_texto(chat_id, texto)` | ✅ | respostas da IA, avisos, link de login |
| `enviar_imagem(chat_id, url)` | ✅ | imagens dos manuais |
| `marcar_lida(chat_id, message_id)` | — | no-op por padrão |
| `iniciar_digitacao(chat_id)` | — | no-op por padrão |

Os métodos recebem o `chat_id` **nativo** da plataforma. O provider `waha` mantém o id puro (`5586...@c.us`); os demais são prefixados na aplicação (`telegram:123456`), evitando colisão entre plataformas.

**Para adicionar um provider (ex: Discord):**
1. Crie `services/providers/discord.py` com uma subclasse de `MessagingProvider` (`name = "discord"`).
2. Registre `"discord": "services.providers.discord:DiscordProvider"` em `_BUILTIN` (`services/providers/__init__.py`).
3. Habilite no `.env`: `MESSAGING_PROVIDERS=waha,discord`.
4. Aponte o webhook da plataforma para `POST /webhook/discord` (validação de secret/assinatura vai dentro de `parse_webhook`).
5. Cadastre os chat_ids permitidos em `/admin/access`.

`POST /webhook` continua existindo como alias de `/webhook/waha`.

Respostas do webhook: `200 {"status":"ok"}` (aceito, ou descartado pela ACL sem resposta ao usuário), `200 {"status":"ignored"}` (evento sem texto, ack, `fromMe`), `400` (payload inválido ou secret errado), `404` (provider desconhecido ou desabilitado).

### WAHA

Eventos ignorados: `message.waiting_message`, `message.ack`, `message.revoked`, `session.status`, `presence.update`, além de mensagens do próprio número (`fromMe`). Antes de cada resposta o `waha_client` aplica o padrão anti-ban (RN14): `sendSeen` → `startTyping` → espera proporcional ao tamanho (máx. 8 s) → `stopTyping` → `sendText`. Sessão WAHA fixa: `default`. Header `X-Api-Key` enviado quando `WAHA_API_KEY` está preenchida.

### Telegram

Variáveis: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` (validado no header `X-Telegram-Bot-Api-Secret-Token`) e `MESSAGING_PROVIDERS=waha,telegram`.
Na subida, se `APP_BASE_URL` for `https://` público, o webhook é registrado automaticamente (`setWebhook`). Em desenvolvimento, exponha a porta 8002 com um túnel (ngrok/cloudflared) e use a URL como `APP_BASE_URL`.
Só conversas privadas com texto são processadas. Respostas longas são divididas em partes de 4096 caracteres.

---

## Estrutura de Arquivos

```
chat/
├── main.py                         # FastAPI: routers, lifespan, workers da fila, retenção de logs
├── config.py                       # Todas as variáveis de ambiente centralizadas
├── requirements.txt
├── Dockerfile                      # python:3.12-slim, uvicorn na porta 8002
├── docker-compose.yml              # Container do próprio chat-bot (usa .env.dev, volume ./prompts)
├── Makefile                        # install / dev / prod
├── .env.example                    # Modelo de variáveis (copie para .env.dev / .env.prod)
├── docs/
│   ├── Plano_Painel_Admin.md       # Plano e decisões do painel admin
│   ├── Plano_Integracao_SUAP_MCP.md
│   └── Resumo_Alteracoes_SUAP_MCP.md
├── web/
│   ├── login.html                  # Login do aluno (HTML puro, placeholders {{TOKEN}}/{{AGENT_NAME}})
│   └── admin/                      # Templates Jinja2 do painel (base, dashboard, queue, prompt,
│                                   #   skills, knowledge, access, logs, login, parciais HTMX)
├── models/
│   └── database.py                 # SQLAlchemy async: UserAuth, KnowledgeDocument, AccessRule,
│                                   #   AccessLog, PromptVersion, Skill, Guardrail
├── routes/
│   ├── webhook.py                  # POST /webhook[/{provider}] — eventos das plataformas
│   ├── auth.py                     # GET/POST /auth/login — login web do aluno
│   ├── terms.py                    # GET /terms (JSON), /terms/view (HTML) — Termo de Compromisso de Uso
│   ├── admin.py                    # Agregador dos routers do painel
│   ├── admin_common.py             # Templates, sessão assinada, CSRF, require_admin, render
│   ├── admin_auth.py               # Login/logout do painel + resumo (/admin)
│   ├── admin_queue.py              # Fila de atendimento
│   ├── admin_prompt.py             # System prompt
│   ├── admin_skills.py             # Skills + guardrails
│   ├── admin_knowledge.py          # Base de conhecimento
│   ├── admin_access.py             # Allowlist / blocklist
│   └── admin_logs.py               # Log de acesso
├── services/
│   ├── messaging_client.py         # ★ Fachada de envio (único ponto de import)
│   ├── providers/                  # ★ Contrato (base.py), registry, waha.py, telegram.py
│   ├── waha_client.py              # Cliente HTTP do WAHA (anti-ban: sendSeen → typing → delay → sendText)
│   ├── auth_service.py             # Autenticação SUAP, vínculo chat_id → matrícula, perfil
│   ├── session_service.py          # Redis: token TTL, rate limit, link UUID, perfil
│   ├── queue_service.py            # Fila Redis (listas), worker, recuperação, retry
│   ├── message_router.py           # Comandos, guardrails de entrada/saída, histórico
│   ├── thread_service.py           # Histórico curto da conversa (Redis)
│   ├── acl_service.py              # Allowlist/blocklist com cache em memória
│   ├── access_log_service.py       # Log de acesso (Postgres), LGPD-safe
│   ├── prompt_service.py           # System prompt versionado
│   ├── guardrail_service.py        # Regras input/output/prompt
│   ├── skill_service.py            # Skills editáveis
│   ├── knowledge_service.py        # CRUD + busca vetorial da base de conhecimento
│   ├── rag_agent.py                # RAG dos manuais (busca vetorial; usado pela tool search_manuals)
│   ├── agent_orchestrator.py       # Orquestrador ReAct (tool_calling loop)
│   ├── mcp_client.py               # Cliente httpx da API SUAP com tools OpenAI
│   ├── falta_calculator.py         # Limite e cálculo de faltas por disciplina
│   └── logger.py                   # Logger estruturado
├── utils/
│   └── security.py                 # Sanitização de logs (remove token, senha, CPF)
└── tests/                          # pytest (fakes manuais, sem Redis/Postgres reais)
```

---

## Fluxo de Autenticação

O link enviado ao aluno **nunca contém o número de telefone ou matrícula** — apenas um UUID de uso único:

```
1. Aluno envia mensagem sem vínculo
2. Sistema gera UUID → Redis: suap:onboarding_link:{uuid} = chat_id  (TTL: 15 min)
3. messaging_client envia ao aluno: https://dominio/auth/login?token={uuid}
4. Aluno aceita os Termos de Uso, preenche matrícula + senha → POST /auth/login?token={uuid}
5. Backend valida UUID → autentica no SUAP → token no Redis (TTL retornado pela API)
6. Vínculo chat_id → matrícula (e data do aceite dos termos) persistido em user_auth (PostgreSQL)
7. Perfil (nome, curso) é buscado no SUAP e cacheado para a saudação personalizada
8. messaging_client notifica o resultado na plataforma (sucesso ou erro)
```

O comando `/sair` encerra a sessão: apaga token, vínculo, perfil e histórico da conversa.

---

## Pipeline de Mensagens e Fila (Redis)

O webhook retorna `200 OK` imediatamente (RNF01); o atendimento ocorre em workers asyncio dentro do mesmo processo.

| Chave Redis | Tipo | Conteúdo |
|-------------|------|----------|
| `suap:queue:pending` | list | Aguardando (`LPUSH`; consumo FIFO pela direita) |
| `suap:queue:processing` | list | Em atendimento (`BLMOVE pending → processing`) |
| `suap:queue:started` | hash | `id → timestamp` do início do atendimento |
| `suap:queue:failed` | list | Falhas/timeouts (máx. 500) |
| `suap:queue:done` | list | Atendidas, com resposta (máx. 500, resposta truncada em 4000 chars) |

Payload JSON: `{id, chat_id, provider, content, enqueued_at, attempts}`.

Garantias:
- **Nada se perde:** na subida `recover_processing()` devolve tudo de `processing` para `pending`.
- **Timeout (RN07):** o `_stale_cleaner` (a cada 60 s) devolve itens parados além de `QUEUE_TIMEOUT_MINUTES` para `pending`, até `QUEUE_MAX_ATTEMPTS`; depois vão para `failed`.
- **Ordem por conversa (RN08):** o mesmo `chat_id` é atendido um por vez, mesmo com vários consumidores (`QUEUE_CONSUMERS`).
- **Anti-ban:** mensagem marcada como lida ao chegar e "digitando…" durante o processamento.
- **Rate limit (RN06):** `MAX_DAILY_MESSAGES` por conta/dia, contador no Redis, reset à meia-noite BRT.

---

## Controle de Acesso (ACL)

`services/acl_service.py` — tabela `access_rule` (`chat_id`, `kind` allow|block, motivo, autor).

- **`block` sempre vence `allow`.**
- `RESPONDER_QUALQUER_NUMERO=false`: só quem está em `allow` passa. `true`: só `block` barra.
- Regras espelhadas em **sets em memória**, carregados na subida e atualizados na escrita — o webhook nunca consulta o banco.
- As regras vêm **só do banco** (nada de números no `.env`); cadastre em `/admin/access`.
- Bloqueados são descartados em silêncio e registrados no log.
- Gerenciado em `/admin/access` (adicionar/remover, motivo, busca por número).

---

## Log de Acesso

`services/access_log_service.py` — tabela `access_log`.

- Eventos: `received`, `blocked`, `denied`, `rate_limited`, `guardrail_input`, `guardrail_output`, `answered`, `failed`.
- **Ações do admin** também entram aqui: `chat_id=admin:<usuário>`, `provider=admin`, evento `admin_*` (login, login_failed, logout, acl_add/remove, prompt_save/activate, skill_*, guardrail_*, knowledge_*, queue_cancel/requeue). `detail` guarda só ids/alvos (`skill=x`, `version=3`), nunca conteúdo.
- Campos: `chat_id`, `provider`, `event`, `detail`, `duration_ms`, `created_at`.
- **LGPD:** por padrão grava só tamanho + hash curto da mensagem (`len=… sha=…`), nunca o texto. `ACCESS_LOG_STORE_CONTENT=True` libera o conteúdo.
- Gravação fora do caminho crítico (`asyncio.create_task`).
- **Retenção:** purga automática diária de registros mais antigos que `ACCESS_LOG_RETENTION_DAYS`.
- Consulta em `/admin/logs` com filtros por usuário, evento e data.

---

## System Prompt Editável

`services/prompt_service.py` — tabela `prompt_version` (uma versão ativa).

- Prompt ativo mantido em memória; `get_system_prompt()` é síncrono e sem I/O.
- Editar cria uma nova versão ativa; versões antigas podem ser **restauradas**.
- Vale imediatamente, sem restart. Fonte única é o banco (sem `SYSTEM_PROMPT` no env); sem versão, o agente usa um fallback embutido.
- Mantém o placeholder `{AGENT_NAME}`; limite de 20 000 caracteres.
- Regras de guardrail `instruct` são anexadas ao final num bloco "Regras de comportamento".
- Usado tanto pelo agente ReAct quanto pelo RAG simples.

---

## Guardrails

`services/guardrail_service.py` — tabela `guardrail`, regras compiladas em memória.

| Escopo | Onde atua | Ações |
|--------|-----------|-------|
| `input` | `message_router`, antes do agente | `block` (responde sem chamar o LLM), `replace` |
| `output` | sobre a resposta, antes de salvar/enviar | `mask` (trecho → `***`), `replace`, `block` |
| `prompt` | anexado ao system prompt | `instruct` (orientação ao modelo; sem garantia dura) |

Campos: `name`, `description`, `scope`, `match_type` (`keyword` \| `regex`), `pattern`, `action`, `response`, `instruction`, `priority`, `enabled`.

Segurança: regex validada ao salvar (padrão até 500 caracteres, detecção de quantificadores aninhados contra ReDoS; no teste, texto até 2000 caracteres e timeout de 2 s). `block` sem texto responde "Desculpe, não posso ajudar com isso."; `mask` troca o trecho por `***`. O texto do usuário nunca é logado. `POST /admin/api/guardrails/test` aplica as regras a um texto de exemplo sem enviar nada.

---

## Skills

`services/skill_service.py` — tabela `skill` (slug, nome, descrição, corpo markdown até 20 000 chars).

- O agente recebe só o **catálogo** (slug, nome, descrição) no prompt.
- Quando a pergunta se encaixa, chama a tool **`load_skill`** para ler as instruções completas.
- CRUD em `/admin/skills`; cache em memória recarregado a cada escrita.

---

## Base de Conhecimento (RAG editável)

`services/knowledge_service.py` — tabela `knowledge_document` + coleção pgvector própria `conhecimento_agente` (**não toca nos manuais** já indexados).

- Documento dividido em chunks (`KNOWLEDGE_CHUNK_SIZE` / `KNOWLEDGE_CHUNK_OVERLAP`) com ids determinísticos; atualizar faz upsert e remove só as sobras; falha no banco desfaz os vetores.
- Limite por documento: `KNOWLEDGE_MAX_CHARS`. Upload de `.txt` e `.md`.
- Tool `search_knowledge` no agente (top-k = `KNOWLEDGE_TOP_K`), ao lado de `search_manuals`.
- `/admin/knowledge`: criar, editar (reindexa), excluir, upload e **testar a recuperação**.

---

## Agente ReAct

`services/agent_orchestrator.py` — loop de tool calling (máx. `AGENT_MAX_ITERATIONS`; ao atingir o limite força uma síntese). Recebe o histórico da conversa (`THREAD_HISTORY_PAIRS` pares) para perguntas de acompanhamento.

- **Sem token** no Redis (sessão expirada), o agente nem chama o LLM: responde pedindo novo login.
- Injeta uma mensagem de sistema com **data/hora atual (BRT)** para resolver "hoje", "esse ano", "agora".
- A tool `load_skill` só é exposta quando há skills cadastradas; o catálogo vai no prompt.
- Falha inesperada do agente devolve `FALLBACK_TEXT` e o par pergunta/resposta não é gravado no histórico.

### Ferramentas

| Tool | Origem |
|------|--------|
| `search_manuals` | RAG nos manuais do SUAP (`manuais_suap_ifpi`) |
| `search_knowledge` | Base de conhecimento do painel |
| `load_skill` | Instruções de uma skill cadastrada |
| Tools SUAP (abaixo) | `services/mcp_client.py` |

### Tools SUAP (`mcp_client.py`)

Cliente httpx direto na API REST do SUAP (tags Ensino e token, mais `/api/rh/eu` e `/api/rh/meus-vinculos`). **Adicionar tool = adicionar uma linha em `ENDPOINTS`.** Erros da API voltam como JSON estruturado para o LLM responder de forma amigável; o token nunca é logado (RN13). Endpoints paginados seguem até `MAX_PAGES`.

| Grupo | Tools |
|-------|-------|
| Perfil | `get_my_data`, `get_my_vinculos`, `get_student_data`, `get_graduation_requirements` |
| Períodos | `get_my_periods`, `get_periods` |
| Aluno | `get_disciplines`, `get_discipline_stages`, `get_report_card`, `get_upcoming_assessments`, `get_messages`, `get_all_disciplines` |
| Professor / diários | `get_diaries`, `get_my_diaries`, `get_my_open_diaries`, `get_diary_professors`, `get_diary_students`, `get_diary_classes`, `get_diary_assignments`, `get_diary_materials`, `get_diary_topics` |
| Trabalhos e materiais | `get_assignment`, `get_material` |
| Aulas virtuais | `get_virtual_classes`, `get_virtual_class` |

`falta_calculator.py` calcula o limite de faltas por carga horária (ignorando estágio, TCC e atividades complementares) para responder "quantas faltas ainda posso ter?".

---

## Painel Admin (`/admin`)

UI server-rendered (Jinja2 com autoescape + HTMX), sem build de frontend.

| Página | Função |
|--------|--------|
| `/admin` | Resumo: fila (pendentes/em atendimento/falhas), regras de acesso, atendimentos do dia, versão do prompt |
| `/admin/queue` | Fila em abas (pendentes, em atendimento, falhas, atendidas), cancelar/reenfileirar, auto-refresh |
| `/admin/prompt` | Editor do system prompt, histórico e restauração |
| `/admin/skills` | CRUD de skills e de guardrails, com botão "testar" |
| `/admin/knowledge` | CRUD de documentos, upload, teste de busca |
| `/admin/access` | Allowlist e blocklist |
| `/admin/logs` | Log de acesso com filtros |

Segurança do painel:
- Login com `ADMIN_USERNAME`/`ADMIN_PASSWORD` (`secrets.compare_digest`).
- Cookie de sessão assinado (`itsdangerous`), HttpOnly, SameSite=Strict, `Secure` em HTTPS, expira em `ADMIN_SESSION_TTL_SECONDS`.
- **CSRF** em todo POST/PUT/DELETE (header `X-CSRF-Token` ou campo `csrf_token`).
- **Throttle de login** no Redis: 5 falhas por IP bloqueiam por 15 min.
- Painel **desabilitado (503)** se `ADMIN_PASSWORD` ou `ADMIN_SESSION_SECRET` estiverem vazios.
- Rotas `/admin/api/*` respondem 401 sem sessão; páginas redirecionam para `/admin/login`.

---

## Pré-requisitos

- Python 3.12+
- PostgreSQL 16 com extensão **pgvector**
- **Redis** 7
- **WAHA** (container separado, ver `dockercompose.yml` na raiz do repositório) e/ou bot do Telegram
- Chave de API OpenAI

---

## Instalação e Execução

```bash
cd chat
make install                # venv + dependências
cp .env.example .env.dev    # configure as variáveis
make dev                    # porta 8002, reload, usa .env.dev
make prod                   # porta 8002, 1 worker, usa .env.prod
```

> Produção usa **um único worker**: ACL, prompt, skills e guardrails ficam em cache de memória invalidado pelas rotas admin. Escalar para vários processos exigiria trocar o cache por invalidação via Redis. Para mais vazão, aumente `QUEUE_CONSUMERS`.

Da raiz do repositório também funciona: `make chatbot-install`, `make chatbot-dev`, `make chatbot-prod`.

### Docker

```bash
docker compose up -d --build   # sobe só o chat-bot (porta 8002, lê .env.dev)
```

O `Dockerfile` usa `python:3.12-slim` e inicia `uvicorn main:app` (1 worker). O volume `./prompts` é montado em `/app/prompts`. Postgres, Redis e WAHA precisam estar acessíveis pelas URLs do `.env`.

### Subida

As tabelas são criadas/migradas automaticamente (`init_db`): `user_auth`, `knowledge_document`, `access_rule`, `access_log`, `prompt_version`, `skill`, `guardrail` (colunas novas entram via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). Em seguida carregam os caches de ACL, prompt e skills/guardrails, os providers (`startup()`) e as tasks de background (recuperação da fila, workers, `_stale_cleaner`, retenção do log).

### Testes

```bash
.venv/bin/pytest tests/
```

16 arquivos em `tests/`, sem Redis/Postgres reais. Cobrem fila, ACL, log de acesso, prompt, guardrails, skills, conhecimento, rotas do painel, providers de mensageria, cliente SUAP e webhook.

---

## Variáveis de Ambiente

### Conexões

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `OPENAI_API_KEY` | — | Chave da OpenAI |
| `WAHA_BASE_URL` | `http://localhost:3000` | URL base do WAHA (o cliente acrescenta `/api/sendText` etc.) |
| `WAHA_API_KEY` | — | Enviada no header `X-Api-Key` quando preenchida |
| `PGVECTOR_CONNECTION_STRING` | `postgresql+psycopg://admin:...@localhost:5432/vetordatabase` | PostgreSQL (RAG + tabelas) |
| `PGVECTOR_COLLECTION` | `manuais_suap_ifpi` | Coleção dos manuais |
| `REDIS_URL` | `redis://localhost:6379` | Redis |
| `SUAP_BASE_URL` | `https://suap.ifpi.edu.br` | URL base da API do SUAP |
| `SUAP_TOKEN` | — | Token de serviço (fallback/testes) |
| `APP_BASE_URL` | `http://localhost:8002` | URL pública deste serviço |

### Mensageria

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `MESSAGING_PROVIDERS` | `waha` | Providers habilitados (`waha,telegram`) |
| `TELEGRAM_BOT_TOKEN` | — | Token do bot |
| `TELEGRAM_WEBHOOK_SECRET` | — | Segredo validado no header do webhook |

### Comportamento

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `RESPONDER_QUALQUER_NUMERO` | `False` | Se `True`, só a blocklist barra |
| `MAX_DAILY_MESSAGES` | `25` | Limite diário por aluno |
| `SESSION_TTL_SECONDS` | `28800` | TTL do token de sessão (8h) |
| `AGENT_MAX_ITERATIONS` | `5` | Iterações máximas do loop ReAct |
| `THREAD_HISTORY_PAIRS` | `3` | Pares pergunta/resposta injetados no contexto |
| `AGENT_NAME` / `AGENT_VERSION` | `SUAP-IA` / `0.1.0` | Identidade do agente |
| `TEMPERATURE` | `0.3` | Temperatura do LLM |

### Modelos

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `MODELO_LLM` | `gpt-3.5-turbo` (código) / `gpt-4o-mini` (`.env.example`) | Modelo do RAG simples (`rag_agent`) |
| `MODELO_LLM_AVANCADO` | `gpt-4o` | Modelo do Agente ReAct |
| `MODELO_EMBEDDING` | `text-embedding-3-small` | Embeddings (manuais e base de conhecimento) |

> `.env.example` também traz `REDIS_PASSWORD` (para montar `REDIS_URL`) e `MODELO_AVALIADOR_LLM` / `MODELO_AVALIADOR_EMBEDDING` (avaliação RAGAS em `pipeline/evaluation`); o chat-bot não lê essas três. `AGENT_MAX_ITERATIONS`, `MODELO_LLM_AVANCADO`, `OPENAI_API_KEY`, `SUAP_BASE_URL` e `SUAP_TOKEN` são lidos direto pelo orquestrador.

### Fila

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `QUEUE_TIMEOUT_MINUTES` | `5` | Tempo em `processing` antes de considerar travado |
| `QUEUE_MAX_ATTEMPTS` | `2` | Tentativas antes de ir para `failed` |
| `QUEUE_CONSUMERS` | `1` | Consumidores asyncio da fila |

### Painel admin e logs

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ADMIN_USERNAME` | `admin` | Usuário do painel |
| `ADMIN_PASSWORD` | — | Senha (vazia = painel desabilitado) |
| `ADMIN_SESSION_SECRET` | — | Segredo longo e aleatório do cookie |
| `ADMIN_SESSION_TTL_SECONDS` | `28800` | Duração da sessão |
| `ACCESS_LOG_STORE_CONTENT` | `False` | Gravar texto da mensagem no log (LGPD) |
| `ACCESS_LOG_RETENTION_DAYS` | `90` | Retenção do log |

### Base de conhecimento

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `KNOWLEDGE_COLLECTION` | `conhecimento_agente` | Coleção pgvector |
| `KNOWLEDGE_CHUNK_SIZE` | `800` | Tamanho do chunk |
| `KNOWLEDGE_CHUNK_OVERLAP` | `150` | Sobreposição |
| `KNOWLEDGE_TOP_K` | `4` | Trechos retornados na busca |
| `KNOWLEDGE_MAX_CHARS` | `200000` | Limite por documento |

---

## Endpoints

### Públicos

| Método | Path | Descrição |
|--------|------|-----------|
| `POST` | `/webhook` | Alias de `/webhook/waha` |
| `POST` | `/webhook/{provider}` | Eventos da plataforma (`waha`, `telegram`) |
| `GET` | `/auth/login?token={uuid}` | Página de login do aluno |
| `POST` | `/auth/login?token={uuid}` | Autentica no SUAP |
| `GET` | `/terms` | Termo de Compromisso de Uso em JSON (`version`, `effective_date`, `title`, `content` em markdown) |
| `GET` | `/terms/view` | Mesmo termo como página HTML |

### Painel admin (sessão + CSRF nas escritas)

| Método | Path | Descrição |
|--------|------|-----------|
| `GET/POST` | `/admin/login` · `POST /admin/logout` | Sessão |
| `GET` | `/admin` | Resumo |
| `GET` | `/admin/queue`, `/admin/queue/table` | Fila (página e parcial HTMX) |
| `POST` | `/admin/queue/{id}/cancel` · `/requeue` | Cancelar pendente / reenfileirar falha |
| `GET/POST` | `/admin/prompt` · `POST /admin/prompt/{id}/activate` | Editar e restaurar prompt |
| `GET/POST` | `/admin/skills` · `POST /admin/skills/{slug}` · `/delete` | CRUD de skills |
| `POST` | `/admin/guardrails` · `/{id}` · `/{id}/delete` | CRUD de guardrails |
| `POST` | `/admin/api/guardrails/test` | Testa regras num texto |
| `GET` | `/admin/knowledge` | Página de conhecimento |
| `GET/POST/PUT/DELETE` | `/admin/api/knowledge[/{id}]` | CRUD de documentos |
| `POST` | `/admin/api/knowledge/upload` | Cria de `.txt`/`.md` |
| `GET` | `/admin/api/knowledge/search?q=` | Testa a recuperação |
| `GET/POST` | `/admin/access` · `POST /admin/access/remove` | Allowlist / blocklist |
| `GET` | `/admin/logs` | Log de acesso |

---

## Segurança e LGPD

- Link de login contém apenas UUID temporário — sem número de telefone ou matrícula na URL.
- Token SUAP e senha nunca aparecem em logs ou em texto plano no banco (RN03, RNF02); o token vive só no Redis com TTL.
- `utils/security.py` sanitiza dicts antes de logar.
- Aceite dos Termos de Uso registrado com data/hora (LGPD Art. 8º §5º).
- Log de acesso não guarda o texto das mensagens por padrão, com purga por retenção.
- Painel com autoescape (sem XSS), CSRF, cookie assinado e throttle de login. Falha de login grava só o IP no log (nunca o usuário digitado); sem Redis o throttle é desativado com aviso, mas a senha continua exigida.
- Telegram: secret do webhook comparado com `hmac.compare_digest`; logs do `httpx` silenciados para não vazar o token do bot na URL.
- Regex de guardrails validadas contra ReDoS.
