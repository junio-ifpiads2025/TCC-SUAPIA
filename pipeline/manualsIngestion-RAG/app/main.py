from fastapi import FastAPI
from app.url.url import router as ingestao_router

app = FastAPI(
    title="API de Ingestão Vetorial (RAG)",
    description="Microsserviço independente responsável por vetorizar dados JSON no Qdrant.",
    version="1.0.0"
)

app.include_router(ingestao_router, prefix="/api/v1")