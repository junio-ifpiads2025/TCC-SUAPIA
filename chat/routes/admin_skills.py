"""Painel admin: CRUD de skills (Postgres) e de guardrails com botão testar."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from routes.admin_common import render, require_admin, verify_csrf
from services import access_log_service
from services import guardrail_service as gs
from services import skill_service

router = APIRouter(prefix="/admin", tags=["admin"])


class _TestBody(BaseModel):
    text: str = Field("", max_length=gs.MAX_TEXT_LEN)


async def _page(request: Request, status_code: int = 200, error: str | None = None,
                skill: str | None = None, msg: str | None = None) -> HTMLResponse:
    return render(
        request, "skills.html", status_code=status_code,
        skills=await skill_service.list_skills(),
        selected=await skill_service.get_skill(skill) if skill else None,
        guardrails=await gs.list_rules(),
        scopes=gs.SCOPES, match_types=gs.MATCH_TYPES, actions=gs.ACTIONS,
        error=error, msg=msg,
    )


def _form(name, description, scope, match_type, pattern, action, response,
          instruction, priority, enabled) -> dict:
    return {"name": name, "description": description, "scope": scope,
            "match_type": match_type, "pattern": pattern, "action": action,
            "response": response, "instruction": instruction,
            "priority": priority, "enabled": enabled == "on"}


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request, skill: str | None = None, msg: str | None = None,
                      _: str = Depends(require_admin)):
    return await _page(request, skill=skill, msg=msg)


@router.post("/skills", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def skill_create(
    request: Request, slug: str = Form(""), name: str = Form(""), description: str = Form(""),
    body: str = Form(""), admin: str = Depends(require_admin),
):
    data = {"name": name, "description": description, "body": body}
    try:
        await skill_service.create_skill(slug, data)
    except skill_service.SkillError as e:
        return await _page(request, 422, error=str(e))
    access_log_service.log_admin(admin, "skill_create", f"skill={slug.strip()}")
    return RedirectResponse("/admin/skills?msg=skill+criada", status_code=303)


@router.post("/skills/{slug}/delete", response_class=HTMLResponse,
             dependencies=[Depends(verify_csrf)])
async def skill_delete(request: Request, slug: str, admin: str = Depends(require_admin)):
    try:
        await skill_service.delete_skill(slug)
    except skill_service.SkillNotFound:
        return await _page(request, 404, error="Skill não encontrada.")
    access_log_service.log_admin(admin, "skill_delete", f"skill={slug}")
    return RedirectResponse("/admin/skills?msg=skill+removida", status_code=303)


@router.post("/skills/{slug}", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def skill_update(
    request: Request, slug: str, name: str = Form(""), description: str = Form(""),
    body: str = Form(""), admin: str = Depends(require_admin),
):
    data = {"name": name, "description": description, "body": body}
    try:
        await skill_service.update_skill(slug, data)
    except skill_service.SkillError as e:
        return await _page(request, 422, error=str(e), skill=slug)
    except skill_service.SkillNotFound:
        return await _page(request, 404, error="Skill não encontrada.")
    access_log_service.log_admin(admin, "skill_update", f"skill={slug}")
    return RedirectResponse(f"/admin/skills?skill={slug}&msg=skill+atualizada", status_code=303)


@router.post("/guardrails", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def guardrail_create(
    request: Request, name: str = Form(""), description: str = Form(""), scope: str = Form(""),
    match_type: str = Form(""), pattern: str = Form(""), action: str = Form(""),
    response: str = Form(""), instruction: str = Form(""), priority: str = Form("100"),
    enabled: str = Form(""), admin: str = Depends(require_admin),
):
    data = _form(name, description, scope, match_type, pattern, action, response,
                 instruction, priority, enabled)
    try:
        await gs.create_rule(data)
    except gs.GuardrailError as e:
        return await _page(request, 422, error=str(e))
    access_log_service.log_admin(admin, "guardrail_create", f"action={action}")
    return RedirectResponse("/admin/skills?msg=criado", status_code=303)


@router.post("/guardrails/{rule_id}/delete", response_class=HTMLResponse,
             dependencies=[Depends(verify_csrf)])
async def guardrail_delete(request: Request, rule_id: int, admin: str = Depends(require_admin)):
    try:
        await gs.delete_rule(rule_id)
    except gs.GuardrailNotFound:
        return await _page(request, 404, error="Regra não encontrada.")
    access_log_service.log_admin(admin, "guardrail_delete", f"rule={rule_id}")
    return RedirectResponse("/admin/skills?msg=removido", status_code=303)


@router.post("/guardrails/{rule_id}", response_class=HTMLResponse,
             dependencies=[Depends(verify_csrf)])
async def guardrail_update(
    request: Request, rule_id: int, name: str = Form(""), description: str = Form(""),
    scope: str = Form(""), match_type: str = Form(""), pattern: str = Form(""),
    action: str = Form(""), response: str = Form(""), instruction: str = Form(""),
    priority: str = Form("100"), enabled: str = Form(""), admin: str = Depends(require_admin),
):
    data = _form(name, description, scope, match_type, pattern, action, response,
                 instruction, priority, enabled)
    try:
        await gs.update_rule(rule_id, data)
    except gs.GuardrailError as e:
        return await _page(request, 422, error=str(e))
    except gs.GuardrailNotFound:
        return await _page(request, 404, error="Regra não encontrada.")
    access_log_service.log_admin(admin, "guardrail_update", f"rule={rule_id}")
    return RedirectResponse("/admin/skills?msg=atualizado", status_code=303)


@router.post("/api/guardrails/test", dependencies=[Depends(verify_csrf)])
async def guardrail_test(body: _TestBody, _: str = Depends(require_admin)):
    """Aplica as regras ativas a um texto de exemplo, sem enviar nada."""
    return JSONResponse(gs.test(body.text))
