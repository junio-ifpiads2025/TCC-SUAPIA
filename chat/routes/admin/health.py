"""Saúde do sistema: /admin/health (sondas, reconectar provider) e /health público mínimo."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from routes.admin.common import render, require_admin, verify_csrf
from services.admin import health_service

router = APIRouter(prefix="/admin", tags=["admin"])
# Montado na raiz em main.py: monitoramento externo, sem autenticação e sem detalhes
public_router = APIRouter(tags=["health"])


async def _context() -> dict:
    return {"checks": await health_service.check_all(),
            "last_failure": await health_service.last_failure()}


@router.get("/health")
async def health_page(request: Request, msg: str = "", admin: str = Depends(require_admin)):
    return render(request, "health.html", msg=msg, **await _context())


@router.get("/health/table")
async def health_table(request: Request, admin: str = Depends(require_admin)):
    return render(request, "_health_table.html", **await _context())


@router.post("/health/{provider}/reconnect", dependencies=[Depends(verify_csrf)])
async def health_reconnect(provider: str, admin: str = Depends(require_admin)):
    try:
        ok = await health_service.reconnect(provider)
        msg = "Reconexão solicitada." if ok else "Erro: a plataforma não aceitou a reconexão."
    except KeyError:
        msg = "Erro: provider não habilitado."
    return RedirectResponse("/admin/health?" + urlencode({"msg": msg}), status_code=303)


@public_router.get("/health")
async def public_health():
    ok = await health_service.check_core()
    return JSONResponse({"status": "ok" if ok else "degraded"}, status_code=200 if ok else 503)
