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
   routes/chat/webhook.py
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

Todo envio passa por **`services/chat/messaging_client.py`** (fachada), que escolhe o provider pelo `chat_id`. Rotas e serviços nunca importam código de plataforma.

O contrato é a classe abstrata **`MessagingProvider`** (`services/chat/providers/base.py`):

| Método | Obrigatório | Função |
|--------|:-----------:|--------|
| `parse_webhook(request) -> IncomingMessage \| None` | ✅ | converte o webhook da plataforma em mensagem normalizada (`None` = ignorar; `InvalidPayload` = HTTP 400) |
| `enviar_texto(chat_id, texto)` | ✅ | respostas da IA, avisos, link de login |
| `enviar_imagem(chat_id, url)` | ✅ | imagens dos manuais |
| `marcar_lida(chat_id, message_id)` | — | no-op por padrão |
| `iniciar_digitacao(chat_id)` | — | no-op por padrão |

Os métodos recebem o `chat_id` **nativo** da plataforma. O provider `waha` mantém o id puro (`5586...@c.us`); os demais são prefixados na aplicação (`telegram:123456`), evitando colisão entre plataformas.

**Para adicionar um provider (ex: Discord):**
1. Crie `services/chat/providers/discord.py` com uma subclasse de `MessagingProvider` (`name = "discord"`).
2. Registre `"discord": "services.providers.discord:DiscordProvider"` em `_BUILTIN` (`services/chat/providers/__init__.py`).
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

Organização por domínio (ver AGENT.MD): `chat` (atendimento pelo WhatsApp/Telegram), `admin` (painel) e `shared` (usado pelos dois). `chat` nunca importa `admin`; `admin` pode importar `chat` e `shared`.

```
chat/
├── main.py                         # FastAPI: routers, lifespan, workers da fila, retenção, alertas
├── config.py                       # Todas as variáveis de ambiente centralizadas
├── requirements.txt
├── Dockerfile                      # python:3.12-slim, uvicorn na porta 8002
├── docker-compose.yml              # Container do próprio chat-bot (usa .env.dev, volume ./prompts)
├── Makefile                        # install / dev / prod
├── .env.example                    # Modelo de variáveis (copie para .env.dev / .env.prod)
├── docs/
│   ├── Plano_Painel_Admin.md       # Plano e decisões do painel admin
│   ├── Plano_Painel_Admin_Expansao.md  # Plano da expansão do painel (auditoria, qualidade, saúde...)
│   ├── Plano_Integracao_SUAP_MCP.md
│   └── Resumo_Alteracoes_SUAP_MCP.md
├── models/
│   └── database.py                 # SQLAlchemy async: tabelas, init_db e migrações IF NOT EXISTS
├── routes/
│   ├── chat/
│   │   ├── webhook.py              # POST /webhook[/{provider}] — eventos das plataformas
│   │   ├── auth.py                 # GET/POST /auth/login — login web do aluno
│   │   └── terms.py                # GET /terms (JSON), /terms/view (HTML) — Termo de Uso
│   └── admin/                      # Painel /admin (cada módulo exporta `router`)
│       ├── __init__.py             # Agregador dos routers do painel
│       ├── common.py               # Templates, sessão assinada, CSRF, require_admin, render
│       ├── auth.py                 # Login/logout do painel + dashboard (/admin)
│       ├── queue.py                # Fila de atendimento
│       ├── prompt.py               # System prompt
│       ├── skills.py               # Skills + guardrails
│       ├── knowledge.py            # Base de conhecimento, reindexação, chunks
│       ├── access.py               # Allowlist / blocklist e limites diários
│       ├── users.py                # Busca, detalhe, bloqueio e exclusão de dados (LGPD)
│       ├── usage.py                # Uso de tokens e custo
│       ├── quality.py              # Avaliações e perguntas sem resposta
│       ├── logs.py                 # Log de acesso (+ PDF)
│       ├── audit.py                # Auditoria das alterações e reversão
│       ├── exports.py              # Exportações CSV/JSON
│       ├── health.py               # Saúde do sistema e /health público
│       ├── broadcast.py            # Mensagem em massa
│       └── admins.py               # Administradores por matrícula
├── services/
│   ├── chat/                       # Atendimento
│   │   ├── messaging_client.py     # ★ Fachada de envio (único ponto de import)
│   │   ├── providers/              # ★ Contrato (base.py, com health/reconnect), waha.py, telegram.py
│   │   ├── waha_client.py          # Cliente HTTP do WAHA (anti-ban: sendSeen → typing → delay → sendText)
│   │   ├── queue_service.py        # Fila Redis, worker, recuperação, retry, limites e cota de tokens
│   │   ├── message_router.py       # Comandos, guardrails de entrada/saída, histórico, "sem resposta"
│   │   ├── feedback_service.py     # Pedido de avaliação ("1"/"2") pendente no Redis
│   │   ├── thread_service.py       # Histórico curto da conversa (Redis)
│   │   ├── agent_orchestrator.py   # Orquestrador ReAct (tool_calling loop)
│   │   ├── rag_agent.py            # RAG dos manuais (tool search_manuals)
│   │   ├── mcp_client.py           # Cliente httpx da API SUAP com tools OpenAI
│   │   └── falta_calculator.py     # Limite e cálculo de faltas por disciplina
│   ├── shared/                     # Usado pelo atendimento e pelo painel
│   │   ├── auth_service.py         # Autenticação SUAP, vínculo chat_id → matrícula, perfil
│   │   ├── session_service.py      # Redis: token TTL, rate limit, contador de tokens, link UUID, perfil
│   │   ├── acl_service.py          # Allowlist/blocklist e limites diários com cache em memória
│   │   ├── access_log_service.py   # Log de acesso (Postgres), LGPD-safe, rotina de retenção
│   │   ├── audit_service.py        # Auditoria das alterações dos admins (ContextVar current_admin)
│   │   ├── prompt_service.py       # System prompt versionado
│   │   ├── guardrail_service.py    # Regras input/output/prompt
│   │   ├── skill_service.py        # Skills editáveis
│   │   ├── knowledge_service.py    # CRUD, busca vetorial e reindexação da base de conhecimento
│   │   ├── qa_case_service.py      # Casos de qualidade (avaliações e "sem resposta")
│   │   ├── usage_service.py        # Consumo de tokens por chamada, custo estimado
│   │   ├── dashboard_service.py    # Indicadores do dashboard (latência, erros, satisfação)
│   │   └── logger.py               # Logger estruturado
│   └── admin/                      # Só o painel
│       ├── admin_user_service.py   # Administradores por matrícula
│       ├── audit_revert.py         # Reversão de entradas da auditoria
│       ├── user_admin_service.py   # Busca e detalhe de usuários
│       ├── user_data_service.py    # Exclusão de dados do titular (LGPD)
│       ├── export_service.py       # CSV/JSON com neutralização de fórmulas
│       ├── health_service.py       # Sondas de saúde e reconexão de providers
│       ├── alert_service.py        # Alertas (Telegram/SMTP) e alert_loop
│       ├── broadcast_service.py    # Envio de mensagem em massa
│       └── pdf_report.py           # PDF do log de acesso
├── web/
│   ├── login.html                  # Login do aluno (HTML puro, placeholders {{TOKEN}}/{{AGENT_NAME}})
│   └── admin/                      # Templates Jinja2 do painel (uma página por área + parciais `_*.html`)
├── utils/
│   └── security.py                 # Sanitização de logs e mascaramento de chat_id (•••1234)
└── tests/                          # pytest (fakes manuais, sem Redis/Postgres reais; conftest isola a auditoria)
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
| `suap:fb:pending:<chat_id>` | string | Pedido de feedback da última resposta (pergunta, resposta, trechos), TTL 30 min |

Payload JSON: `{id, chat_id, provider, content, enqueued_at, attempts}`.

Garantias:
- **Nada se perde:** na subida `recover_processing()` devolve tudo de `processing` para `pending`.
- **Timeout (RN07):** o `_stale_cleaner` (a cada 60 s) devolve itens parados além de `QUEUE_TIMEOUT_MINUTES` para `pending`, até `QUEUE_MAX_ATTEMPTS`; depois vão para `failed`.
- **Ordem por conversa (RN08):** o mesmo `chat_id` é atendido um por vez, mesmo com vários consumidores (`QUEUE_CONSUMERS`).
- **Anti-ban:** mensagem marcada como lida ao chegar e "digitando…" durante o processamento.
- **Rate limit (RN06):** limite diário de mensagens por conta, contador no Redis, reset à meia-noite BRT. O limite efetivo é o próprio do usuário, se houver, senão o padrão definido no painel, senão `MAX_DAILY_MESSAGES` (RN22). A mensagem de recusa informa o número efetivo.
- **Orçamento de tokens (RN23):** com `DAILY_TOKEN_BUDGET > 0`, quem já consumiu esse total de tokens no dia tem a mensagem recusada com aviso. O consumo é somado no Redis (`suap:tokens:<chat_id>:<data>`) a cada chamada ao LLM.
- **Alerta de limite:** cada recusa por limite ou orçamento incrementa um contador sem identificação (`suap:alert:limit:<tipo>`), que o loop de alertas lê e zera.
- **Feedback (RN18):** a resposta "1" ou "2" a um pedido de feedback é tratada em `enqueue`, antes do rate limit: não aciona o agente nem conta no limite diário. Ver [Qualidade das Respostas](#qualidade-das-respostas).

---

## Controle de Acesso (ACL)

`services/shared/acl_service.py` — tabela `access_rule` (`chat_id`, `kind` allow|block, motivo, autor).

- **`block` sempre vence `allow`.**
- `RESPONDER_QUALQUER_NUMERO=false`: só quem está em `allow` passa. `true`: só `block` barra.
- Regras espelhadas em **sets em memória**, carregados na subida e atualizados na escrita — o webhook nunca consulta o banco.
- As regras vêm **só do banco** (nada de números no `.env`); cadastre em `/admin/access`.
- Bloqueados são descartados em silêncio e registrados no log.
- Gerenciado em `/admin/access` (adicionar/remover, motivo, busca por número).
- **Limite diário (RN22):** a mesma tela define o limite padrão de mensagens por dia (tabela `app_setting`, chave `max_daily_messages`; vazio volta ao `MAX_DAILY_MESSAGES` do ambiente) e o limite próprio de um número (`access_rule.daily_limit`). Um número sem regra de acesso que recebe limite próprio ganha uma linha `kind='limit'`, que não libera nem bloqueia. Remover allow/block mantém o limite próprio. Os limites ficam em cache em memória, como as regras, e toda alteração é auditada e reversível.

---

## Usuários e Exclusão de Dados (LGPD)

`services/admin/user_admin_service.py`, `services/admin/user_data_service.py`. Página `/admin/users`.

- **Busca** por matrícula ou número entre quem já fez login (`user_auth`). O número aparece mascarado (só os 4 últimos dígitos); o usuário é identificado no painel pelo id interno, nunca pelo número na URL.
- **Detalhe:** data do aceite dos termos, primeiro login, situação de acesso, mensagens e tokens consumidos hoje (com limite e orçamento), últimos 20 eventos do log. Abrir o detalhe é registrado na auditoria como leitura (`user_data`/`view`).
- **Ações:** bloquear (encerra a sessão na hora) e desbloquear, reaproveitando o controle de acesso; definir limite próprio.
- **Apagar dados (RN24):** a pedido do titular, o admin digita `APAGAR` para confirmar. É removido: login (`user_auth`), log de acesso, regra de acesso/limite, casos de qualidade; no Redis, token, perfil, histórico, pendência de feedback, contadores do dia e links de login; e os itens do usuário na fila. No consumo de tokens (`llm_usage`) o número é anonimizado (os totais permanecem). O Redis é limpo antes do banco: se estiver fora do ar, a exclusão falha antes de apagar qualquer coisa e pode ser repetida. A ação é auditada sem o número (só id interno e contagens) e não pode ser revertida.
- **Consumo por usuário:** o `chat_id` gravado em `llm_usage` vem de um `ContextVar` (`usage_service.current_chat_id`) definido pela fila durante o atendimento; `asyncio.to_thread` copia o contexto para a thread do agente. Esse vínculo é anonimizado após `ACCESS_LOG_RETENTION_DAYS` pela rotina diária de retenção.

**RN22 — Limite diário configurável:** o limite de mensagens por dia é definido no painel, com padrão geral e exceção por número; vale o limite próprio quando existe.

**RN23 — Orçamento diário de tokens:** com orçamento configurado, o usuário que o esgotar no dia não é atendido até a meia-noite (BRT) e recebe aviso claro.

**RN24 — Exclusão a pedido do titular:** o administrador pode apagar todos os dados de um usuário, com confirmação explícita e registro na auditoria, sem que a auditoria guarde o identificador apagado.

**Histórias de usuário:**
- Como administrador, quero encontrar um aluno pela matrícula e ver o uso dele hoje, para responder a reclamações sobre limite. *Critérios de aceite:* a busca encontra por matrícula parcial; o detalhe mostra mensagens e tokens do dia e o limite efetivo.
- Como estudante, quero pedir a exclusão dos meus dados, para exercer meu direito previsto na LGPD. *Critérios de aceite:* após a exclusão, não resta login, histórico, log, avaliação nem item de fila com meu número; a auditoria registra a exclusão sem meu número.

---

## Log de Acesso

`services/shared/access_log_service.py` — tabela `access_log`.

- Eventos: `received`, `blocked`, `denied`, `rate_limited`, `guardrail_input`, `guardrail_output`, `answered`, `failed`.
- **Ações operacionais do admin** também entram aqui: `chat_id=admin:<usuário>`, `provider=admin`, evento `admin_*` (login, login_failed, logout, queue_cancel/requeue, export). `detail` guarda só ids/alvos, nunca conteúdo. Alterações de configuração vão para a [Auditoria](#auditoria-do-painel).
- Campos: `chat_id`, `provider`, `event`, `detail`, `duration_ms`, `created_at`.
- **LGPD:** por padrão grava só tamanho + hash curto da mensagem (`len=… sha=…`), nunca o texto. `ACCESS_LOG_STORE_CONTENT=True` libera o conteúdo.
- Gravação fora do caminho crítico (`asyncio.create_task`).
- **Retenção:** purga automática diária de registros mais antigos que `ACCESS_LOG_RETENTION_DAYS`.
- Consulta em `/admin/logs` com filtros por usuário, evento e data.

---

## Auditoria do Painel

`services/shared/audit_service.py` — tabela `admin_audit`. Página `/admin/audit`.

Toda alteração de configuração feita por um administrador fica registrada com **quem** fez, **quando**, **o quê** e o **estado antes e depois** (RN15). Cobre: prompt (salvar/restaurar versão), skills, guardrails, regras de acesso (allow/block), o modo "responder qualquer número", documentos da base de conhecimento e a lista de administradores.

- O autor é identificado automaticamente pela sessão do painel: `require_admin` guarda o usuário num `ContextVar` (`current_admin`) que os serviços leem ao gravar. Fora do painel o autor aparece como `desconhecido`.
- A gravação acontece dentro do próprio serviço da entidade, logo depois da alteração; falha ao gravar só gera aviso e não desfaz a mudança.
- **Reverter** (`services/admin/audit_revert.py`): reaplica o estado anterior pelo próprio serviço da entidade, com as mesmas validações. Criação é desfeita removendo o item; remoção, recriando-o (documentos e guardrails recriados ganham novo id); alteração, reaplicando o "antes". No prompt, reverter reativa a versão que estava ativa. A reversão gera uma nova entrada de auditoria e marca a original como revertida (`reverted_by`), que não pode ser revertida de novo. Um admin não pode reverter alterações no próprio acesso.
- A tela filtra por administrador, área e período e mostra o diff campo a campo.
- **Dados pessoais:** a auditoria guarda matrícula do admin e, em regras de acesso, o `chat_id` alvo. Não guarda conversas.

**RN15 — Auditoria das alterações do painel:** toda alteração de configuração feita no painel deve ser registrada com autor, data e estado anterior e posterior, e deve poder ser revertida por um administrador.

**História de usuário:** como administrador, quero ver quem alterou o prompt, as regras ou os documentos e desfazer uma alteração errada, para corrigir rapidamente o comportamento do assistente. *Critérios de aceite:* cada alteração aparece em `/admin/audit` com antes/depois; "Reverter" restaura o estado anterior e a própria reversão aparece na lista.

---

## Qualidade das Respostas

`services/chat/feedback_service.py` (pedido de avaliação) e `services/shared/qa_case_service.py` (tabela `qa_case`). Página `/admin/quality`.

**Objetivo:** descobrir onde o assistente responde mal ou não sabe responder, para o administrador corrigir a base de conhecimento.

Fluxo:
1. Cada resposta do agente termina com *"Essa resposta foi útil? Responda 1 👍 ou 2 👎"*. Comandos (`/menu`, `/about`), bloqueios de guardrail e falhas não pedem avaliação. O pedido é feito por texto, igual no WhatsApp e no Telegram.
2. A pergunta, a resposta (sem o nome do usuário) e os metadados dos trechos usados ficam no Redis por 30 minutos, à espera da avaliação.
3. Se a próxima mensagem for "1" ou "2", o caso é gravado e o usuário recebe um agradecimento, sem chamar o LLM e sem gastar a cota diária. Qualquer outra mensagem segue normalmente (e uma nova resposta substitui o pedido pendente).
4. Quando o assistente **não encontra resposta**, o caso é gravado direto como "sem resposta" e não há pedido de avaliação. A detecção (`message_router.is_no_answer`) considera "sem resposta" quando nenhum trecho foi recuperado e o texto contém expressões como "não encontrei".

No painel, a aba **Mal avaliadas** lista as respostas 👎 e a aba **Sem resposta** lista as perguntas não respondidas, agrupando as parecidas (palavras em comum) para indicar os assuntos que mais faltam. O topo mostra a satisfação dos últimos 30 dias (% de 👍 entre as avaliadas). Em cada caso o admin registra uma nota e o status (`new`, `reviewed`, `converted`); **Converter em documento** marca o caso e abre o formulário da base de conhecimento com o título preenchido pela pergunta. Mudanças de status/nota são auditadas e podem ser revertidas.

| Tipo | O que é guardado |
|------|------------------|
| `up` | só o `chat_id` e a data |
| `down` | pergunta, resposta e metadados dos trechos (título/fonte, sem o texto) |
| `no_answer` | pergunta, resposta e metadados dos trechos |

**RN18 — Avaliação das respostas:** toda resposta do agente pede avaliação "1" (útil) ou "2" (não útil); a avaliação vale só para a última resposta, por até 30 minutos, e não conta no limite diário de mensagens.

**RN19 — Minimização no feedback (LGPD):** pergunta e resposta só são guardadas quando a resposta é avaliada como não útil ou quando o assistente não encontra resposta; avaliações positivas guardam apenas o tipo. Os casos são apagados após `QA_CASE_RETENTION_DAYS` (purga diária) e o painel mostra só os 4 últimos dígitos do usuário.

**Histórias de usuário:**
- Como estudante, quero dizer se a resposta me ajudou, para que o assistente melhore. *Critérios de aceite:* respondo "1" ou "2" logo após a resposta e recebo um agradecimento; a avaliação não consome minhas mensagens do dia.
- Como administrador, quero ver as respostas mal avaliadas e as perguntas sem resposta, para saber que documentos adicionar. *Critérios de aceite:* os casos aparecem em `/admin/quality`, perguntas parecidas aparecem agrupadas e "Converter em documento" abre o cadastro com o título preenchido.

---

## System Prompt Editável

`services/shared/prompt_service.py` — tabela `prompt_version` (uma versão ativa).

- Prompt ativo mantido em memória; `get_system_prompt()` é síncrono e sem I/O.
- Editar cria uma nova versão ativa; versões antigas podem ser **restauradas**.
- Vale imediatamente, sem restart. Fonte única é o banco (sem `SYSTEM_PROMPT` no env); sem versão, o agente usa um fallback embutido.
- Mantém o placeholder `{AGENT_NAME}`; limite de 20 000 caracteres.
- Regras de guardrail `instruct` são anexadas ao final num bloco "Regras de comportamento".
- Usado tanto pelo agente ReAct quanto pelo RAG simples.

---

## Guardrails

`services/shared/guardrail_service.py` — tabela `guardrail`, regras compiladas em memória.

| Escopo | Onde atua | Ações |
|--------|-----------|-------|
| `input` | `message_router`, antes do agente | `block` (responde sem chamar o LLM), `replace` |
| `output` | sobre a resposta, antes de salvar/enviar | `mask` (trecho → `***`), `replace`, `block` |
| `prompt` | anexado ao system prompt | `instruct` (orientação ao modelo; sem garantia dura) |

Campos: `name`, `description`, `scope`, `match_type` (`keyword` \| `regex`), `pattern`, `action`, `response`, `instruction`, `priority`, `enabled`.

Segurança: regex validada ao salvar (padrão até 500 caracteres, detecção de quantificadores aninhados contra ReDoS; no teste, texto até 2000 caracteres e timeout de 2 s). `block` sem texto responde "Desculpe, não posso ajudar com isso."; `mask` troca o trecho por `***`. O texto do usuário nunca é logado. `POST /admin/api/guardrails/test` aplica as regras a um texto de exemplo sem enviar nada.

---

## Skills

`services/shared/skill_service.py` — tabela `skill` (slug, nome, descrição, corpo markdown até 20 000 chars).

- O agente recebe só o **catálogo** (slug, nome, descrição) no prompt.
- Quando a pergunta se encaixa, chama a tool **`load_skill`** para ler as instruções completas.
- CRUD em `/admin/skills`; cache em memória recarregado a cada escrita.

---

## Base de Conhecimento (RAG editável)

`services/shared/knowledge_service.py` — tabela `knowledge_document` + coleção pgvector própria `conhecimento_agente` (**não toca nos manuais** já indexados).

- Documento dividido em chunks (`KNOWLEDGE_CHUNK_SIZE` / `KNOWLEDGE_CHUNK_OVERLAP`) com ids determinísticos; atualizar faz upsert e remove só as sobras; falha no banco desfaz os vetores.
- Limite por documento: `KNOWLEDGE_MAX_CHARS`. Upload de `.txt` e `.md`.
- Tool `search_knowledge` no agente (top-k = `KNOWLEDGE_TOP_K`), ao lado de `search_manuals`.
- `/admin/knowledge`: criar, editar (reindexa), excluir, upload e **testar a recuperação**.
- **Reindexar tudo:** `reindex_all()` revetoriza todos os documentos, um por vez, em background (`start_reindex`), sem tirar o assistente do ar. O progresso (total, feitos, falhas, situação) fica no Redis em `suap:knowledge:reindex` (expira em 7 dias) e a tela mostra uma barra que se atualiza sozinha. Falha num documento é registrada e não interrompe os demais; só uma reindexação roda por vez. O disparo é auditado.
- **Ver chunks:** cada documento mostra os pedaços gravados no pgvector, consultando direto as tabelas do `langchain_postgres` (`langchain_pg_embedding` filtrada pela coleção em `langchain_pg_collection` e por `cmetadata->>'doc_id'`).
- A coleção dos manuais é construída fora do app (`../pipeline`) e não é reindexada por aqui.

**RN16 — Reindexação única:** só uma reindexação completa da base de conhecimento pode rodar por vez; um documento com falha não impede os demais.

---

## Mensagem em Massa (Broadcast)

`services/admin/broadcast_service.py` — tabela `broadcast`. Página `/admin/broadcast`.

Permite ao administrador enviar um aviso (ex.: prazo de matrícula, manutenção do SUAP) a todos os usuários do assistente.

1. **Redigir:** o texto (até 4000 caracteres) vira um rascunho. Nada é enviado.
2. **Pré-visualizar:** a tela mostra quantos destinatários existem e uma amostra com só os 4 últimos dígitos de cada número.
3. **Confirmar:** o envio roda em background, um destinatário por vez, com intervalo de `BROADCAST_DELAY_SECONDS` (o WAHA ainda aplica o próprio atraso anti-ban, RN14). A tela acompanha enviadas, falhas e total.
4. **Cancelar:** descarta o rascunho ou interrompe o envio antes da próxima mensagem.

- **Destinatários (RN17):** usuários que aceitaram os Termos de Uso e que o assistente atenderia hoje — fora da blocklist e, com a allowlist ativa, dentro dela.
- Criar, enviar e cancelar ficam na [auditoria](#auditoria-do-painel) (não reversíveis: mensagem entregue não volta).
- **LGPD:** a tela nunca mostra o número completo; o registro guarda só texto, autor e contadores, sem a lista de destinatários.
- Limitação: se o processo reiniciar no meio do envio, o registro fica como "sending"; cancelar encerra o registro sem reenviar.

**RN17 — Destinatários do broadcast:** a mensagem em massa só vai para quem aceitou os Termos de Uso e não está bloqueado (respeitando a allowlist quando ativa), e só é enviada depois de o administrador confirmar o número de destinatários.

**História de usuário:** como administrador, quero avisar todos os estudantes sobre um prazo, para que eles recebam a informação no canal que já usam. *Critérios de aceite:* vejo quantas pessoas receberão antes de confirmar; acompanho enviadas e falhas; posso interromper o envio.

---

## Indicadores e Exportações

`services/shared/dashboard_service.py` (indicadores) e `services/admin/export_service.py` + `routes/admin/exports.py` (exportações). Os indicadores aparecem no Resumo do painel (`/admin`), com seletor de período (7, 30 ou 90 dias) e gráficos (Chart.js).

Indicadores do período, dia a dia:
- **Tempo de resposta** p50 e p95: metade das respostas sai em até p50; só 5% demoram mais que p95. Vem da duração registrada no log de acesso para cada mensagem respondida.
- **Taxa de erro:** mensagens que falharam ÷ (respondidas + falhas).
- **Bloqueios de guardrail:** mensagens ou respostas barradas pelas regras de segurança.
- **Usuários ativos:** pessoas diferentes atendidas no período.
- **Satisfação:** avaliações 👍 ÷ (👍 + 👎), e **taxa de sem resposta:** perguntas sem resposta ÷ respondidas (casos de qualidade).
- **Tokens e custo estimado por modelo:** tokens consumidos × tabela de preços `MODEL_PRICES_JSON` (US$ por 1 milhão de tokens de entrada e de saída). Modelo sem preço configurado aparece sem custo e fica fora da soma. O custo também aparece em `/admin/usage`.

Exportações (botões no Resumo e nas telas de Logs, Uso e Auditoria):

| Arquivo | Conteúdo |
|---------|----------|
| `/admin/logs/export.csv` | Log de acesso, com os mesmos filtros da tela |
| `/admin/usage/export.csv?days=` | Uso diário (mensagens, usuários, chamadas e tokens) |
| `/admin/export/quality.csv?kind=` | Casos de qualidade (avaliações e perguntas sem resposta) |
| `/admin/export/audit.csv` | Auditoria, com os filtros da tela e o antes/depois em JSON |
| `/admin/api/knowledge/export.json` | Todos os documentos da base de conhecimento (backup) |

- Até 5.000 linhas por arquivo, geradas em streaming.
- **Injeção de fórmula:** texto que começa com `=`, `+`, `-`, `@`, TAB ou quebra de linha ganha um apóstrofo na frente, para que planilhas não o executem como fórmula.
- **LGPD:** o número do usuário (`chat_id`) sai mascarado (só os 4 últimos dígitos) e o nome não é exportado. A pergunta e a resposta dos casos de qualidade saem como estão, pois a revisão é a finalidade desses casos. Cada download fica registrado no log de acesso (`admin_export`, com o tipo exportado).

**RN21 — Exportação de dados:** exportações do painel exigem administrador autenticado, mascaram o identificador do usuário, neutralizam fórmulas de planilha e ficam registradas no log de acesso.

**História de usuário:** como administrador, quero ver no resumo a rapidez, os erros, a satisfação e o custo do assistente em um período, e baixar os dados em planilha, para acompanhar a qualidade do serviço e prestar contas. *Critérios de aceite:* o resumo mostra os indicadores e gráficos de 7, 30 ou 90 dias; cada exportação baixa um arquivo com o número do usuário mascarado.

---

## Saúde e Alertas

`services/admin/health_service.py` e `services/admin/alert_service.py`. Página `/admin/health`.

**Saúde.** O painel verifica, a cada 30 segundos, se cada peça de que o assistente depende responde: banco de dados (Postgres), Redis, as coleções de manuais e da base de conhecimento no banco vetorial, a API do SUAP, a OpenAI e cada plataforma de mensagem habilitada (WAHA: sessão do WhatsApp conectada; Telegram: webhook registrado e sem erro recente). A OpenAI não recebe chamada de teste, porque cada chamada tem custo: conta como saudável com a chave configurada, e a tela mostra a data do último consumo registrado. Cada verificação tem tempo limite; erros aparecem só pelo tipo, sem mensagens que possam conter segredos. A tela também mostra o último atendimento que falhou (do log de acesso).

- **Reconectar:** para WAHA reinicia a sessão do WhatsApp; para Telegram registra o webhook de novo. O botão exige CSRF e a ação fica na auditoria (área `provider`, sem reversão).
- O contrato dos providers (`providers/base.py`) ganhou `health()` e `reconnect()`; quem não implementa responde "sem verificação" e "não suportado".
- **`/health` público:** responde só `{"status": "ok"}` (200) ou `{"status": "degraded"}` (503) conforme Postgres e Redis, para monitoramento externo. Não chama serviços pagos nem expõe detalhes.

**Alertas.** Uma tarefa de fundo (`alert_loop`, iniciada junto com os workers da fila) avalia a cada `ALERT_INTERVAL_SECONDS`:

| Regra | Dispara quando |
|-------|----------------|
| Fila cheia | pendentes acima de `ALERT_QUEUE_MAX_PENDING` |
| Item travado | mensagem em atendimento há mais de `ALERT_PROCESSING_MAX_SECONDS` |
| Taxa de falhas | nos últimos 15 min, com pelo menos 5 atendimentos, a proporção de falhas passa de `ALERT_ERROR_RATE` |
| Componente fora | uma verificação de saúde falha `ALERT_PROBE_FAILURES` vezes seguidas |
| Limite excedido | alguma mensagem foi recusada por limite diário ou orçamento de tokens desde a última verificação (só a contagem, sem identificar o usuário) |

- Canais: Telegram (`ALERT_TELEGRAM_CHAT_ID`, exige o provider `telegram` habilitado) e e-mail (`ALERT_SMTP_*`). Cada canal fica desligado se não configurado; sem nenhum, o alerta vai só para o log da aplicação.
- Deduplicação: a mesma regra não alerta de novo antes de `ALERT_COOLDOWN_SECONDS` (chave `suap:alert:cooldown:<regra>` no Redis).
- Outras partes do sistema alertam por `alert_service.notify(regra, mensagem)` (ex.: orçamento de tokens excedido).

**RN20 — Conteúdo dos alertas:** alertas enviados para fora do sistema (Telegram, e-mail) levam apenas contagens e nomes de componentes, nunca número de telefone, matrícula ou conteúdo de conversa.

**História de usuário:** como administrador, quero ser avisado quando a fila trava, os erros sobem ou uma dependência cai, e poder reconectar o WhatsApp pelo painel, para restabelecer o atendimento sem acessar o servidor. *Critérios de aceite:* a tela mostra a situação de cada componente; um problema persistente gera um único aviso por período de silêncio; "Reconectar" fica registrado na auditoria.

---

## Agente ReAct

`services/chat/agent_orchestrator.py` — loop de tool calling (máx. `AGENT_MAX_ITERATIONS`; ao atingir o limite força uma síntese). Recebe o histórico da conversa (`THREAD_HISTORY_PAIRS` pares) para perguntas de acompanhamento.

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
| Tools SUAP (abaixo) | `services/chat/mcp_client.py` |

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
| `/admin` | Resumo: fila, regras de acesso, atendimentos do dia, versão do prompt, indicadores do período (latência, erros, guardrails, usuários, satisfação, custo) com gráficos e exportações |
| `/admin/queue` | Fila em abas (pendentes, em atendimento, falhas, atendidas), cancelar/reenfileirar, auto-refresh |
| `/admin/prompt` | Editor do system prompt, histórico e restauração |
| `/admin/skills` | CRUD de skills e de guardrails, com botão "testar" |
| `/admin/knowledge` | CRUD de documentos, upload, teste de busca, reindexar tudo e ver chunks |
| `/admin/access` | Allowlist, blocklist e limites diários (padrão e por número) |
| `/admin/users` | Busca de usuários, detalhe com uso do dia, bloquear, limite próprio e apagar dados (LGPD) |
| `/admin/logs` | Log de acesso com filtros |
| `/admin/audit` | Auditoria das alterações dos admins, com diff e reverter |
| `/admin/health` | Saúde dos componentes, último atendimento com falha e reconectar provider |
| `/admin/quality` | Respostas mal avaliadas, perguntas sem resposta (agrupadas) e satisfação |
| `/admin/broadcast` | Mensagem em massa: redigir, pré-visualizar destinatários, confirmar, acompanhar e cancelar |

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

As tabelas são criadas/migradas automaticamente (`init_db`): `user_auth`, `knowledge_document`, `access_rule`, `access_log`, `prompt_version`, `skill`, `guardrail`, `admin_user`, `llm_usage`, `admin_audit`, `qa_case`, `broadcast` (colunas novas entram via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). Em seguida carregam os caches de ACL, prompt e skills/guardrails, os providers (`startup()`) e as tasks de background (recuperação da fila, workers, `_stale_cleaner`, retenção do log, alertas).

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
| `MAX_DAILY_MESSAGES` | `25` | Limite diário por aluno, enquanto o painel não define outro padrão |
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
| `QA_CASE_RETENTION_DAYS` | `90` | Retenção dos casos de qualidade (feedback) |
| `MODEL_PRICES_JSON` | preços de `gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo` | USD por 1M tokens, `{"modelo": [entrada, saída]}`, para o custo estimado |
| `DAILY_TOKEN_BUDGET` | `0` | Orçamento diário de tokens por usuário (0 = sem limite) |
| `ALERT_TELEGRAM_CHAT_ID` | — | Chat do Telegram que recebe alertas (vazio = desligado) |
| `ALERT_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_TO` | — / `587` | E-mail de alertas (host vazio = desligado) |
| `ALERT_QUEUE_MAX_PENDING` | `50` | Alerta com mais itens pendentes que isso |
| `ALERT_PROCESSING_MAX_SECONDS` | `180` | Alerta com item em atendimento há mais tempo que isso |
| `ALERT_ERROR_RATE` | `0.2` | Alerta com taxa de falhas acima disso |
| `ALERT_PROBE_FAILURES` | `3` | Falhas seguidas de uma verificação de saúde antes de alertar |
| `ALERT_INTERVAL_SECONDS` | `60` | Intervalo entre rodadas de verificação dos alertas |
| `ALERT_COOLDOWN_SECONDS` | `1800` | Silêncio mínimo entre dois alertas da mesma regra |
| `BROADCAST_DELAY_SECONDS` | `3` | Intervalo entre envios de mensagem em massa |

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
| `GET` | `/health` | Status mínimo (Postgres e Redis) para monitoramento externo |

### Painel admin (sessão + CSRF nas escritas)

| Método | Path | Descrição |
|--------|------|-----------|
| `GET/POST` | `/admin/login` · `POST /admin/logout` | Sessão |
| `GET` | `/admin?days=7\|30\|90` | Resumo e indicadores |
| `GET` | `/admin/logs/export.csv` · `/admin/usage/export.csv` · `/admin/export/quality.csv` · `/admin/export/audit.csv` | Exportações CSV |
| `GET` | `/admin/api/knowledge/export.json` | Exportação da base de conhecimento |
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
| `GET/POST` | `/admin/api/knowledge/reindex` | Progresso / dispara a reindexação completa (409 se já rodando) |
| `GET` | `/admin/api/knowledge/{id}/chunks` | Chunks gravados de um documento |
| `GET/POST` | `/admin/broadcast` · `POST /admin/broadcast/{id}/send` · `/cancel` | Mensagem em massa |
| `GET` | `/admin/broadcast/{id}/progress` | Parcial HTMX do progresso |
| `GET/POST` | `/admin/access` · `POST /admin/access/remove` | Allowlist / blocklist |
| `POST` | `/admin/access/limit` · `/admin/access/user-limit` | Limite diário padrão / por número |
| `GET` | `/admin/users` · `/admin/users/{id}` | Busca e detalhe de usuário |
| `POST` | `/admin/users/{id}/block` · `/unblock` · `/limit` · `/erase` | Bloquear, desbloquear, limite próprio, apagar dados |
| `GET` | `/admin/logs` | Log de acesso |
| `GET` | `/admin/audit` · `POST /admin/audit/{id}/revert` | Auditoria e reversão |
| `GET` | `/admin/health` · `/admin/health/table` · `POST /admin/health/{provider}/reconnect` | Saúde, parcial HTMX e reconexão |
| `GET` | `/admin/quality?tab=down\|no_answer` · `POST /admin/quality/{id}` · `/{id}/convert` | Casos de qualidade: nota/status e converter em documento |

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
- Alterações feitas no painel ficam auditadas com autor e estado antes/depois (RN15).
- Alertas externos não levam dado pessoal (RN20); o `/health` público não expõe detalhes.
- Feedback guarda conteúdo só em 👎 e "sem resposta", com retenção de `QA_CASE_RETENTION_DAYS` e usuário mascarado no painel (RN19).
- Exclusão de dados a pedido do titular em `/admin/users`, auditada sem o número apagado; o número no consumo de tokens é anonimizado após a retenção (RN24).
- Exportações mascaram o número do usuário, neutralizam fórmulas de planilha e ficam registradas no log (RN21).
