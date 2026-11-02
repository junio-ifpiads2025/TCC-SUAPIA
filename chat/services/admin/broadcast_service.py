"""
Mensagens em massa (broadcast) enviadas pelo painel (tabela `broadcast`).

Fluxo: o admin redige (rascunho) → vê quantos e quais destinatários (mascarados)
→ confirma → o envio roda em background, um destinatário por vez, com intervalo
BROADCAST_DELAY_SECONDS (o WAHA ainda aplica o próprio atraso anti-ban).
Destinatários: usuários que aceitaram os Termos de Uso e que o bot atenderia
hoje (`acl_service.check == "ok"`: fora da blocklist e, com a allowlist ativa,
dentro dela). O progresso fica nos contadores da tabela; cancelar interrompe
antes do próximo envio. Criar, enviar e cancelar são auditados.
"""

import asyncio

from sqlalchemy import select, update

import config
from utils.security import mask_chat_id
from models.database import AsyncSessionLocal, Broadcast, UserAuth
from services.chat import messaging_client
from services.shared import acl_service, audit_service, logger

MAX_TEXT_LEN = 4000
PREVIEW_SAMPLE = 20

_tasks: dict[int, asyncio.Task] = {}
_cancel: set[int] = set()


class BroadcastError(ValueError):
    """Texto inválido ou transição de estado não permitida."""


class BroadcastNotFound(LookupError):
    """Broadcast inexistente."""


def _to_dict(b: Broadcast) -> dict:
    return {"id": b.id, "admin": b.admin, "text": b.text, "status": b.status, "total": b.total,
            "sent": b.sent, "failed": b.failed, "created_at": b.created_at}


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

async def _db_accepted_chat_ids() -> list[str]:
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(UserAuth.chat_id).where(UserAuth.terms_accepted_at.is_not(None))
                               .order_by(UserAuth.chat_id))
        return [r[0] for r in rows]


async def _db_insert(admin: str, text: str) -> dict:
    async with AsyncSessionLocal() as s:
        b = Broadcast(admin=admin, text=text, status="draft")
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return _to_dict(b)


async def _db_get(broadcast_id: int) -> dict | None:
    async with AsyncSessionLocal() as s:
        b = await s.get(Broadcast, broadcast_id)
        return _to_dict(b) if b else None


async def _db_update(broadcast_id: int, **values) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(update(Broadcast).where(Broadcast.id == broadcast_id).values(**values))
        await s.commit()


async def _db_list(limit: int) -> list[dict]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(limit))).scalars().all()
        return [_to_dict(b) for b in rows]


# ── API pública ──────────────────────────────────────────────────────────────

async def recipients() -> list[str]:
    return [cid for cid in await _db_accepted_chat_ids() if acl_service.check(cid) == "ok"]


async def preview() -> dict:
    """Total de destinatários e uma amostra mascarada."""
    ids = await recipients()
    return {"total": len(ids), "sample": [mask_chat_id(c) for c in ids[:PREVIEW_SAMPLE]]}


async def create(text: str, admin: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise BroadcastError("A mensagem não pode ficar vazia.")
    if len(text) > MAX_TEXT_LEN:
        raise BroadcastError(f"Mensagem longa demais (máx. {MAX_TEXT_LEN} caracteres).")
    b = await _db_insert(admin, text)
    await audit_service.record("create", "broadcast", b["id"], None, {"text": text})
    return b


async def get(broadcast_id: int) -> dict:
    b = await _db_get(broadcast_id)
    if b is None:
        raise BroadcastNotFound(broadcast_id)
    return b


async def list_broadcasts(limit: int = 20) -> list[dict]:
    return await _db_list(limit)


async def _send_all(broadcast_id: int, text: str, ids: list[str]) -> None:
    sent = failed = 0
    try:
        for i, chat_id in enumerate(ids):
            if broadcast_id in _cancel:
                break
            try:
                await messaging_client.enviar_texto_async(chat_id, text)
                sent += 1
            except Exception as e:
                failed += 1
                logger.warn("BROADCAST", f"Falha ao enviar #{broadcast_id} para {mask_chat_id(chat_id)}: {e}")
            await _db_update(broadcast_id, sent=sent, failed=failed)
            if i < len(ids) - 1:
                await asyncio.sleep(config.BROADCAST_DELAY_SECONDS)
        status = "cancelled" if broadcast_id in _cancel else "done"
        await _db_update(broadcast_id, status=status)
        logger.info("BROADCAST", f"#{broadcast_id} {status}: {sent} enviada(s), {failed} falha(s).")
    except Exception as e:
        logger.error("BROADCAST", f"Envio #{broadcast_id} interrompido: {e}")
    finally:
        _cancel.discard(broadcast_id)
        _tasks.pop(broadcast_id, None)


async def send(broadcast_id: int) -> dict:
    """Confirma um rascunho e inicia o envio em background."""
    b = await get(broadcast_id)
    if b["status"] != "draft":
        raise BroadcastError("Só um rascunho pode ser enviado.")
    ids = await recipients()
    await _db_update(broadcast_id, status="sending", total=len(ids), sent=0, failed=0)
    await audit_service.record("send", "broadcast", broadcast_id, {"status": "draft"},
                               {"status": "sending", "total": len(ids)})
    _tasks[broadcast_id] = asyncio.get_running_loop().create_task(_send_all(broadcast_id, b["text"], ids))
    return {**b, "status": "sending", "total": len(ids)}


async def cancel(broadcast_id: int) -> None:
    """Cancela um rascunho ou interrompe um envio em andamento."""
    b = await get(broadcast_id)
    if b["status"] == "draft":
        await _db_update(broadcast_id, status="cancelled")
    elif b["status"] == "sending" and broadcast_id in _tasks:
        _cancel.add(broadcast_id)  # a task grava o status final
    elif b["status"] == "sending":
        # envio perdido (processo reiniciado no meio): só encerra o registro
        await _db_update(broadcast_id, status="cancelled")
    else:
        raise BroadcastError("Esse envio já terminou.")
    await audit_service.record("cancel", "broadcast", broadcast_id, {"status": b["status"]},
                               {"status": "cancelled"})
