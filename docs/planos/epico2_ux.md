# Plano — Épico 2: Interação e UX

> Requisitos cobertos: RF05, RF06, RF07 | Regras: RN04

**Depende de:** Épico 1 (auth), Épicos 4 e 5 (agentes prontos para receber consultas)

---

## Objetivo

Prover a camada de roteamento de mensagens: exibir menu, interpretar linguagem natural para direcionar ao fluxo correto (RAG, MCP ou ambos) e garantir que erros nunca exponham detalhes técnicos ao usuário.

---

## Arquivos a criar / modificar

| Arquivo | Ação |
|---------|------|
| `routes/webhook.py` | Modificar — adicionar dispatcher |
| `services/message_router.py` | Criar |
| `config.py` | Atualizar — MENU_TEXT, FALLBACK_TEXT |

---

## Passos

### 2.1 — Mensagens estáticas em `config.py`

```python
MENU_TEXT = """
Olá! Sou o SUAPIA 👋 Posso te ajudar com:
1. Dúvidas sobre o SUAP e manuais institucionais
2. Seus dados acadêmicos (notas, faltas, disciplinas)

Digite sua pergunta ou use os comandos:
/menu — exibir este menu
/sair — encerrar sessão
"""

FALLBACK_TEXT = "Desculpe, ocorreu uma instabilidade. Tente novamente em alguns instantes."

UNKNOWN_COMMAND_TEXT = "Comando não reconhecido. Comandos disponíveis: /menu, /sair"
```

### 2.2 — `services/message_router.py`

Responsável por classificar a mensagem e chamar o agente correto:

```python
async def route(chat_id: str, message: str, token: str) -> tuple[str, list[dict]]:
    ...
```

Lógica de roteamento (RF06):
1. Se `/menu` → retorna `MENU_TEXT` (RF05)
2. Se `/sair` → delegado ao auth (tratado no webhook)
3. Se começa com `/` → retorna `UNKNOWN_COMMAND_TEXT` (RN04)
4. Caso contrário → chama `agent_orchestrator.gerar_resposta_agente(message, chat_id, token)`
   - O orquestrador já decide internamente se usa RAG, MCP ou ambos (RF06, RF13)

Tratamento de exceção global (RF07):
```python
except Exception as e:
    logger.error("route_error", extra={"error": str(e), "chat_id": chat_id})
    return FALLBACK_TEXT, []
```

### 2.3 — Exibição do menu pós-login (RF05)

Em `auth_service.py`, após login bem-sucedido, enfileirar uma mensagem de menu:
- O `queue_service` envia `MENU_TEXT` ao usuário como primeira resposta após autenticação.

### 2.4 — Garantias de UX (RF07)

- Nunca propagar exceções até o usuário sem captura.
- Middleware FastAPI de exceção global retorna `FALLBACK_TEXT` como resposta ao WAHA.
- `utils/security.py` sanitiza qualquer dict antes de logar.

---

## Critérios de Aceite

- **RF05:** `/menu` retorna menu. Login bem-sucedido exibe menu automaticamente.
- **RF06:** Pergunta em linguagem natural ativa o agente e retorna resposta contextualizada.
- **RF07:** Nenhum stack trace, endpoint ou token aparece na resposta ao usuário em qualquer cenário de erro.
- **RN04:** `/sair` e `/menu` funcionam; qualquer outro `/comando` retorna mensagem de opções disponíveis.
