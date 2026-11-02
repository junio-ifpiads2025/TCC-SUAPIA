# Plano: ampliar o painel admin do SUAPIA

## Context
O painel admin (`chat/routes/admin/*`, templates em `chat/web/admin/`) já cobre acesso, admins, base de conhecimento, prompt, skills, guardrails, fila, logs e uso. Faltam qualidade das respostas, rastreabilidade das ações dos admins, gestão de usuários, saúde do sistema e operação (alertas, broadcast, reindexação). Itens escolhidos: **1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13** (fora: 3 visualizador de conversas, 6 playground, 14 2FA).

Decisões do usuário:
- Feedback por **resposta em texto** ("1" útil / "2" não útil), igual em WAHA e Telegram, sem mexer nos provedores.
- Pergunta e resposta só são guardadas quando a resposta é 👎 ou o bot não encontrou resposta (LGPD).

Premissas verificadas no código:
- Construir sobre o layout novo (`routes/admin/`, `routes/chat/`, `services/{chat,shared,admin}/`). O refactor ainda está só parcialmente no git.
- Não há alembic. `init_db()` em `models/database.py` usa `create_all` mais `ALTER TABLE ... IF NOT EXISTS`. Colunas novas em tabelas existentes entram ali.
- A thread vive só no Redis (`thread_service`). `LlmUsage` não tem `chat_id` nem latência. A latência já existe em `AccessLog.duration_ms` (eventos `answered`/`failed`).
- `queue_service._process_item` descarta os metadados de `route()` (`resposta, _`). É lá que ficam os chunks do RAG e os sinais de "sem resposta".
- Padrão dos testes: `FastAPI()` + `TestClient` + `dependency_overrides` de `require_admin`/`verify_csrf`, com `monkeypatch` em funções `_db_*`. Todo serviço novo deve ter essa costura `_db_*`.
- Padrão de rota: `router` com prefixo `/admin`, `Depends(require_admin)`, `dependencies=[Depends(verify_csrf)]` nos POST, `render()` de `common.py`, registro em `routes/admin/__init__.py`, link no array do nav em `web/admin/base.html`.

## Fase 0: fundações (`models/database.py`, `config.py`)
Novas tabelas (criadas pelo `create_all`):
- `AdminAudit`: `id, admin, action, entity, entity_id, before (JSON), after (JSON), reverted_by, created_at`.
- `QaCase`: `id, kind (up|down|no_answer), chat_id, question, answer, chunks (JSON), status (new|reviewed|converted), note, created_at`. `question`, `answer` e `chunks` ficam nulos em `up`.
- `Broadcast`: `id, admin, text, status (draft|sending|done|cancelled), total, sent, failed, created_at`.

Colunas novas (com `ALTER ... IF NOT EXISTS` em `init_db`):
- `llm_usage.chat_id` (nullable, indexada).
- `access_rule.daily_limit` (nullable, override por usuário).

Config em `config.py` (único lugar com `os.getenv`):
- `MODEL_PRICES` (USD por 1M tokens, entrada e saída, por modelo).
- `QA_CASE_RETENTION_DAYS`.
- `ALERT_TELEGRAM_CHAT_ID` e `ALERT_SMTP_*` (canais desligados se vazios).
- Limiares de alerta: tamanho da fila, idade do item em processamento, taxa de erro.
- `BROADCAST_DELAY_SECONDS`.
- `DAILY_TOKEN_BUDGET`.

## Fase 1: auditoria dos admins (item 2)
- `services/admin/audit_service.py`: `record(action, entity, entity_id, before, after)` e `list(filters)`. Fire-and-forget como `access_log_service`, com costura `_db_*`.
- O ator vem de um `ContextVar current_admin` definido em `require_admin` (`routes/admin/common.py`, é `async`, então roda na mesma task do endpoint). Isso evita mudar a assinatura de todos os serviços.
- Chamar `record()` dentro das funções de mutação, onde o "antes" já está disponível:
  - `prompt_service` (save/activate)
  - `skill_service`
  - `guardrail_service`
  - `acl_service` (regras e modo aberto)
  - `knowledge_service` (create/update/delete)
  - `admin_user_service`
- Substituir as chamadas `log_admin` de mutações por `record()`. Manter `log_admin` só para login/logout/falha de login e ações de fila.
- Página `/admin/audit` (`routes/admin/audit.py` + `audit.html`): filtros (admin, entidade, período) e diff antes/depois.
- Reverter: dicionário `entity → função` em `audit_service`. Prompt reativa a versão anterior (reusa `prompt_service.activate`). Skill, guardrail, regra de acesso e documento reaplicam o `before`. A reversão gera uma nova entrada de auditoria e marca `reverted_by` na original.

## Fase 2: feedback e casos de qualidade (itens 1 e 5)
- `services/chat/feedback_service.py`:
  - `arm(chat_id, question, answer, chunks)` grava no Redis `suap:fb:pending:<chat_id>` com TTL curto.
  - `handle(chat_id, text)` interpreta "1"/"2" quando existe pendência.
  - `record_case(kind, ...)` grava em `QaCase`.
- `message_router.route()` devolve também `no_answer: bool` nos metadados. Verdadeiro quando `rag_metadata` é vazio e a resposta contém um dos textos de "não encontrei" de `rag_agent.py` e `_run_knowledge`.
- `queue_service._process_item`:
  - Usa os metadados que hoje descarta.
  - Se `no_answer`, grava um `QaCase(kind=no_answer)` com pergunta, resposta e chunks.
  - Caso contrário, arma o feedback e anexa o pedido "Foi útil? Responda 1 👍 ou 2 👎" à resposta.
- Em `enqueue` (ou no início de `route`), se há pendência e o texto é "1" ou "2": registra o `QaCase`, responde "Obrigado pelo feedback" e **não** chama o LLM. 👍 grava só o `kind=up` sem conteúdo. 👎 grava pergunta, resposta e chunks.
- Retenção: o `retention_loop` existente passa a purgar `QaCase` pelo `QA_CASE_RETENTION_DAYS`.
- Admin `/admin/quality` (`routes/admin/quality.py` + `quality.html`):
  - Abas "Mal avaliadas" e "Sem resposta", e contagem de satisfação.
  - Nota do admin e status.
  - Ação "Converter em documento": abre o formulário de `knowledge` com o título preenchido e marca o caso como `converted`.
  - A aba "Sem resposta" agrega perguntas parecidas para indicar quais manuais adicionar.

## Fase 3: usuários e limites (itens 8 e 7)
Usuários (`routes/admin/users.py` + `users.html`, `services/admin/user_admin_service.py`):
- Busca por matrícula ou `chat_id` em `UserAuth`.
- Detalhe: aceite dos termos, eventos recentes do `AccessLog`, uso do dia.
- Bloquear/desbloquear reusa `acl_service` (`AccessRule kind=block`).
- Apagar dados (LGPD), novo `user_data_service.erase(chat_id)`:
  - Remove `user_auth`, `access_log`, `access_rule` e `qa_case` do usuário.
  - Remove no Redis as chaves `token`, `profile`, `thread`, `rate` e `fb`.
  - Remove da fila os itens do usuário (varrendo as listas `pending/processing/failed/done`).
  - Reusa `acl_service.clear_user_session`.
  - Exige confirmação e é auditada.

Limites:
- O `ContextVar current_chat_id` é definido em `_process_item`. `usage_service.record` o lê e grava `llm_usage.chat_id`. Verificar com teste que o contexto chega às threads de `asyncio.to_thread`.
- Limite diário de mensagens passa a ser configurável pelo painel: padrão global em `AppSetting` (hoje fixo em `MAX_DAILY_MESSAGES=25`, inclusive o texto da mensagem) e override por usuário em `access_rule.daily_limit`. `session_service.increment_rate`/`enqueue` passam a ler o limite efetivo.
- Orçamento diário de tokens por usuário: contador Redis `suap:tokens:<chat_id>:<data>` incrementado em `usage_service.record`. Ao exceder, `enqueue` recusa com mensagem clara e dispara alerta (Fase 5).
- UI: campos de limite na página `access.html` e na página do usuário.

## Fase 4: dashboard e exportações (itens 4 e 10)
- `services/shared/dashboard_service.py` (ou extensão de `usage_service.report`):
  - Latência p50/p95 por dia com `percentile_cont` sobre `AccessLog.duration_ms` onde `event='answered'`.
  - Taxa de erro (`failed` / total).
  - Bloqueios de guardrail por dia (eventos `guardrail_input`/`guardrail_output`).
  - Usuários ativos.
  - Satisfação (de `QaCase`) e taxa de "sem resposta".
  - Custo estimado e tokens por modelo (`MODEL_PRICES` × `LlmUsage`).
- `dashboard.html` (rota em `routes/admin/auth.py` l.144) ganha gráficos com Chart.js, já usado em `usage.html`, e seletor de período. A página de uso permanece.
- Exportação CSV/JSON via `StreamingResponse` com `csv` da stdlib:
  - `/admin/logs/export.csv`, reusando os filtros de `logs.py`.
  - Uso, casos de qualidade e auditoria.
  - `/admin/api/knowledge/export.json`.
  - Neutralizar injeção de fórmula (prefixar `=`, `+`, `-`, `@` com apóstrofo).

## Fase 5: saúde e alertas (itens 9 e 12)
Saúde:
- `services/admin/health_service.py` com sondas: Postgres (`SELECT 1`), Redis (`ping`), vector store, SUAP (`SUAPMCPClient`), WAHA e Telegram.
- Adicionar `health()` e `reconnect()` ao contrato de `providers/base.py` e às implementações `waha.py` (reiniciar sessão) e `telegram.py` (refazer `setWebhook`).
- OpenAI sem chamada paga: configuração presente mais a última `LlmUsage` bem-sucedida.
- Página `/admin/health` (`routes/admin/health.py`) com atualização via htmx e "última falha" vinda do `AccessLog`. Botão reconectar protegido por CSRF e auditado.
- Rota pública mínima `/health` (só status, sem detalhes) para monitoramento externo.

Alertas:
- `services/admin/alert_service.py` com canais Telegram (via `messaging_client`) e SMTP (`smtplib`), cada um desligado quando não configurado.
- `alert_loop` iniciado em `main.py` junto de `_queue_worker`, `_stale_cleaner` e `retention_loop`. Regras:
  - fila acima do limite ou item em processamento por tempo demais;
  - taxa de erro acima do limiar;
  - sonda de saúde falhando N vezes seguidas;
  - orçamento ou cota excedidos.
- Deduplicação com chave Redis de cooldown por regra.

## Fase 6: reindexação e broadcast (itens 11 e 13)
Reindexação:
- `knowledge_service.reindex_all()`: percorre `list_documents` e chama `_indexar` (síncrono, via `asyncio.to_thread`). Roda em background com progresso (total, feitos, falhas) guardado no Redis.
- UI em `knowledge.html`: botão "Reindexar tudo", barra de status e visão de chunks por documento (consulta ao pgvector filtrando por `doc_id`; confirmar o esquema da tabela de embeddings do `langchain_postgres` antes de implementar).
- A coleção de manuais é construída fora do app (`../pipeline`) e **não** entra aqui.

Broadcast:
- `routes/admin/broadcast.py` + `broadcast.html`, com `Broadcast` e `services/admin/broadcast_service.py`.
- Fluxo: redigir texto → pré-visualizar destinatários (usuários de `UserAuth` com termos aceitos, excluindo bloqueados) → confirmar → envio em background por `messaging_client.enviar_texto_async`, com intervalo `BROADCAST_DELAY_SECONDS` (WAHA tem atraso anti-ban).
- Progresso e cancelamento, contagem de enviados e falhas. Tudo auditado.

## Ordem de entrega
0 → 1 → 2 → 3 → 4 → 5 → 6. Cada fase é independente depois da 0 e termina com testes passando e seu link no nav.

## Verificação
- Testes novos por serviço e por rota, no padrão atual (`TestClient`, `dependency_overrides`, `monkeypatch` em `_db_*`). Rodar `pytest` a partir de `chat/`.
- Casos a cobrir:
  - auditoria: grava antes/depois e reverte;
  - feedback: "1"/"2" com e sem pendência, e nenhum conteúdo persistido em 👍;
  - `no_answer` detectado;
  - cota excedida recusa a mensagem;
  - apagamento LGPD limpa Postgres e Redis;
  - CSV neutraliza fórmulas;
  - `ContextVar` chega ao `usage_service.record` em thread.
- Ponta a ponta: subir o app (skill `run`), enviar mensagens pelo Telegram/WAHA de teste e conferir cada tela. Fluxo principal: pergunta → resposta com pedido de feedback → "2" → caso em `/admin/quality` → converter em documento → reindexar → reperguntar.
- Conferir no navegador o dashboard em tema claro, os gráficos e o envio de broadcast para um único destinatário de teste.
