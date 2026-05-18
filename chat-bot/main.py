from contextlib import asynccontextmanager

from fastapi import FastAPI

from models.database import init_db
from routes.auth import router as auth_router
from routes.webhook import router as webhook_router
from services import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.success("BOOT", "Banco de dados inicializado")
    yield


app = FastAPI(title="SUAP-IA WhatsApp Bot", lifespan=lifespan)

app.include_router(webhook_router)
app.include_router(auth_router)
