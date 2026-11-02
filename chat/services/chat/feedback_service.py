"""
Feedback do usuário sobre a última resposta, por texto: "1" útil, "2" não útil.

Funciona igual no WhatsApp e no Telegram (não depende de botões do provedor).
Depois de cada resposta do agente, `arm()` guarda a pergunta, a resposta e os
trechos usados no Redis (`suap:fb:pending:<chat_id>`) por PENDING_TTL_SECONDS
e a resposta ganha o pedido FEEDBACK_PROMPT. Se a próxima mensagem for "1" ou
"2", `handle()` consome a pendência e grava o caso:
- 👍 grava só o tipo (sem conteúdo);
- 👎 grava pergunta, resposta e trechos para revisão no painel.
Sem pendência, "1"/"2" seguem como mensagem normal para o agente.
"""

import json

from services.shared import qa_case_service
from services.shared.session_service import get_redis

PENDING_KEY = "suap:fb:pending:{chat_id}"
PENDING_TTL_SECONDS = 30 * 60
FEEDBACK_PROMPT = "\n\nEssa resposta foi útil? Responda *1* 👍 ou *2* 👎"
THANKS_TEXT = "Obrigado pelo feedback! 🙏"
_ANSWERS = {"1": "up", "2": "down"}


def _key(chat_id: str) -> str:
    return PENDING_KEY.format(chat_id=chat_id)


async def arm(chat_id: str, question: str, answer: str, chunks: list | None) -> None:
    """Guarda a pendência de feedback da última resposta (substitui a anterior)."""
    data = {"question": question, "answer": answer, "chunks": chunks or []}
    await get_redis().set(_key(chat_id), json.dumps(data, ensure_ascii=False, default=str),
                          ex=PENDING_TTL_SECONDS)


async def handle(chat_id: str, text: str) -> str | None:
    """
    Se `text` é "1"/"2" e há pendência, grava o caso e devolve o agradecimento.
    Caso contrário devolve None (a mensagem segue o fluxo normal).
    """
    kind = _ANSWERS.get((text or "").strip())
    if kind is None:
        return None
    raw = await get_redis().getdel(_key(chat_id))
    if raw is None:
        return None
    data = json.loads(raw)
    await qa_case_service.record(kind, chat_id, data.get("question"), data.get("answer"), data.get("chunks"))
    return THANKS_TEXT


async def clear(chat_id: str) -> None:
    await get_redis().delete(_key(chat_id))
