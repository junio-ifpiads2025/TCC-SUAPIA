"""Tela /admin/quality: respostas mal avaliadas, perguntas sem resposta e satisfação."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from routes.admin.common import render, require_admin, verify_csrf
from services.shared import qa_case_service

router = APIRouter(prefix="/admin", tags=["admin"])

TABS = {"down": "Mal avaliadas", "no_answer": "Sem resposta"}
TITLE_MAX = 200


def _back(tab: str, msg: str) -> RedirectResponse:
    return RedirectResponse("/admin/quality?" + urlencode({"tab": tab, "msg": msg}), status_code=303)


@router.get("/quality")
async def quality_page(request: Request, tab: str = "down", msg: str = "",
                       admin: str = Depends(require_admin)):
    tab = tab if tab in TABS else "down"
    cases = await qa_case_service.list_cases(tab)
    groups = qa_case_service.group_similar(cases) if tab == "no_answer" else []
    return render(request, "quality.html", tab=tab, tabs=TABS, cases=cases, groups=groups,
                  statuses=qa_case_service.STATUSES, stats=await qa_case_service.satisfaction(),
                  msg=msg)


@router.post("/quality/{case_id}", dependencies=[Depends(verify_csrf)])
async def quality_update(case_id: int, status: str = Form(...), note: str = Form(""),
                         tab: str = Form("down"), admin: str = Depends(require_admin)):
    try:
        await qa_case_service.update_case(case_id, status, note)
        msg = "Caso atualizado."
    except ValueError as e:
        msg = f"Erro: {e}"
    except LookupError:
        msg = "Erro: caso não encontrado."
    return _back(tab, msg)


@router.post("/quality/{case_id}/convert", dependencies=[Depends(verify_csrf)])
async def quality_convert(case_id: int, tab: str = Form("down"), admin: str = Depends(require_admin)):
    """Marca o caso como convertido e abre o formulário de conhecimento com o título preenchido."""
    try:
        case = await qa_case_service.get_case(case_id)
        await qa_case_service.update_case(case_id, "converted", case["note"])
    except LookupError:
        return _back(tab, "Erro: caso não encontrado.")
    title = (case["question"] or "").strip()[:TITLE_MAX]
    return RedirectResponse("/admin/knowledge?" + urlencode({"title": title}), status_code=303)
