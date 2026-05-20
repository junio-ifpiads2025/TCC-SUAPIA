"""
Fluxo de autenticação web do SUAP-IA.

O usuário recebe um link único via WhatsApp, acessa no navegador,
informa matrícula e senha do SUAP, e o token de acesso é armazenado
no Redis associado ao seu chat_id.

Endpoints:
  GET  /auth/login?token=<uuid>  — exibe o formulário de login.
  POST /auth/login?token=<uuid>  — processa credenciais e autentica.

O token UUID é de uso único e expira em 15 minutos (gerenciado pelo Redis).
"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, Query
from fastapi.responses import HTMLResponse

from services import logger
from services.auth_service import login_with_suap
from services.session_service import get_onboarding_link, delete_onboarding_link
from services.messaging_client import enviar_texto_async
from config import AGENT_NAME, MENU_TEXT

router = APIRouter(prefix="/auth")

# Caminho absoluto para o arquivo HTML do formulário de login
_LOGIN_HTML = Path(__file__).parent.parent / "web" / "login.html"


def _render_html(token: str) -> str:
    """
    Lê o template HTML e substitui os placeholders pelo token e nome do agente.
    O token é inserido no formulário para ser reenviado no POST.
    """
    return (
        _LOGIN_HTML.read_text(encoding="utf-8")
        .replace("{{TOKEN}}", token)
        .replace("{{AGENT_NAME}}", AGENT_NAME)
    )


def _result_page(title: str, message: str, success: bool) -> str:
    """Gera página de resultado (sucesso ou erro) após tentativa de login."""
    color = "#16a34a" if success else "#dc2626"
    icon = "✅" if success else "❌"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{AGENT_NAME} — {title}</title>
  <style>
    body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
         background:#f0f4f8;font-family:'Segoe UI',sans-serif;}}
    .card{{background:#fff;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.1);
           padding:2.5rem 2rem;width:100%;max-width:400px;text-align:center;}}
    h2{{color:{color};font-size:1.4rem;margin-bottom:1rem;}}
    p{{color:#374151;font-size:.95rem;}}
  </style>
</head>
<body>
  <div class="card">
    <h2>{icon} {title}</h2>
    <p>{message}</p>
  </div>
</body>
</html>"""


@router.get("/login", response_class=HTMLResponse)
async def login_page(token: str = Query(...)):
    """
    Exibe o formulário de login se o token UUID ainda for válido.
    O token é validado contra o Redis — se expirado ou já usado, retorna 400.
    """
    chat_id = await get_onboarding_link(token)
    if not chat_id:
        return HTMLResponse(
            _result_page("Link inválido", "Este link expirou ou já foi utilizado.", success=False),
            status_code=400,
        )
    return HTMLResponse(_render_html(token))


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    background_tasks: BackgroundTasks,
    token: str = Query(...),
    matricula: str = Form(...),
    senha: str = Form(...),
):
    """
    Processa as credenciais enviadas pelo formulário.

    Fluxo em caso de sucesso:
      1. Valida o token de onboarding (ainda pode ter expirado entre GET e POST).
      2. Autentica no SUAP e armazena o token no Redis.
      3. Invalida o link de onboarding (uso único).
      4. Notifica o usuário no WhatsApp em background (não bloqueia a resposta HTTP).

    Em caso de falha, retorna 401 e envia aviso pelo WhatsApp.
    """
    chat_id = await get_onboarding_link(token)
    if not chat_id:
        return HTMLResponse(
            _result_page("Link inválido", "Este link expirou ou já foi utilizado.", success=False),
            status_code=400,
        )

    result = await login_with_suap(chat_id, matricula, senha)

    if result.success:
        # Invalida o token imediatamente para evitar reuso
        await delete_onboarding_link(token)
        logger.success("AUTH_WEB", f"Login via web concluído — chat_id={chat_id}")

        # Notificações enviadas em background para não atrasar a resposta HTML
        background_tasks.add_task(
            enviar_texto_async,
            chat_id,
            "✅ Login realizado com sucesso! Agora você já pode enviar suas perguntas sobre o SUAP aqui no WhatsApp.",
        )
        background_tasks.add_task(enviar_texto_async, chat_id, MENU_TEXT)
        return HTMLResponse(
            _result_page("Login realizado!", result.message, success=True)
        )

    # Falha: avisa o usuário pelo WhatsApp para que ele saiba tentar de novo
    background_tasks.add_task(
        enviar_texto_async,
        chat_id,
        f"❌ Falha no login: {result.message}",
    )
    return HTMLResponse(
        _result_page("Erro no login", result.message, success=False),
        status_code=401,
    )
