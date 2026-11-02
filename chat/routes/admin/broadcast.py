"""Tela /admin/broadcast: redigir, pré-visualizar destinatários, confirmar e acompanhar envios."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routes.admin.common import render, require_admin, verify_csrf
from services.admin import broadcast_service as bs

router = APIRouter(prefix="/admin", tags=["admin"])


def _redirect(broadcast_id: int | None = None, msg: str = "") -> RedirectResponse:
    qs = {k: v for k, v in (("id", broadcast_id), ("msg", msg)) if v}
    return RedirectResponse("/admin/broadcast?" + urlencode(qs), status_code=303)


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, id: int | None = None, msg: str = "",
                         _: str = Depends(require_admin)):
    selected, preview = None, None
    if id is not None:
        try:
            selected = await bs.get(id)
        except bs.BroadcastNotFound:
            msg = "Erro: envio não encontrado."
        if selected and selected["status"] == "draft":
            preview = await bs.preview()
    return render(request, "broadcast.html", selected=selected, preview=preview, msg=msg,
                  history=await bs.list_broadcasts(), max_len=bs.MAX_TEXT_LEN)


@router.get("/broadcast/{broadcast_id}/progress", response_class=HTMLResponse)
async def broadcast_progress(request: Request, broadcast_id: int, _: str = Depends(require_admin)):
    """Parcial HTMX com os contadores do envio."""
    try:
        b = await bs.get(broadcast_id)
    except bs.BroadcastNotFound:
        return HTMLResponse("", status_code=404)
    return render(request, "_broadcast_progress.html", b=b)


@router.post("/broadcast", dependencies=[Depends(verify_csrf)])
async def broadcast_create(text: str = Form(""), admin: str = Depends(require_admin)):
    try:
        b = await bs.create(text, admin)
    except bs.BroadcastError as e:
        return _redirect(msg=f"Erro: {e}")
    return _redirect(b["id"])


@router.post("/broadcast/{broadcast_id}/send", dependencies=[Depends(verify_csrf)])
async def broadcast_send(broadcast_id: int, _: str = Depends(require_admin)):
    try:
        await bs.send(broadcast_id)
    except bs.BroadcastError as e:
        return _redirect(broadcast_id, f"Erro: {e}")
    except bs.BroadcastNotFound:
        return _redirect(msg="Erro: envio não encontrado.")
    return _redirect(broadcast_id, "Envio iniciado.")


@router.post("/broadcast/{broadcast_id}/cancel", dependencies=[Depends(verify_csrf)])
async def broadcast_cancel(broadcast_id: int, _: str = Depends(require_admin)):
    try:
        await bs.cancel(broadcast_id)
    except bs.BroadcastError as e:
        return _redirect(broadcast_id, f"Erro: {e}")
    except bs.BroadcastNotFound:
        return _redirect(msg="Erro: envio não encontrado.")
    return _redirect(broadcast_id, "Envio cancelado.")
