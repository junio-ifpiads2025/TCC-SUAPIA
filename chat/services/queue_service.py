"""
Serviço de fila de mensagens do SUAP-IA.

Gerencia o ciclo de vida completo de uma mensagem recebida:
  enqueue() → process_next() → _process_message() → completed/failed

A fila é armazenada no PostgreSQL (tabela message_queue), garantindo
persistência mesmo em caso de reinício da aplicação.

Garantias de ordem e concorrência:
- Mesmo chat_id: processamento FIFO — uma mensagem por vez (RN08).
- chat_ids distintos: processados em paralelo via asyncio.gather (RN08).
- Mensagens travadas em 'processing' são marcadas como 'failed' pelo
  stale_cleaner após QUEUE_TIMEOUT_MINUTES (RN07).
"""

import asyncio
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from config import AGENT_NAME, MAX_DAILY_MESSAGES, QUEUE_TIMEOUT_MINUTES
from models.database import AsyncSessionLocal, MessageQueue
from services import logger
from services.auth_service import generate_onboarding_link, logout
from services.message_router import route
from services.messaging_client import enviar_texto_async, marcar_lida_async, iniciar_digitacao_async
from services.session_service import delete_token, increment_rate, is_authenticated, get_profile, delete_profile
from services import thread_service


async def enqueue(chat_id: str, content: str, message_id: str | None = None) -> None:
    """
    Ponto de entrada para toda mensagem recebida do webhook.

    Antes de enfileirar, executa validações em ordem:
      1. Comando /sair — encerra sessão imediatamente, sem enfileirar.
      2. Autenticação (RF01/RF10) — se não autenticado, envia link de onboarding.
      3. Rate limit diário (RN06) — se cota esgotada, envia aviso.
      4. Insere na fila com status='pending' (RF11).
    """
    # Marca como lida imediatamente ao receber — antes de qualquer processamento (WAHA anti-ban)
    await marcar_lida_async(chat_id, message_id)

    # /sair é tratado aqui e não entra na fila, pois não precisa do agente
    if content.strip() == "/sair":
        await delete_token(chat_id)
        await logout(chat_id)
        await delete_profile(chat_id)
        await thread_service.clear_thread(chat_id)  # apaga histórico junto com a sessão
        await enviar_texto_async(
            chat_id,
            "Sessão encerrada. Na próxima mensagem você receberá o link de login.",
        )
        return

    # RF10: usuário não autenticado recebe link de onboarding e a mensagem é descartada
    if not await is_authenticated(chat_id):
        link = await generate_onboarding_link(chat_id)
        await enviar_texto_async(
            chat_id,
            f"Olá! Para usar o {AGENT_NAME}, acesse o link abaixo para fazer login com sua conta SUAP "
            f"(válido por 15 minutos):\n\n{link}",
        )
        return

    # RN06: incrementa contador diário antes de enfileirar;
    # o TTL da chave Redis é ajustado para expirar à meia-noite BRT
    count = await increment_rate(chat_id)
    if count > MAX_DAILY_MESSAGES:
        await enviar_texto_async(
            chat_id,
            "Você atingiu o limite de 25 mensagens por dia. Tente novamente amanhã.",
        )
        return

    # RF11: persiste a mensagem na fila com status inicial 'pending'
    async with AsyncSessionLocal() as session:
        session.add(MessageQueue(chat_id=chat_id, content=content, status="pending"))
        await session.commit()

    logger.info("QUEUE", f"Enfileirado — chat_id={chat_id}")


async def _process_message(msg_id: int, chat_id: str, content: str) -> None:
    """
    Processa uma única mensagem da fila.

    Fluxo:
      1. Marca como 'processing' (impede que process_next() a pegue novamente).
      2. Chama o roteador de mensagens (RAG / agente).
      3. Envia a resposta via WAHA.
      4. Atualiza status para 'completed' ou 'failed' com detalhes do erro.

    A re-busca do registro antes de atualizar o status garante que a sessão
    SQLAlchemy não fique aberta durante o processamento (que pode demorar).
    """
    # Marca como 'processing' em sessão separada para liberar o lock rapidamente
    async with AsyncSessionLocal() as session:
        msg = await session.get(MessageQueue, msg_id)
        if not msg or msg.status != "pending":
            # Mensagem pode ter sido cancelada ou já processada por outra task
            return
        msg.status = "processing"
        msg.updated_at = datetime.now(timezone.utc)
        await session.commit()

    try:
        logger.incoming(chat_id, content)
        await iniciar_digitacao_async(chat_id)  # mostra "digitando..." durante o processamento do LLM
        resposta, _ = await route(chat_id, content)

        profile = await get_profile(chat_id)
        if profile and profile.get("nome"):
            primeiro_nome = profile["nome"].split()[0]
            resposta = f"{primeiro_nome}, {resposta}"

        logger.response_log(resposta)
        await enviar_texto_async(chat_id, resposta)
        status, error_detail = "completed", None
    except Exception as e:
        logger.error("QUEUE", f"Erro ao processar id={msg_id} chat_id={chat_id}: {e}")
        status, error_detail = "failed", str(e)

    # Atualiza o status final em nova sessão após o processamento
    async with AsyncSessionLocal() as session:
        msg = await session.get(MessageQueue, msg_id)
        if msg:
            msg.status = status
            msg.error_detail = error_detail
            msg.updated_at = datetime.now(timezone.utc)
            await session.commit()


async def process_next() -> None:
    """
    Seleciona e dispara o processamento das próximas mensagens pendentes.

    Estratégia (RN08):
    - Exclui chat_ids que já têm uma mensagem em 'processing' (garante FIFO por chat_id).
    - Para os demais, pega a mensagem mais antiga de cada chat_id.
    - Processa todos os chat_ids elegíveis em paralelo com asyncio.gather.

    Chamado a cada 1s pelo _queue_worker em main.py.
    """
    async with AsyncSessionLocal() as session:
        # Descobre quais chat_ids já estão sendo processados no momento
        busy_result = await session.execute(
            select(MessageQueue.chat_id).where(MessageQueue.status == "processing")
        )
        busy = {row[0] for row in busy_result.fetchall()}

        # Busca pendentes excluindo chat_ids ocupados, ordenados por criação (FIFO)
        q = select(MessageQueue).where(MessageQueue.status == "pending")
        if busy:
            q = q.where(MessageQueue.chat_id.not_in(busy))
        q = q.order_by(MessageQueue.created_at.asc())

        pending = (await session.execute(q)).scalars().all()

    # Seleciona apenas a primeira mensagem de cada chat_id (a mais antiga)
    seen: set[str] = set()
    tasks = []
    for msg in pending:
        if msg.chat_id not in seen:
            seen.add(msg.chat_id)
            tasks.append(asyncio.create_task(_process_message(msg.id, msg.chat_id, msg.content)))

    # return_exceptions=True evita que uma falha numa task cancele as demais
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def cleanup_stale() -> None:
    """
    Marca como 'failed' mensagens que ficaram travadas em 'processing' por tempo
    superior a QUEUE_TIMEOUT_MINUTES (RN07).

    Isso cobre cenários de crash da task ou timeout no agente sem tratamento de exceção.
    Chamado a cada 60s pelo _stale_cleaner em main.py.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=QUEUE_TIMEOUT_MINUTES)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MessageQueue)
            .where(MessageQueue.status == "processing")
            .where(MessageQueue.updated_at < cutoff)
        )
        stale = result.scalars().all()
        for msg in stale:
            msg.status = "failed"
            msg.error_detail = "timeout"
            msg.updated_at = datetime.now(timezone.utc)
            logger.warn("QUEUE", f"Timeout — id={msg.id} chat_id={msg.chat_id}")
        if stale:
            await session.commit()
