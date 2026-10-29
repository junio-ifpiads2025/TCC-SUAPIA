"""
Painel de monitoramento da fila de mensagens.

Endpoint de uso interno para visualizar o estado atual da fila no PostgreSQL.
Protegido por HTTP Basic Auth — credenciais configuradas via ADMIN_USERNAME
e ADMIN_PASSWORD nas variáveis de ambiente.

Exibe apenas mensagens com status 'pending' ou 'processing'.
A página usa meta refresh para atualizar automaticamente a cada 10 segundos.
"""

import secrets

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import HTTPException
from sqlalchemy import select

from models.database import AsyncSessionLocal, MessageQueue
from config import ADMIN_USERNAME, ADMIN_PASSWORD

router = APIRouter(prefix="/admin", tags=["admin"])
_security = HTTPBasic()


def _check_auth(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    """
    Valida as credenciais de Basic Auth contra as variáveis de ambiente.
    Usa secrets.compare_digest para evitar timing attacks.
    Lança 401 se as credenciais forem inválidas ou se ADMIN_PASSWORD estiver vazio.
    """
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Painel desabilitado: ADMIN_PASSWORD não configurado.")

    usuario_ok = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    senha_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)

    if not (usuario_ok and senha_ok):
        raise HTTPException(
            status_code=401,
            detail="Credenciais inválidas.",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/queue", response_class=HTMLResponse)
async def queue_dashboard(_: None = Depends(_check_auth)):
    """
    Retorna página HTML com a fila de mensagens pendentes e em processamento.
    Requer autenticação via HTTP Basic Auth.
    Atualiza automaticamente a cada 10 segundos via meta refresh.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MessageQueue)
            .where(MessageQueue.status.in_(["pending", "processing"]))
            .order_by(MessageQueue.created_at.asc())
        )
        rows = result.scalars().all()

    # Gera as linhas da tabela com formatação condicional por status
    rows_html = "".join(
        f"<tr>"
        f"<td>{r.id}</td>"
        f"<td>{r.chat_id}</td>"
        f"<td class='content'>{r.content}</td>"
        f"<td><span class='badge badge-{'orange' if r.status == 'processing' else 'blue'}'>{r.status}</span></td>"
        f"<td>{r.created_at.strftime('%d/%m/%Y %H:%M:%S')}</td>"
        f"<td>{r.updated_at.strftime('%d/%m/%Y %H:%M:%S') if r.updated_at else '—'}</td>"
        f"<td>{r.error_detail or '—'}</td>"
        f"</tr>"
        for r in rows
    )

    html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="10">
  <title>SUAP-IA · Fila de Mensagens</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: sans-serif; padding: 2rem; background: #f0f2f5; color: #333; }}
    h1 {{ margin-bottom: .5rem; font-size: 1.4rem; }}
    .meta {{ font-size: .85rem; color: #666; margin-bottom: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.12); }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: .6rem 1rem; text-align: left; font-size: .875rem; }}
    th {{ background: #1d4ed8; color: #fff; font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f8fafc; }}
    .content {{ max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: .78rem; font-weight: 600; color: #fff; }}
    .badge-orange {{ background: #f97316; }}
    .badge-blue {{ background: #3b82f6; }}
    .empty {{ color: #9ca3af; font-style: italic; padding: 1.5rem; }}
    footer {{ margin-top: 1rem; font-size: .78rem; color: #9ca3af; }}
  </style>
</head>
<body>
  <h1>SUAP-IA · Fila de Mensagens</h1>
  <p class="meta">Total aguardando: <strong>{len(rows)}</strong> &nbsp;|&nbsp; Atualiza automaticamente a cada 10s.</p>
  <table>
    <thead>
      <tr>
        <th>#</th><th>chat_id</th><th>Conteúdo</th><th>Status</th><th>Criado em</th><th>Atualizado em</th><th>Erro</th>
      </tr>
    </thead>
    <tbody>
      {rows_html if rows_html else '<tr><td colspan="7" class="empty">Nenhuma mensagem aguardando.</td></tr>'}
    </tbody>
  </table>
  <footer>Somente mensagens com status <em>pending</em> ou <em>processing</em> são exibidas.</footer>
</body>
</html>"""
    return HTMLResponse(content=html)
