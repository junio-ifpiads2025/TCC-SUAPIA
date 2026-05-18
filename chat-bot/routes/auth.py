from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, Query
from fastapi.responses import HTMLResponse

from services import logger
from services.auth_service import login_with_suap
from services.session_service import get_onboarding_link, delete_onboarding_link
from services.messaging_client import enviar_texto_async

router = APIRouter(prefix="/auth")

_LOGIN_HTML = Path(__file__).parent.parent / "web" / "login.html"


def _render_html(token: str) -> str:
    return _LOGIN_HTML.read_text(encoding="utf-8").replace("{{TOKEN}}", token)


def _result_page(title: str, message: str, success: bool) -> str:
    color = "#16a34a" if success else "#dc2626"
    icon = "✅" if success else "❌"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>SUAP-IA — {title}</title>
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
    chat_id = await get_onboarding_link(token)
    if not chat_id:
        return HTMLResponse(
            _result_page("Link inválido", "Este link expirou ou já foi utilizado.", success=False),
            status_code=400,
        )

    result = await login_with_suap(chat_id, matricula, senha)

    if result.success:
        await delete_onboarding_link(token)
        logger.success("AUTH_WEB", f"Login via web concluído — chat_id={chat_id}")
        background_tasks.add_task(
            enviar_texto_async,
            chat_id,
            "✅ Login realizado com sucesso! Agora você já pode enviar suas perguntas sobre o SUAP aqui no WhatsApp.",
        )
        return HTMLResponse(
            _result_page("Login realizado!", result.message, success=True)
        )

    background_tasks.add_task(
        enviar_texto_async,
        chat_id,
        f"❌ Falha no login: {result.message}",
    )
    return HTMLResponse(
        _result_page("Erro no login", result.message, success=False),
        status_code=401,
    )
