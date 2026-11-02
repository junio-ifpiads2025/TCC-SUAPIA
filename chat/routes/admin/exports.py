"""
Exportações do painel: CSV de logs, uso, casos de qualidade e auditoria, e JSON da
base de conhecimento. Cada download fica registrado no log (`admin_export`).

Incluído antes do router de knowledge: `/api/knowledge/export.json` não pode ser
capturado por `/api/knowledge/{doc_id}`.
"""

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse

from routes.admin.audit import ENTITIES as AUDIT_ENTITIES
from routes.admin.common import parse_date, require_admin
from routes.admin.logs import EVENTS
from routes.admin.usage import PERIODS
from services.admin import export_service
from services.shared import access_log_service, audit_service, usage_service

router = APIRouter(prefix="/admin", tags=["admin"])

EXPORT_LIMIT = 5000


def _csv(rows, columns: list[str], name: str) -> StreamingResponse:
    filename = f"suapia-{name}-{date.today().isoformat()}.csv"
    return StreamingResponse(export_service.csv_lines(rows, columns), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/logs/export.csv")
async def logs_csv(chat_id: str = "", event: str = "", date_from: str = "", date_to: str = "",
                   admin: str = Depends(require_admin)):
    event = event if event in EVENTS else ""
    rows = await access_log_service.list_logs(
        chat_id=chat_id.strip() or None, event=event or None,
        date_from=parse_date(date_from), date_to=parse_date(date_to), limit=EXPORT_LIMIT)
    access_log_service.log_admin(admin, "export", "kind=logs")
    return _csv(export_service.mask_rows(rows), export_service.LOG_COLUMNS, "logs")


@router.get("/usage/export.csv")
async def usage_csv(days: int = 30, admin: str = Depends(require_admin)):
    report = await usage_service.report(days if days in PERIODS else 30)
    access_log_service.log_admin(admin, "export", "kind=usage")
    return _csv(report["daily"], export_service.USAGE_COLUMNS, f"uso-{report['days']}d")


@router.get("/export/quality.csv")
async def quality_csv(kind: str = "", admin: str = Depends(require_admin)):
    rows = await export_service.qa_cases(kind or None, EXPORT_LIMIT)
    access_log_service.log_admin(admin, "export", "kind=quality")
    return _csv(rows, export_service.QA_COLUMNS, "qualidade")


@router.get("/export/audit.csv")
async def audit_csv(admin_filter: str = "", entity: str = "", date_from: str = "", date_to: str = "",
                    admin: str = Depends(require_admin)):
    rows = await audit_service.list_entries(
        admin=admin_filter.strip() or None,
        entity=entity if entity in AUDIT_ENTITIES else None,
        date_from=parse_date(date_from), date_to=parse_date(date_to), limit=EXPORT_LIMIT)
    access_log_service.log_admin(admin, "export", "kind=audit")
    return _csv(rows, export_service.AUDIT_COLUMNS, "auditoria")


@router.get("/api/knowledge/export.json")
async def knowledge_json(admin: str = Depends(require_admin)):
    body = await export_service.knowledge_json()
    access_log_service.log_admin(admin, "export", "kind=knowledge")
    filename = f"suapia-conhecimento-{date.today().isoformat()}.json"
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
