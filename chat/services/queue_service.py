"""
Serviço de fila de mensagens do SUAP-IA (Redis, listas).

Ciclo de vida de uma mensagem recebida:
  enqueue() → process_next() → _process_item() → removida de 'processing'
                                              ↘ 'failed' (erro/timeout esgotado)

Chaves Redis:
- suap:queue:pending    (list) aguardando; LPUSH na entrada, consumo pela direita (FIFO)
- suap:queue:processing (list) em atendimento (BLMOVE pending → processing)
- suap:queue:started    (hash) id → timestamp de início do atendimento
- suap:queue:failed     (list) falhas/timeouts, limitada a FAILED_MAX itens
- suap:queue:done       (list) atendidas (com resposta), limitada a DONE_MAX itens

Payload (JSON): {id, chat_id, provider, content, enqueued_at, attempts}.

Garantias:
- Nada se perde se o processo cair: na subida recover_processing() devolve
  tudo de 'processing' para 'pending'.
- Mesmo chat_id é atendido um por vez, mesmo com vários consumidores (RN08).
- Itens parados em 'processing' além de QUEUE_TIMEOUT_MINUTES voltam para
  'pending' (até QUEUE_MAX_ATTEMPTS) ou vão para 'failed' (RN07).
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from config import AGENT_NAME, MAX_DAILY_MESSAGES, QUEUE_MAX_ATTEMPTS, QUEUE_TIMEOUT_MINUTES
from services import access_log_service, logger
from services.auth_service import generate_onboarding_link, logout
from services.message_router import route
from services.messaging_client import enviar_texto_async, marcar_lida_async, iniciar_digitacao_async
from services.session_service import (
    delete_token, increment_rate, is_authenticated, get_profile, delete_profile, get_redis,
)
from services import thread_service

PENDING = "suap:queue:pending"
PROCESSING = "suap:queue:processing"
STARTED = "suap:queue:started"
FAILED = "suap:queue:failed"
FAILED_MAX = 500
DONE = "suap:queue:done"
DONE_MAX = 500
DONE_RESPONSE_MAX = 4000

_KEYS = {"pending": PENDING, "processing": PROCESSING, "failed": FAILED, "done": DONE}

# Trava por chat_id (dentro do processo) para manter FIFO por conversa
# quando há mais de um consumidor.
_chat_locks: dict[str, asyncio.Lock] = {}


def _provider_of(chat_id: str) -> str:
    """Deduz o provider pelo namespace do chat_id ('telegram:123'); padrão waha."""
    return chat_id.split(":", 1)[0] if ":" in chat_id else "waha"


def _dumps(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False, separators=(",", ":"))


async def enqueue(chat_id: str, content: str, message_id: str | None = None) -> None:
    """
    Ponto de entrada para toda mensagem recebida do webhook.

    Antes de enfileirar, executa validações em ordem:
      1. Comando /sair — encerra sessão imediatamente, sem enfileirar.
      2. Autenticação (RF01/RF10) — se não autenticado, envia link de onboarding.
      3. Rate limit diário (RN06) — se cota esgotada, envia aviso.
      4. Insere em suap:queue:pending (RF11).
    """
    provider = _provider_of(chat_id)

    # Marca como lida imediatamente ao receber — antes de qualquer processamento (anti-ban)
    await marcar_lida_async(chat_id, message_id)

    # /sair é tratado aqui e não entra na fila, pois não precisa do agente
    if content.strip() == "/sair":
        await delete_token(chat_id)
        await logout(chat_id)
        await delete_profile(chat_id)
        await thread_service.clear_thread(chat_id)  # apaga histórico junto com a sessão
        await enviar_texto_async(
            chat_id,
            "Sessão encerrada. Na próxima mensagem você receberá o link de login.",
        )
        return

    # RF10: usuário não autenticado recebe link de onboarding e a mensagem é descartada
    if not await is_authenticated(chat_id):
        access_log_service.log_event(chat_id, "denied", provider=provider, detail="nao_autenticado")
        link = await generate_onboarding_link(chat_id)
        await enviar_texto_async(
            chat_id,
            f"Olá! Para usar o {AGENT_NAME}, acesse o link abaixo para fazer login com sua conta SUAP "
            f"(válido por 15 minutos):\n\n{link}",
        )
        return

    # RN06: incrementa contador diário antes de enfileirar
    count = await increment_rate(chat_id)
    if count > MAX_DAILY_MESSAGES:
        access_log_service.log_event(chat_id, "rate_limited", provider=provider)
        await enviar_texto_async(
            chat_id,
            "Você atingiu o limite de 25 mensagens por dia. Tente novamente amanhã.",
        )
        return

    item = {
        "id": uuid.uuid4().hex,
        "chat_id": chat_id,
        "provider": provider,
        "content": content,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
        "attempts": 0,
    }
    await get_redis().lpush(PENDING, _dumps(item))
    logger.info("QUEUE", f"Enfileirado — chat_id={chat_id}")


async def _process_item(raw: str) -> None:
    """
    Atende um item já movido para 'processing'.

    Sucesso: remove de processing/started. Erro: move para 'failed'.
    Se o item já não está em processing (cleanup_stale o devolveu/falhou
    durante o atendimento), apenas ignora o desfecho.
    """
    r = get_redis()
    item = json.loads(raw)
    chat_id, item_id = item["chat_id"], item["id"]
    await r.hset(STARTED, item_id, str(time.time()))

    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    t0 = time.monotonic()
    error: str | None = None
    resposta: str | None = None
    async with lock:
        try:
            logger.incoming(chat_id, item["content"])
            await iniciar_digitacao_async(chat_id)  # "digitando..." durante o LLM
            resposta, _ = await route(chat_id, item["content"])

            profile = await get_profile(chat_id)
            if profile and profile.get("nome"):
                resposta = f"{profile['nome'].split()[0]}, {resposta}"

            logger.response_log(resposta)
            await enviar_texto_async(chat_id, resposta)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:300]
            logger.error("QUEUE", f"Erro ao processar id={item_id} chat_id={chat_id}: {e}")
    if not _chat_locks[chat_id].locked() and not getattr(_chat_locks[chat_id], "_waiters", None):
        _chat_locks.pop(chat_id, None)

    duration_ms = int((time.monotonic() - t0) * 1000)
    removed = await r.lrem(PROCESSING, 1, raw)
    await r.hdel(STARTED, item_id)

    if error is None:
        access_log_service.log_event(chat_id, "answered", provider=item.get("provider"), duration_ms=duration_ms)
        item["response"] = (resposta or "")[:DONE_RESPONSE_MAX]
        item["answered_at"] = datetime.now(timezone.utc).isoformat()
        item["duration_ms"] = duration_ms
        await r.lpush(DONE, _dumps(item))
        await r.ltrim(DONE, 0, DONE_MAX - 1)
        return
    access_log_service.log_event(chat_id, "failed", provider=item.get("provider"),
                                 detail=error.split(":", 1)[0], duration_ms=duration_ms)
    if removed:  # se não estava mais em processing, o cleanup já decidiu o destino
        item["error"] = error
        await _push_failed(item)


async def _push_failed(item: dict) -> None:
    r = get_redis()
    await r.lpush(FAILED, _dumps(item))
    await r.ltrim(FAILED, 0, FAILED_MAX - 1)


async def process_next(timeout: float = 1) -> None:
    """
    Pega o próximo item de 'pending' (BLMOVE pending → processing, RIGHT LEFT)
    e o atende. Retorna ao estourar o timeout se a fila estiver vazia.

    Chamado em loop por cada um dos QUEUE_CONSUMERS consumidores (main.py).
    """
    raw = await get_redis().blmove(PENDING, PROCESSING, timeout, "RIGHT", "LEFT")
    if raw is None:
        return
    try:
        await _process_item(raw)
    except Exception as e:  # item corrompido etc.; cleanup_stale/recover cuidam do resto
        logger.error("QUEUE", f"Falha inesperada no consumidor: {e}")


async def recover_processing() -> int:
    """Na subida: devolve tudo que sobrou em 'processing' (queda no meio) para 'pending'."""
    r = get_redis()
    n = 0
    while await r.lmove(PROCESSING, PENDING, "LEFT", "RIGHT") is not None:
        n += 1
    await r.delete(STARTED)
    if n:
        logger.warn("QUEUE", f"Recuperados {n} item(ns) de 'processing'")
    return n


async def cleanup_stale() -> None:
    """
    Trata itens parados em 'processing' há mais de QUEUE_TIMEOUT_MINUTES (RN07):
    volta para 'pending' (attempts+1) enquanto attempts < QUEUE_MAX_ATTEMPTS;
    senão vai para 'failed' com error='timeout'. Chamado a cada 60s.
    """
    r = get_redis()
    limit = QUEUE_TIMEOUT_MINUTES * 60
    now = time.time()
    started = await r.hgetall(STARTED)
    for raw in await r.lrange(PROCESSING, 0, -1):
        item = json.loads(raw)
        ts = started.get(item["id"])
        if ts is not None:
            age = now - float(ts)
        else:  # ainda sem registro de início: usa a hora de entrada
            age = now - datetime.fromisoformat(item["enqueued_at"]).timestamp()
        if age <= limit:
            continue
        if not await r.lrem(PROCESSING, 1, raw):
            continue  # outro consumidor concluiu no meio
        await r.hdel(STARTED, item["id"])
        item["attempts"] = item.get("attempts", 0) + 1
        if item["attempts"] < QUEUE_MAX_ATTEMPTS:
            await r.rpush(PENDING, _dumps(item))  # direita = próximo a ser consumido
            logger.warn("QUEUE", f"Timeout, reenfileirado — id={item['id']} chat_id={item['chat_id']}")
        else:
            item["error"] = "timeout"
            await _push_failed(item)
            access_log_service.log_event(item["chat_id"], "failed", provider=item.get("provider"), detail="timeout")
            logger.warn("QUEUE", f"Timeout, falhou — id={item['id']} chat_id={item['chat_id']}")


# ── API para o painel admin ──────────────────────────────────────────────────

async def stats() -> dict:
    r = get_redis()
    return {
        "pending": await r.llen(PENDING),
        "processing": await r.llen(PROCESSING),
        "failed": await r.llen(FAILED),
        "done": await r.llen(DONE),
    }


async def list_items(which: str, limit: int = 200) -> list[dict]:
    """Itens da lista (pending: o mais antigo primeiro; demais: mais recente primeiro)."""
    key = _KEYS.get(which)
    if key is None:
        raise ValueError(which)
    r = get_redis()
    raws = await r.lrange(key, 0, limit - 1)
    if which == "pending":
        raws = list(reversed(await r.lrange(key, -limit, -1)))
    items = [json.loads(x) for x in raws]
    if which == "processing":
        started = await r.hgetall(STARTED)
        for it in items:
            it["started_at"] = started.get(it["id"])
    return items


async def _find(key: str, item_id: str) -> str | None:
    for raw in await get_redis().lrange(key, 0, -1):
        if json.loads(raw)["id"] == item_id:
            return raw
    return None


async def cancel(item_id: str) -> bool:
    """Cancela um item ainda pendente. False se não existe/já foi pego."""
    raw = await _find(PENDING, item_id)
    return bool(raw and await get_redis().lrem(PENDING, 1, raw))


async def requeue(item_id: str) -> bool:
    """Devolve um item de 'failed' para 'pending' com attempts=0."""
    r = get_redis()
    raw = await _find(FAILED, item_id)
    if not raw or not await r.lrem(FAILED, 1, raw):
        return False
    item = json.loads(raw)
    item["attempts"] = 0
    item.pop("error", None)
    await r.lpush(PENDING, _dumps(item))
    return True
