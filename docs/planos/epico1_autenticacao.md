# Plano — Épico 1: Autenticação e Gestão de Sessão

> Requisitos cobertos: RF01, RF02, RF03, RF04 | Regras: RN01, RN02, RN03

**Depende de:** Épico 0 (DB + Redis prontos)

---

## Objetivo

Vincular o `chat_id` do WhatsApp a uma matrícula SUAP, persistir o token no Redis com TTL correto e expor um fluxo de login via interface web segura.

---

## Arquivos a criar / modificar

| Arquivo | Ação |
|---------|------|
| `services/auth_service.py` | Criar |
| `services/session_service.py` | Criar |
| `models/database.py` | Criar (model `UserAuth`) |
| `web/login.html` | Criar |
| `routes/webhook.py` | Criar (extrair de `main.py`) |
| `utils/security.py` | Criar |
| `config.py` | Atualizar |

---

## Passos

### 1.1 — `models/database.py`

Definir modelos SQLAlchemy async:

```python
class UserAuth(Base):
    __tablename__ = "user_auth"
    id, chat_id (unique), matricula, created_at, updated_at
```

### 1.2 — `services/session_service.py`

Responsável por toda operação no Redis:

```python
async def get_token(chat_id) -> str | None
async def set_token(chat_id, token, ttl_seconds)   # RN02: TTL da API ou 8h
async def delete_token(chat_id)                     # RF04: /sair
async def is_authenticated(chat_id) -> bool
async def increment_rate(chat_id) -> int            # RN06: contador diário
async def get_onboarding_link(uuid) -> str | None
async def set_onboarding_link(uuid, chat_id, ttl=900)
```

Regras:
- Chave do token: `suap:token:{chat_id}`
- Chave do rate: `suap:rate:{chat_id}:{YYYYMMDD_BRT}` — TTL calculado até meia-noite BRT (RN06)
- Token nunca é logado (RN03)

### 1.3 — `services/auth_service.py`

```python
async def generate_onboarding_link(chat_id) -> str   # RF01: UUID + Redis
async def login_with_suap(chat_id, matricula, senha) -> Result  # RF03
async def logout(chat_id)                            # RF04
async def get_linked_matricula(chat_id) -> str | None
```

Fluxo `login_with_suap`:
1. Envia `POST /api/token/` ao SUAP com `username=matricula`, `password=senha`
2. Em caso de sucesso: persiste `UserAuth` no PostgreSQL (RN01), salva token no Redis com TTL (RN02)
3. Em caso de erro 401/SUAP indisponível: retorna mensagem amigável (RF03)
4. Nunca loga senha, CPF ou token (RN03)

### 1.4 — `web/login.html`

Página HTML simples (sem framework):
- Campos: matrícula, senha (obrigatórios) — RF02
- Validação client-side antes do envio
- POST para `/auth/login?token={uuid}`
- Exibe mensagem de sucesso ("Pode voltar ao WhatsApp") ou erro amigável

### 1.5 — Rota `/auth/login` no FastAPI

```python
POST /auth/login?token={uuid}
Body: { matricula, senha }
```

1. Valida UUID no Redis → obtém `chat_id` (RF01)
2. Chama `auth_service.login_with_suap`
3. Retorna resposta HTML (não JSON) para o usuário final

### 1.6 — `utils/security.py`

```python
def sanitize_log(data: dict) -> dict   # Remove keys: token, senha, password, cpf
```

Usar em todos os `logger.info/debug` que logam dicts de request/response.

### 1.7 — Fluxo `/sair` (RF04)

No handler de mensagens (routes/webhook.py):
```python
if message.strip() == "/sair":
    await session_service.delete_token(chat_id)
    await auth_service.logout(chat_id)  # mantém user_auth mas limpa Redis
    return "Sessão encerrada. Na próxima mensagem você receberá o link de login."
```

---

## Critérios de Aceite (por RF)

- **RF01:** Número sem vínculo recebe link único; número com sessão ativa prossegue.
- **RF02:** Formulário valida campos antes de enviar; erros de campo mostram mensagem clara.
- **RF03:** Login válido → token no Redis; login inválido → mensagem amigável; SUAP down → mensagem amigável.
- **RF04:** Após `/sair`, próxima mensagem aciona onboarding.
- **RN01:** `user_auth` possui o vínculo; token NÃO está na coluna.
- **RN02:** TTL do Redis igual ao retornado pelo SUAP (fallback 8h).
- **RN03:** Nenhum log contém token, senha ou CPF.
