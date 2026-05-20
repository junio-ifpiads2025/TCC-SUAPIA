# Fix — Sessão Persistente com Refresh Token

## Problema

O token de acesso SUAP expira (geralmente em 8–24h). Quando isso acontece, o aluno
recebe o link de login novamente e precisa informar matrícula e senha — mesmo que
tenha usado o bot poucas horas antes. Isso degrada significativamente a experiência.

## Por que não hashear o token?

Hash é **unidirecional** — você não consegue recuperar o valor original a partir do hash.
Para chamar a API do SUAP (consultar notas, faltas, etc.) o token precisa ser enviado
literalmente no header `Authorization: Bearer <token>`. Se estiver hasheado, é impossível usá-lo.

Portanto: **hash não serve para tokens que precisam ser reutilizados**.

## Solução — Refresh Token Criptografado

O SUAP retorna dois tokens no login:

| Token | Duração | Finalidade |
|-------|---------|------------|
| `access` | ~8h | Autenticar chamadas à API do SUAP |
| `refresh` | ~30 dias | Obter novo `access` sem pedir senha |

A estratégia é guardar cada um no lugar certo:

```
Login SUAP
   ├── access token  → Redis (TTL curto, expira junto com o SUAP)
   └── refresh token → PostgreSQL (criptografado com Fernet/AES)
```

### Fluxo quando o aluno manda uma mensagem

```
enqueue(chat_id, content)
   ├── access token no Redis? → usa direto (caminho feliz)
   └── não tem (expirou ou servidor reiniciou) →
         ├── busca refresh token criptografado no PostgreSQL
         ├── descriptografa com FERNET_SECRET (variável de ambiente)
         ├── POST /api/token/refresh no SUAP → novo access token
         ├── salva novo access no Redis (TTL renovado)
         └── processa a mensagem normalmente — aluno não percebe nada

         caso o refresh também esteja expirado (~30 dias sem usar):
         └── envia link de login (comportamento atual)
```

### Por que criptografia e não plaintext?

O PostgreSQL é um banco persistente e potencialmente auditável. Armazenar o refresh
token em texto puro violaria os requisitos RN01 e RN03 (token nunca deve ficar exposto
em armazenamento persistente sem proteção). Com Fernet (AES-128-CBC + HMAC-SHA256),
o token só pode ser lido por quem possui a `FERNET_SECRET`.

---

## O que precisa ser implementado

### 1. `config.py`

Adicionar a chave de criptografia:

```python
FERNET_SECRET = os.getenv("FERNET_SECRET", "")
```

Gerar uma chave válida:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Adicionar nos `.env`:

```env
FERNET_SECRET=<chave gerada acima>
```

---

### 2. `models/database.py` — coluna `refresh_token` em `UserAuth`

```python
# Refresh token criptografado com Fernet — nunca em texto puro (RN01, RN03)
refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
```

---

### 3. `services/auth_service.py`

**No `login_with_suap()`**, salvar o refresh token criptografado:

```python
from cryptography.fernet import Fernet
from config import FERNET_SECRET

def _fernet() -> Fernet:
    return Fernet(FERNET_SECRET.encode())

# Dentro de login_with_suap(), após obter os tokens do SUAP:
refresh_raw = data.get("refresh")
if refresh_raw and FERNET_SECRET:
    user.refresh_token = _fernet().encrypt(refresh_raw.encode()).decode()
```

**Nova função `refresh_access_token()`**:

```python
async def refresh_access_token(chat_id: str) -> bool:
    """
    Tenta renovar o access token usando o refresh token armazenado no PostgreSQL.
    Retorna True se conseguiu renovar, False se o refresh também expirou.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserAuth).where(UserAuth.chat_id == chat_id))
        user = result.scalar_one_or_none()

    if not user or not user.refresh_token or not FERNET_SECRET:
        return False

    try:
        refresh_raw = _fernet().decrypt(user.refresh_token.encode()).decode()
    except Exception:
        return False  # token corrompido ou chave trocada

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{SUAP_BASE_URL}/api/token/refresh",
                json={"refresh": refresh_raw},
            )
    except httpx.RequestError:
        return False

    if resp.status_code != 200:
        return False

    data = resp.json()
    new_access = data.get("access")
    if not new_access:
        return False

    ttl = int(data.get("expires_in", SESSION_TTL_SECONDS))
    await set_token(chat_id, new_access, ttl_seconds=ttl)
    logger.success("AUTH", f"Token renovado silenciosamente — chat_id={chat_id}")
    return True
```

---

### 4. `services/queue_service.py` — `enqueue()`

Substituir o bloco de autenticação:

```python
# Antes (comportamento atual):
if not await is_authenticated(chat_id):
    link = await generate_onboarding_link(chat_id)
    await enviar_texto_async(chat_id, f"... {link}")
    return

# Depois (com refresh silencioso):
if not await is_authenticated(chat_id):
    renovado = await refresh_access_token(chat_id)
    if not renovado:
        link = await generate_onboarding_link(chat_id)
        await enviar_texto_async(chat_id, f"... {link}")
        return
    # se renovado == True, continua o fluxo normalmente
```

---

## Resultado esperado

| Situação | Comportamento atual | Com o fix |
|----------|--------------------|-----------| 
| Token expirou (8h) | Pede login | Renova silenciosamente |
| Servidor reiniciou | Pede login | Renova silenciosamente |
| 30 dias sem usar | Pede login | Pede login (esperado) |
| Aluno trocou senha | Pede login | Pede login (esperado) |

## Dependência a instalar

```bash
pip install cryptography
```

Adicionar ao `requirements.txt`:

```
cryptography>=42.0.0
```
