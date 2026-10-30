"""
Ponto de entrada da aplicação SUAP-IA.

Responsabilidades:
- Criar a instância FastAPI e registrar os routers.
- Inicializar o banco de dados na subida.
- Iniciar as tasks de background (processamento da fila e limpeza de stale).
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from models.database import init_db
from routes.admin import router as admin_router
from routes.auth import router as auth_router
from routes.terms import router as terms_router
from routes.webhook import router as webhook_router
from services import access_log_service, acl_service, logger, prompt_service, skill_service
from services import providers
from services import queue_service
from config import AGENT_NAME, QUEUE_CONSUMERS


async def _queue_worker() -> None:
    """
    Consumidor da fila Redis: process_next() bloqueia até 1s esperando item.
    Roda como task asyncio dentro do mesmo processo (QUEUE_CONSUMERS tasks).
    Erros são capturados para não derrubar a task.
    """
    while True:
        try:
            await queue_service.process_next()
        except Exception as e:
            logger.error("WORKER", f"queue_worker: {e}")
            await asyncio.sleep(1)


async def _stale_cleaner() -> None:
    """
    Loop infinito que verifica itens travados em 'processing' a cada 60s.
    Cobre o caso de falha ou crash durante o processamento (RN07).
    """
    while True:
        try:
            await queue_service.cleanup_stale()
        except Exception as e:
            logger.error("WORKER", f"stale_cleaner: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida da aplicação FastAPI.
    Tudo antes do `yield` roda na subida; o `yield` mantém a app rodando.
    As tasks são criadas aqui para garantir que o event loop já está ativo.
    """
    await init_db()
    logger.success("BOOT", "Banco de dados inicializado")

    # Caches em memória (ACL, prompt ativo, guardrails): carregados do Postgres na subida
    await acl_service.startup()
    await prompt_service.startup()
    await skill_service.startup()
    logger.success("BOOT", "Regras de acesso, prompt e guardrails carregados")

    await providers.start_all()

    # Itens que ficaram em 'processing' por queda anterior voltam para 'pending'
    await queue_service.recover_processing()
    for _ in range(max(1, QUEUE_CONSUMERS)):
        asyncio.create_task(_queue_worker())
    asyncio.create_task(_stale_cleaner())
    asyncio.create_task(access_log_service.retention_loop())
    logger.success("BOOT", "Tasks de background iniciadas")

    yield


app = FastAPI(title=f"{AGENT_NAME} WhatsApp Bot", lifespan=lifespan)

# Registro dos routers
app.include_router(webhook_router)   # POST /webhook
app.include_router(auth_router)      # GET/POST /auth/login
app.include_router(terms_router)     # GET /terms, GET /terms/view
app.include_router(admin_router)     # GET /admin/queue
