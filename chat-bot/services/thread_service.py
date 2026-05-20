"""
Histórico de conversa por chat_id armazenado no Redis.

Cada par (mensagem do aluno + resposta do agente) é salvo como entrada na lista
Redis `suap:thread:<chat_id>`. O histórico é injetado no contexto do LLM a cada
nova mensagem, permitindo que o agente referencie respostas anteriores sem
precisar chamar o SUAP novamente.

Limites:
- Máximo de 10 pares (20 mensagens) — as mais antigas são descartadas.
- TTL igual ao da sessão — histórico expira junto com o login.
- O histórico é apagado no /sair.
"""

import json

from services.session_service import get_redis
from config import SESSION_TTL_SECONDS, THREAD_HISTORY_PAIRS

# Máximo de mensagens armazenadas no Redis (configurável via THREAD_HISTORY_PAIRS)
# Guarda o dobro de pares para ter margem de armazenamento mesmo com config baixa
_MAX_STORED = THREAD_HISTORY_PAIRS * 2 * 2  # buffer 2x do que será injetado


def _thread_key(chat_id: str) -> str:
    return f"suap:thread:{chat_id}"


async def get_thread(chat_id: str) -> list[dict]:
    """
    Retorna os últimos THREAD_HISTORY_PAIRS pares do histórico no formato OpenAI.
    Injetar só os pares mais recentes mantém o contexto relevante sem inflar o prompt.
    """
    r = get_redis()
    # Pega apenas as últimas N*2 mensagens (N pares)
    raw = await r.lrange(_thread_key(chat_id), -(THREAD_HISTORY_PAIRS * 2), -1)
    return [json.loads(m) for m in raw]


async def append_messages(chat_id: str, user_msg: str, assistant_msg: str) -> None:
    """
    Adiciona o par (user, assistant) ao histórico e descarta os mais antigos
    se ultrapassar o limite de _MAX_MESSAGES. Renova o TTL a cada interação.
    """
    r = get_redis()
    key = _thread_key(chat_id)

    # Pipeline atômico: push dos dois entries + trim + renovação do TTL
    async with r.pipeline() as pipe:
        pipe.rpush(key, json.dumps({"role": "user", "content": user_msg}))
        pipe.rpush(key, json.dumps({"role": "assistant", "content": assistant_msg}))
        # Mantém apenas as _MAX_MESSAGES mais recentes
        pipe.ltrim(key, -_MAX_STORED, -1)
        pipe.expire(key, SESSION_TTL_SECONDS)
        await pipe.execute()


async def clear_thread(chat_id: str) -> None:
    """Apaga o histórico de conversa. Chamado no /sair."""
    await get_redis().delete(_thread_key(chat_id))
