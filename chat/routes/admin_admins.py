"""Tela /admin/admins: administradores por matrícula SUAP (qualquer admin pode delegar)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from routes.admin_common import render, require_admin, verify_csrf
from services import access_log_service, admin_user_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/admins")
async def admins_page(request: Request, msg: str = "", admin: str = Depends(require_admin)):
    return render(request, "admins.html", admins=await admin_user_service.list_admins(), msg=msg)


@router.post("/admins", dependencies=[Depends(verify_csrf)])
async def admins_add(matricula: str = Form(...), admin: str = Depends(require_admin)):
    try:
        added = await admin_user_service.add_admin(matricula, added_by=admin)
        access_log_service.log_admin(admin, "admin_add", f"alvo={added}")
        msg = "Administrador adicionado."
    except ValueError as e:
        msg = f"Erro: {e}"
    return RedirectResponse(f"/admin/admins?msg={msg}", status_code=303)


@router.post("/admins/remove", dependencies=[Depends(verify_csrf)])
async def admins_remove(matricula: str = Form(...), admin: str = Depends(require_admin)):
    if matricula.strip() == admin:
        return RedirectResponse("/admin/admins?msg=Erro: você não pode remover a si mesmo.", status_code=303)
    await admin_user_service.remove_admin(matricula)
    access_log_service.log_admin(admin, "admin_remove", f"alvo={matricula.strip()}")
    return RedirectResponse("/admin/admins?msg=Administrador removido.", status_code=303)
