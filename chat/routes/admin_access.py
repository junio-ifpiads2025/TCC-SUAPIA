"""Tela /admin/access: allowlist e blocklist (adicionar, remover, buscar)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from routes.admin_common import render, require_admin, verify_csrf
from services import access_log_service, acl_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/access")
async def access_page(request: Request, q: str = "", msg: str = "", admin: str = Depends(require_admin)):
    q = q.strip()
    allow = await acl_service.list_rules("allow", q or None)
    block = await acl_service.list_rules("block", q or None)
    return render(request, "access.html", allow=allow, block=block, q=q, msg=msg,
                  counts=acl_service.counts())


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
        access_log_service.log_admin(admin, "acl_add", f"kind={kind} alvo={chat_id.strip()}")
        msg = "Regra salva."
    except ValueError as e:
        msg = f"Erro: {e}"
    return RedirectResponse(f"/admin/access?msg={msg}", status_code=303)


@router.post("/access/remove", dependencies=[Depends(verify_csrf)])
async def access_remove(chat_id: str = Form(...), admin: str = Depends(require_admin)):
    await acl_service.remove_rule(chat_id)
    access_log_service.log_admin(admin, "acl_remove", f"alvo={chat_id.strip()}")
    return RedirectResponse("/admin/access?msg=Regra removida.", status_code=303)
