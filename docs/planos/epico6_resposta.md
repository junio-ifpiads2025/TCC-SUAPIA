# Plano — Épico 6: Resposta e Envio Outbound

> Requisitos cobertos: RF21, RF22

**Depende de:** Todos os épicos anteriores

---

## Objetivo

Enviar a resposta gerada ao usuário via WAHA e persistir o histórico conversacional para que interações futuras tenham contexto.

---

## Arquivos a criar / modificar

| Arquivo | Ação |
|---------|------|
| `services/waha_client.py` | Criar |
| `services/queue_service.py` | Modificar — integrar envio + history |
| `services/history_service.py` | Modificar — método `save_turn` |

---

## Passos

### 6.1 — `services/waha_client.py` — Envio outbound (RF21)

```python
async def send_message(chat_id: str, text: str) -> bool:
    """
    Envia mensagem de texto ao chat_id via WAHA REST API.
    Retorna True se entregue, False caso contrário.
    """
    url = f"{config.WAHA_BASE_URL}/api/sendText"
    payload = {
        "session": "default",
        "chatId": chat_id,
        "text": text,
    }
    headers = {"X-Api-Key": config.WAHA_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return True
    except httpx.HTTPError as e:
        logger.error("waha_send_failed", extra={"chat_id": chat_id, "error": str(e)})
        return False
```

### 6.2 — Integração no `queue_service.process_next()` (RF21, RF22)

Após `message_router.route()` retornar a resposta:

```python
# Enviar ao usuário
sent = await waha_client.send_message(chat_id, response_text)

if sent:
    # RF22: persistir histórico
    await history_service.save_turn(chat_id, user_message, response_text)
    await queue_service.mark_completed(message_id)
else:
    await queue_service.mark_failed(message_id, "waha_send_failed")
    logger.error("message_not_delivered", extra={"chat_id": chat_id, "message_id": message_id})
```

### 6.3 — `history_service.save_turn` (RF22)

```python
async def save_turn(chat_id: str, user_msg: str, assistant_msg: str):
    async with get_session() as session:
        session.add_all([
            ThreadHistory(chat_id=chat_id, role="user", content=user_msg),
            ThreadHistory(chat_id=chat_id, role="assistant", content=assistant_msg),
        ])
        await session.commit()
```

Cada ciclo gera dois registros na `thread_history`: um `user` e um `assistant` (RF22).

### 6.4 — Fallback de envio

Se `waha_client.send_message` falhar após N tentativas (não há retry automático per RF12):
- Marcar mensagem como `failed` com `error_detail='waha_send_failed'`.
- Logar o erro com `chat_id` e `message_id`.
- **Não** tentar reenviar automaticamente.

### 6.5 — Envio de mensagens do sistema (onboarding, menu, avisos)

`waha_client.send_message` é também usado para mensagens não-agente:
- Link de onboarding (Épico 1)
- Menu inicial pós-login (Épico 2)
- Aviso de rate limit (Épico 3)
- Fallback de indisponibilidade (Épicos 4, 5)

Essas chamadas não passam pela fila — são enviadas diretamente no handler do webhook.

---

## Critérios de Aceite

- **RF21:** Entrega confirmada → status `completed` e histórico atualizado. Falha no envio → status `failed` com erro logado.
- **RF22:** Cada ciclo (mensagem do usuário + resposta) gera dois registros em `thread_history`, vinculados ao `chat_id`.
- Mensagens de sistema (menu, onboarding, avisos) são enviadas via `waha_client` sem passar pela fila.
- Histórico disponível para as próximas consultas do mesmo `chat_id` (consumido em Épico 4, `history_service.get_history`).
