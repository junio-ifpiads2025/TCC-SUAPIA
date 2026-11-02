"""Tela /admin/audit: alterações feitas pelos admins, com diff e botão reverter."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from routes.admin.common import parse_date, render, require_admin, verify_csrf
from services.admin import audit_revert
from services.shared import audit_service

router = APIRouter(prefix="/admin", tags=["admin"])

# Áreas auditadas sem reversão (ações operacionais): aparecem no filtro, sem botão Reverter
NON_REVERTIBLE = ["broadcast", "knowledge_reindex", "provider", "user_data"]
ENTITIES = list(audit_revert.REVERTERS) + NON_REVERTIBLE
PAGE_SIZE = 50


@router.get("/audit")
async def audit_page(
    request: Request,
    admin_filter: str = "",
    entity: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    msg: str = "",
    admin: str = Depends(require_admin),
):
    page = max(page, 1)
    entity = entity if entity in ENTITIES else ""
    rows = await audit_service.list_entries(
        admin=admin_filter.strip() or None,
        entity=entity or None,
        date_from=parse_date(date_from),
        date_to=parse_date(date_to),
        limit=PAGE_SIZE + 1,
        offset=(page - 1) * PAGE_SIZE,
    )
    has_next = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    for r in rows:
        r["changes"] = audit_service.changes(r)

    def url(p: int) -> str:
        qs = {"admin_filter": admin_filter, "entity": entity, "date_from": date_from,
              "date_to": date_to, "page": p}
        return "/admin/audit?" + urlencode({k: v for k, v in qs.items() if v})
    return render(request, "audit.html", entries=rows, entities=ENTITIES, msg=msg,
                  revertible=audit_revert.REVERTERS,
                  admin_filter=admin_filter, entity=entity, date_from=date_from, date_to=date_to,
                  page=page, prev_url=url(page - 1) if page > 1 else None,
                  next_url=url(page + 1) if has_next else None)


@router.post("/audit/{entry_id}/revert", dependencies=[Depends(verify_csrf)])
async def audit_revert_entry(entry_id: int, admin: str = Depends(require_admin)):
    try:
        await audit_revert.revert(entry_id, admin)
        msg = "Alteração revertida."
    except ValueError as e:
        msg = f"Erro: {e}"
    except LookupError:
        msg = "Erro: o item alterado não existe mais."
    return RedirectResponse("/admin/audit?" + urlencode({"msg": msg}), status_code=303)
