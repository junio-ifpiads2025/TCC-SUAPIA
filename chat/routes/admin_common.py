"""
Peças compartilhadas do painel admin: templates Jinja2, sessão e CSRF.

Contrato usado por todos os routers do painel (routes/admin_*.py):
- `require_admin`  : dependência FastAPI; devolve o admin logado (matrícula SUAP ou
                     o usuário de bootstrap do .env).
- `verify_csrf`    : dependência para todo POST/PUT/DELETE de formulário/HTMX.
- `render(request, template, **ctx)` : renderiza web/admin/<template> com
  `request`, `csrf_token` e `admin_user` já no contexto.

A sessão vive num cookie assinado (itsdangerous) com o usuário e o token CSRF.
"""

import secrets
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

import config
from services import admin_user_service
from config import ADMIN_PASSWORD, ADMIN_SESSION_SECRET, ADMIN_SESSION_TTL_SECONDS, ADMIN_USERNAME  # noqa: F401

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "admin"
# autoescape ligado por padrão para .html (resolve o XSS do painel antigo)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

COOKIE_NAME = "admin_session"
_SALT = "admin-session"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(ADMIN_SESSION_SECRET, salt=_SALT)


def _check_enabled() -> None:
    if not ADMIN_PASSWORD or not ADMIN_SESSION_SECRET:
        raise HTTPException(status_code=503, detail="Painel desabilitado: configure ADMIN_PASSWORD e ADMIN_SESSION_SECRET.")


def create_session_cookie(response: Response, username: str, bootstrap: bool = False) -> None:
    """
    Grava o cookie de sessão assinado (usuário + token CSRF novo).

    `bootstrap` marca o login de emergência do .env; os demais são matrículas SUAP,
    revalidadas contra a tabela de admins a cada requisição.
    """
    _check_enabled()
    value = _serializer().dumps({"u": username, "csrf": secrets.token_urlsafe(32), "b": bootstrap})
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=str(config.APP_BASE_URL).lower().startswith("https://"),
        path="/admin",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/admin")


def get_session(request: Request) -> dict | None:
    """Lê e valida o cookie; None se ausente, adulterado ou expirado."""
    cached = getattr(request.state, "admin_session", False)
    if cached is not False:
        return cached
    data = None
    raw = request.cookies.get(COOKIE_NAME)
    if raw and ADMIN_SESSION_SECRET:
        try:
            parsed = _serializer().loads(raw, max_age=ADMIN_SESSION_TTL_SECONDS)
            if isinstance(parsed, dict) and parsed.get("u") and parsed.get("csrf"):
                data = parsed
        except BadSignature:
            data = None
    request.state.admin_session = data
    return data


async def require_admin(request: Request) -> str:
    _check_enabled()
    session = get_session(request)
    # admin removido da lista perde o acesso mesmo com o cookie ainda válido
    if session is not None and not session.get("b"):
        try:
            if not await admin_user_service.is_admin(session["u"]):
                session = None
                request.state.admin_session = None
        except Exception:
            session = None
    if session is None:
        if request.url.path.startswith("/admin/api/"):
            raise HTTPException(status_code=401, detail="Não autenticado.")
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return session["u"]


def is_bootstrap(request: Request) -> bool:
    session = get_session(request)
    return bool(session and session.get("b"))


async def verify_csrf(request: Request) -> None:
    """Valida o token CSRF (header X-CSRF-Token ou campo csrf_token) contra a sessão."""
    session = get_session(request)
    expected = session["csrf"] if session else ""
    sent = request.headers.get("x-csrf-token", "")
    if not sent and "form" in request.headers.get("content-type", ""):
        form = await request.form()
        value = form.get("csrf_token", "")
        sent = value if isinstance(value, str) else ""
    if not expected or not sent or not secrets.compare_digest(sent.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Token CSRF inválido.")


def render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    session = get_session(request)
    ctx.setdefault("csrf_token", session["csrf"] if session else "")
    ctx.setdefault("admin_user", session["u"] if session else "admin")
    ctx.setdefault("is_bootstrap", bool(session and session.get("b")))
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
