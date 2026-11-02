"""Tela /admin/access: allowlist e blocklist (adicionar, remover, buscar)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from routes.admin.common import render, require_admin, verify_csrf
from services.shared import acl_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/access")
async def access_page(request: Request, q: str = "", msg: str = "", admin: str = Depends(require_admin)):
    q = q.strip()
    allow = await acl_service.list_rules("allow", q or None)
    block = await acl_service.list_rules("block", q or None)
    limits = [r for r in await acl_service.list_rules(None, q or None) if r.get("daily_limit") is not None]
    return render(request, "access.html", allow=allow, block=block, q=q, msg=msg, limits=limits,
                  counts=acl_service.counts(), open_mode=acl_service.is_open(),
                  default_limit=acl_service.default_limit())


@router.post("/access", dependencies=[Depends(verify_csrf)])
async def access_add(
    chat_id: str = Form(...),
    kind: str = Form(...),
    reason: str = Form(""),
    clear_session: str = Form(""),
    admin: str = Depends(require_admin),
):
    try:
        await acl_service.add_rule(chat_id, kind, reason or None, created_by=admin,
                                   clear_session=bool(clear_session))
        msg = "Regra salva."
    except ValueError as e:
        msg = f"Erro: {e}"
    return RedirectResponse(f"/admin/access?msg={msg}", status_code=303)


@router.post("/access/remove", dependencies=[Depends(verify_csrf)])
async def access_remove(chat_id: str = Form(...), admin: str = Depends(require_admin)):
    await acl_service.remove_rule(chat_id)
    return RedirectResponse("/admin/access?msg=Regra removida.", status_code=303)


@router.post("/access/open-mode", dependencies=[Depends(verify_csrf)])
async def access_open_mode(open_mode: str = Form(""), admin: str = Depends(require_admin)):
    enabled = bool(open_mode)
    await acl_service.set_open(enabled)
    return RedirectResponse("/admin/access?msg=Configuração salva.", status_code=303)


@router.post("/access/limit", dependencies=[Depends(verify_csrf)])
async def access_default_limit(daily_limit: str = Form(""), admin: str = Depends(require_admin)):
    try:
        await acl_service.set_default_limit(daily_limit)
        msg = "Limite padrão salvo."
    except ValueError as e:
        msg = f"Erro: {e}"
    return RedirectResponse(f"/admin/access?msg={msg}", status_code=303)


@router.post("/access/user-limit", dependencies=[Depends(verify_csrf)])
async def access_user_limit(chat_id: str = Form(...), daily_limit: str = Form(""),
                            admin: str = Depends(require_admin)):
    try:
        await acl_service.set_user_limit(chat_id, daily_limit, created_by=admin)
        msg = "Limite do número salvo."
    except ValueError as e:
        msg = f"Erro: {e}"
    return RedirectResponse(f"/admin/access?msg={msg}", status_code=303)
