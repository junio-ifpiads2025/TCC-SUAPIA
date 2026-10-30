"""Painel admin: editor do system prompt, histórico e restauração de versões."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routes.admin_common import render, require_admin, verify_csrf
from services import access_log_service, prompt_service

router = APIRouter(prefix="/admin", tags=["admin"])


async def _page(request: Request, status_code: int = 200, error: str | None = None,
                draft: str | None = None, msg: str | None = None) -> HTMLResponse:
    versions = await prompt_service.list_versions()
    info = prompt_service.active_info()
    current = prompt_service.active_content()
    return render(request, "prompt.html", status_code=status_code, versions=versions,
                  active=info, content=draft if draft is not None else current,
                  error=error, msg=msg)


@router.get("/prompt", response_class=HTMLResponse)
async def prompt_page(request: Request, msg: str | None = None, _: str = Depends(require_admin)):
    return await _page(request, msg=msg)


@router.post("/prompt", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def prompt_save(request: Request, content: str = Form(""), admin: str = Depends(require_admin)):
    try:
        v = await prompt_service.save(content, admin)
    except prompt_service.PromptError as e:
        return await _page(request, 422, error=str(e), draft=content)
    access_log_service.log_admin(admin, "prompt_save", f"version={v['id']}")
    return RedirectResponse("/admin/prompt?msg=salvo", status_code=303)


@router.post("/prompt/{version_id}/activate", response_class=HTMLResponse,
             dependencies=[Depends(verify_csrf)])
async def prompt_activate(request: Request, version_id: int, admin: str = Depends(require_admin)):
    try:
        await prompt_service.activate(version_id)
    except prompt_service.PromptNotFound:
        return await _page(request, 404, error="Versão não encontrada.")
    access_log_service.log_admin(admin, "prompt_activate", f"version={version_id}")
    return RedirectResponse("/admin/prompt?msg=restaurado", status_code=303)
