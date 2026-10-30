"""Painel admin: fila de atendimento (Redis) — abas, cancelar e reenfileirar."""

from fastapi import APIRouter, Depends, HTTPException, Request

from routes.admin_common import render, require_admin, verify_csrf
from services import access_log_service, queue_service

router = APIRouter(prefix="/admin", tags=["admin"])

_ABAS = ("pending", "processing", "failed", "done")


def _which(value: str) -> str:
    if value not in _ABAS:
        raise HTTPException(status_code=400, detail="Aba inválida.")
    return value


def _mascarar_chat(chat_id) -> str:
    """Mantém só os 4 últimos dígitos do identificador (telefone/JID)."""
    digitos = "".join(c for c in str(chat_id or "").split("@")[0] if c.isalnum())
    return "…" + digitos[-4:] if len(digitos) > 4 else "…"


def _sanitizar(item: dict) -> dict:
    """Minimização de dados (LGPD): o painel não exibe conteúdo da conversa nem o telefone completo."""
    return {
        **{k: v for k, v in item.items() if k not in ("content", "response", "chat_id")},
        "chat_id": _mascarar_chat(item.get("chat_id")),
        "content_len": len(item.get("content") or ""),
        "response_len": len(item.get("response") or ""),
    }


async def _itens(which: str) -> list[dict]:
    return [_sanitizar(it) for it in await queue_service.list_items(which)]


async def _tabela(request: Request, which: str):
    """Renderiza o parcial da tabela da aba `which`."""
    return render(
        request, "_queue_table.html",
        which=which,
        items=await _itens(which),
        counts=await queue_service.stats(),
    )


@router.get("/queue")
async def queue_page(request: Request, which: str = "pending", _: str = Depends(require_admin)):
    which = _which(which)
    return render(
        request, "queue.html",
        which=which,
        items=await _itens(which),
        counts=await queue_service.stats(),
    )


@router.get("/queue/table")
async def queue_table(request: Request, which: str = "pending", _: str = Depends(require_admin)):
    return await _tabela(request, _which(which))


@router.post("/queue/{item_id}/cancel", dependencies=[Depends(verify_csrf)])
async def queue_cancel(request: Request, item_id: str, admin: str = Depends(require_admin)):
    await queue_service.cancel(item_id)
    access_log_service.log_admin(admin, "queue_cancel", f"item={item_id}")
    return await _tabela(request, "pending")


@router.post("/queue/{item_id}/requeue", dependencies=[Depends(verify_csrf)])
async def queue_requeue(request: Request, item_id: str, admin: str = Depends(require_admin)):
    await queue_service.requeue(item_id)
    access_log_service.log_admin(admin, "queue_requeue", f"item={item_id}")
    return await _tabela(request, "failed")
