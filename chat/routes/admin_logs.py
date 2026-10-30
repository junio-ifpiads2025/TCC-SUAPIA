"""Tela /admin/logs: log de acesso com filtros (usuário, evento, data) e paginação."""

from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from routes.admin_common import render, require_admin
from services import access_log_service, pdf_report

router = APIRouter(prefix="/admin", tags=["admin"])

EVENTS = ["received", "blocked", "denied", "rate_limited", "guardrail_input",
          "guardrail_output", "answered", "failed",
          "admin_login", "admin_login_failed", "admin_logout", "admin_acl_add", "admin_acl_remove",
          "admin_prompt_save", "admin_prompt_activate", "admin_skill_create", "admin_skill_update",
          "admin_skill_delete", "admin_guardrail_create", "admin_guardrail_update",
          "admin_guardrail_delete", "admin_knowledge_create", "admin_knowledge_update",
          "admin_knowledge_delete", "admin_queue_cancel", "admin_queue_requeue", "admin_admin_add", "admin_admin_remove"]
PAGE_SIZE = 50
EXPORT_LIMIT = 1000


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@router.get("/logs")
async def logs_page(
    request: Request,
    chat_id: str = "",
    event: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    admin: str = Depends(require_admin),
):
    page = max(page, 1)
    event = event if event in EVENTS else ""
    # busca uma linha a mais para saber se existe próxima página
    rows = await access_log_service.list_logs(
        chat_id=chat_id.strip() or None,
        event=event or None,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        limit=PAGE_SIZE + 1,
        offset=(page - 1) * PAGE_SIZE,
    )
    has_next = len(rows) > PAGE_SIZE

    def url(p: int) -> str:
        qs = {"chat_id": chat_id, "event": event, "date_from": date_from, "date_to": date_to, "page": p}
        return "/admin/logs?" + urlencode({k: v for k, v in qs.items() if v})
    export_qs = urlencode({k: v for k, v in (("chat_id", chat_id), ("event", event),
                                              ("date_from", date_from), ("date_to", date_to)) if v})
    return render(request, "logs.html", logs=rows[:PAGE_SIZE], events=EVENTS, export_qs=export_qs,
                  chat_id=chat_id, event=event, date_from=date_from, date_to=date_to,
                  page=page, prev_url=url(page - 1) if page > 1 else None,
                  next_url=url(page + 1) if has_next else None)


@router.get("/logs/export.pdf")
async def logs_pdf(
    chat_id: str = "",
    event: str = "",
    date_from: str = "",
    date_to: str = "",
    admin: str = Depends(require_admin),
):
    event = event if event in EVENTS else ""
    rows = await access_log_service.list_logs(
        chat_id=chat_id.strip() or None,
        event=event or None,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        limit=EXPORT_LIMIT,
    )
    filters = " · ".join(f"{k}: {v}" for k, v in
                         (("usuário", chat_id.strip()), ("evento", event),
                          ("de", date_from), ("até", date_to)) if v)
    return Response(pdf_report.logs_pdf(rows, filters), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="suapia-logs.pdf"'})
