"""Tela /admin/usage: gráficos de uso e consumo de tokens, com export em PDF."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from routes.admin_common import render, require_admin
from services import pdf_report, usage_service

router = APIRouter(prefix="/admin", tags=["admin"])

PERIODS = (7, 30, 90)


def _days(value: int) -> int:
    return value if value in PERIODS else 30


@router.get("/usage")
async def usage_page(request: Request, days: int = 30, admin: str = Depends(require_admin)):
    days = _days(days)
    return render(request, "usage.html", report=await usage_service.report(days), days=days, periods=PERIODS)


@router.get("/usage/export.pdf")
async def usage_pdf(days: int = 30, admin: str = Depends(require_admin)):
    pdf = pdf_report.usage_report_pdf(await usage_service.report(_days(days)))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="suapia-uso-{_days(days)}d.pdf"'})
