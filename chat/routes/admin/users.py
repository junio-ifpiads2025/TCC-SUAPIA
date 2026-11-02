"""Tela /admin/users: busca, detalhe, bloqueio, limite próprio e exclusão LGPD de um usuário."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from routes.admin.common import render, require_admin, verify_csrf
from services.admin import user_admin_service, user_data_service
from services.shared import acl_service

router = APIRouter(prefix="/admin", tags=["admin"])

ERASE_CONFIRMATION = "APAGAR"


def _back(user_id: int, msg: str) -> RedirectResponse:
    return RedirectResponse(f"/admin/users/{user_id}?" + urlencode({"msg": msg}), status_code=303)


async def _chat_id(user_id: int) -> str:
    chat_id = await user_admin_service.get_chat_id(user_id)
    if chat_id is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return chat_id


@router.get("/users")
async def users_page(request: Request, q: str = "", msg: str = "", admin: str = Depends(require_admin)):
    users = await user_admin_service.search(q)
    return render(request, "users.html", users=users, q=q.strip(), msg=msg)


@router.get("/users/{user_id}")
async def user_detail(request: Request, user_id: int, msg: str = "", admin: str = Depends(require_admin)):
    user = await user_admin_service.detail(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return render(request, "user_detail.html", user=user, msg=msg,
                  default_limit=acl_service.default_limit(), confirmation=ERASE_CONFIRMATION)


@router.post("/users/{user_id}/block", dependencies=[Depends(verify_csrf)])
async def user_block(user_id: int, reason: str = Form(""), admin: str = Depends(require_admin)):
    await acl_service.add_rule(await _chat_id(user_id), "block", reason or None,
                               created_by=admin, clear_session=True)
    return _back(user_id, "Usuário bloqueado.")


@router.post("/users/{user_id}/unblock", dependencies=[Depends(verify_csrf)])
async def user_unblock(user_id: int, admin: str = Depends(require_admin)):
    await acl_service.remove_rule(await _chat_id(user_id))
    return _back(user_id, "Regra de acesso removida.")


@router.post("/users/{user_id}/limit", dependencies=[Depends(verify_csrf)])
async def user_limit(user_id: int, daily_limit: str = Form(""), admin: str = Depends(require_admin)):
    try:
        await acl_service.set_user_limit(await _chat_id(user_id), daily_limit, created_by=admin)
        msg = "Limite salvo."
    except ValueError as e:
        msg = f"Erro: {e}"
    return _back(user_id, msg)


@router.post("/users/{user_id}/erase", dependencies=[Depends(verify_csrf)])
async def user_erase(user_id: int, confirm: str = Form(""), admin: str = Depends(require_admin)):
    if confirm.strip() != ERASE_CONFIRMATION:
        return _back(user_id, f"Erro: digite {ERASE_CONFIRMATION} para confirmar a exclusão.")
    await user_data_service.erase(await _chat_id(user_id), user_id=user_id)
    return RedirectResponse("/admin/users?" + urlencode({"msg": "Dados do usuário apagados."}),
                            status_code=303)
