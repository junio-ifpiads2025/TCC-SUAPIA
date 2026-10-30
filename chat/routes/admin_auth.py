"""Login/logout do painel admin e página de resumo (/admin)."""

import logging
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routes import admin_common
from routes.admin_common import (
    clear_session_cookie,
    create_session_cookie,
    render,
    require_admin,
    templates,
    verify_csrf,
)
from services import access_log_service, admin_user_service, auth_service
from services.session_service import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

MAX_FAILURES = 5
LOCK_WINDOW_SECONDS = 15 * 60


def _fail_key(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"admin:login_fail:{ip}"


def _login_page(request: Request, error: str | None = None, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": error}, status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    admin_common._check_enabled()
    try:
        await require_admin(request)  # sessão ainda válida (e admin ainda autorizado)
        return RedirectResponse("/admin", status_code=303)
    except HTTPException:
        return _login_page(request)


@router.post("/login")
async def login(request: Request, username: str = Form(""), password: str = Form("")):
    admin_common._check_enabled()
    key = _fail_key(request)
    redis = None
    try:
        redis = get_redis()
        if int(await redis.get(key) or 0) >= MAX_FAILURES:
            return _login_page(request, "Muitas tentativas. Aguarde alguns minutos.", 429)
    except Exception:
        logger.warning("Throttle de login indisponível (Redis).")
        redis = None

    username = username.strip()
    bootstrap = (
        secrets.compare_digest(username.encode(), admin_common.ADMIN_USERNAME.encode())
        and secrets.compare_digest(password.encode(), admin_common.ADMIN_PASSWORD.encode())
    )
    ip = request.client.host if request.client else "unknown"
    error = None
    status = 401
    if not bootstrap:
        # matrícula SUAP: só admins cadastrados chegam a consultar o SUAP
        try:
            listed = bool(username) and await admin_user_service.is_admin(username)
        except Exception:
            logger.warning("Falha ao consultar admins.", exc_info=True)
            listed = False
        if listed:
            valid = await auth_service.verify_suap_credentials(username, password)
            if valid is None:
                return _login_page(request, "O SUAP está inacessível no momento. Tente novamente.", 503)
        else:
            valid = False
        if not valid:
            error = "Matrícula ou senha inválidas, ou sem permissão de administrador."
    if error:
        if redis is not None:
            try:
                if await redis.incr(key) == 1:
                    await redis.expire(key, LOCK_WINDOW_SECONDS)
            except Exception:
                logger.warning("Falha ao registrar tentativa de login.")
        # não grava o usuário digitado (pode ser senha no campo errado); só o IP
        access_log_service.log_admin("unknown", "login_failed", f"ip={ip}")
        return _login_page(request, error, status)

    if redis is not None:
        try:
            await redis.delete(key)
        except Exception:
            pass
    access_log_service.log_admin(username, "login", f"ip={ip}")
    response = RedirectResponse("/admin", status_code=303)
    create_session_cookie(response, username, bootstrap=bootstrap)
    return response


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(admin: str = Depends(require_admin)):
    access_log_service.log_admin(admin, "logout")
    response = RedirectResponse("/admin/login", status_code=303)
    clear_session_cookie(response)
    return response


async def _safe(fn, default):
    """Executa fn (sync ou async) e devolve default em qualquer falha."""
    try:
        result = fn()
        if hasattr(result, "__await__"):
            result = await result
        return result
    except Exception:
        logger.warning("Falha ao coletar dado do resumo.", exc_info=True)
        return default


def _queue_stats():
    from services import queue_service

    return queue_service.stats()


def _acl_counts():
    from services import acl_service  # módulo de outro agente; pode não existir ainda

    return acl_service.counts()


def _prompt_info():
    from services import prompt_service  # módulo de outro agente; pode não existir ainda

    return prompt_service.active_info()


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, admin: str = Depends(require_admin)):
    queue = await _safe(_queue_stats, {"pending": 0, "processing": 0, "failed": 0})
    acl = await _safe(_acl_counts, {"allow": 0, "block": 0})
    answered = await _safe(lambda: access_log_service.count_today("answered"), 0)
    prompt = await _safe(_prompt_info, None)
    return render(request, "dashboard.html", queue=queue, acl=acl, answered=answered, prompt=prompt)
