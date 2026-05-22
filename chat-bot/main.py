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
from services import logger
from services import queue_service
from config import AGENT_NAME


async def _queue_worker() -> None:
    """
    Loop infinito que aciona o processamento da fila a cada 1 segundo.
    Roda como task asyncio dentro do mesmo processo da aplicação — não é um
    processo externo. Erros são capturados para não derrubar a task.
    """
    while True:
        try:
            await queue_service.process_next()
        except Exception as e:
            logger.error("WORKER", f"queue_worker: {e}")
        await asyncio.sleep(1)


async def _stale_cleaner() -> None:
    """
    Loop infinito que verifica mensagens travadas no status 'processing' a cada 60s.
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

    asyncio.create_task(_queue_worker())
    asyncio.create_task(_stale_cleaner())
    logger.success("BOOT", "Tasks de background iniciadas")

    yield


app = FastAPI(title=f"{AGENT_NAME} WhatsApp Bot", lifespan=lifespan)

# Registro dos routers
app.include_router(webhook_router)   # POST /webhook
app.include_router(auth_router)      # GET/POST /auth/login
app.include_router(terms_router)     # GET /terms, GET /terms/view
app.include_router(admin_router)     # GET /admin/queue
